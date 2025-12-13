import json
import os
import struct
import zipfile
import shutil # 用來移動資料夾

def send_json(sock, data_dict):
    """
    將 Python Dict 轉為 JSON -> 加上長度 Header -> 發送
    """
    # 1. 序列化: Dict -> JSON String -> Bytes
    json_str = json.dumps(data_dict)
    msg_bytes = json_str.encode('utf-8')
    
    # 2. 計算長度: 取得 bytes 的長度
    msg_len = len(msg_bytes)
    
    # 3. 打包 Header: '!I' 代表 Network byte order (Big-endian), Unsigned Int (4 bytes)
    header = struct.pack('!I', msg_len)
    
    # 4. 發送: Header + Body
    sock.sendall(header + msg_bytes)


def recv_json(sock):
    """
    接收 4 bytes Header -> 讀取對應長度 Body -> 解析 JSON 回傳 Dict
    若連線中斷則回傳 None
    """
    # 1. 先讀取 4 bytes (Header)
    header = recvall(sock, 4)
    if not header:
        return None # 連線已關閉
        
    # 2. 解包 Header 取得內容長度
    msg_len = struct.unpack('!I', header)[0]
    
    # 3. 根據長度讀取完整的 Body
    body_bytes = recvall(sock, msg_len)
    if not body_bytes:
        return None # 讀取 Body 途中發生錯誤或斷線
        
    # 4. 反序列化: Bytes -> JSON String -> Dict
    try:
        json_str = body_bytes.decode('utf-8')
        return json.loads(json_str)
    except json.JSONDecodeError:
        print("[Error] Received invalid JSON")
        return None

def recvall(sock, n):
    """
    輔助函式: 確保一定讀滿 n 個 bytes 才會 return
    解決 TCP 斷包問題 (例如一次只收到半個 JSON 的情況)
    """
    data = b''
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None # 對方關閉了連線
            data += packet
        except ConnectionResetError:
            return None
    return data

def send_file(sock, filepath):
    """
    流程：
    1. 檢查檔案是否存在
    2. 發送 JSON Header (包含檔名與大小)
    3. 發送檔案內容 (Binary)
    """
    if not os.path.exists(filepath):
        # 告訴 Client 檔案找不到
        error_msg = {"status": "error", "msg": "File not found"}
        send_json(sock, error_msg)
        return

    filesize = os.path.getsize(filepath)
    filename = os.path.basename(filepath)

    # 1. 先傳 Header
    header = {
        "status": "ok",
        "cmd": "file_download_header",
        "filename": filename,
        "size": filesize
    }
    send_json(sock, header)

    # 2. 再傳檔案內容 (分塊讀取，避免記憶體爆炸)
    with open(filepath, 'rb') as f:
        while True:
            # 每次讀 4096 bytes 傳送
            chunk = f.read(4096)
            if not chunk:
                break
            sock.sendall(chunk)
    
    print(f"[System] Sent file: {filename} ({filesize} bytes)")

def recv_file(sock, save_dir):
    """
    流程：
    1. 接收 JSON Header
    2. 解析檔案大小
    3. 循環接收 Binary 直到收滿大小
    4. 存檔
    """
    # 1. 等待 Header
    header = recv_json(sock)
    if not header or header.get('status') != 'ok':
        print(f"[Error] Download failed: {header.get('msg')}")
        return None

    filename = header['filename']
    filesize = header['size']
    save_path = os.path.join(save_dir, filename)

    print(f"[Download] Receiving {filename} ({filesize} bytes)...")

    # 2. 接收檔案內容
    received_size = 0
    with open(save_path, 'wb') as f:
        while received_size < filesize:
            # 計算還剩多少沒收
            remaining = filesize - received_size
            # 這次最多收 4096 或 剩下的量
            chunk_size = 4096 if remaining > 4096 else remaining
            
            chunk = sock.recv(chunk_size)
            if not chunk:
                break # 斷線保護
            
            f.write(chunk)
            received_size += len(chunk)

    print(f"[Download] Saved to {save_path}")
    return save_path

def validate_game_folder_to_client(folder_path):
    print(f"[Check] 正在檢查遊戲資料夾: {folder_path} ...")

    # 1. 檢查 manifest 是否存在
    manifest_path = os.path.join(folder_path, "manifest.json")
    if not os.path.exists(manifest_path):
        print("[Error] 找不到 manifest.json！ 目前無法下載此遊戲請稍後再試。")
        return False

    try:
        # 2. 嘗試讀取 manifest 內容
        with open(manifest_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 3. 檢查必要欄位
        required_keys = ["game_id", "version", "server_exe", "client_exe"]
        for key in required_keys:
            if key not in config:
                print(f"[Error] manifest.json 缺少必要欄位: {key}，目前無法下載此遊戲請稍後再試。")
                return False
        
        # 4. 檢查執行檔是否真的存在 (這步最重要！)
        # 因為 manifest 裡寫的路徑是相對路徑
        client_exe_path = os.path.join(folder_path, config["client_exe"])

        if not os.path.exists(client_exe_path):
            print(f"[Error] 找不到 Client 執行檔: {config['client_exe']}，目前無法下載此遊戲請稍後再試。")
            return False

    except json.JSONDecodeError:
        print("[Error] manifest.json 格式錯誤，無法解析 (Syntax Error)。")
        return False
    except Exception as e:
        print(f"[Error] 檢查過程發生未預期錯誤: {e}")
        return False

    print("[Check] 檢查通過！準備壓縮...")
    return True

def zip_game_folder_to_player(folder_path, output_zip_name="temp_game.zip", username = "developer"):
    """
    將指定資料夾的內容壓縮成 zip 檔
    回傳: 壓縮後的 zip 檔案路徑，如果失敗則回傳 None
    """
    # 1. 基本檢查
    if not os.path.exists(folder_path):
        print(f"[Error] Folder '{folder_path}' does not exist.")
        return None


    # 2. 檢查是否有 manifest.json (關鍵步驟！)
    if not validate_game_folder_to_client(folder_path):
        return None

    # 3. 開始壓縮
    print(f"[System] Zipping game files from '{folder_path}'...")
    
    try:
        with zipfile.ZipFile(output_zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 加入 manifest.json
            manifest_path = os.path.join(folder_path, 'manifest.json')
            zipf.write(manifest_path, arcname='manifest.json')
            # 加入 client 資料夾下所有檔案
            client_folder = os.path.join(folder_path, 'client')
            for root, dirs, files in os.walk(client_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, folder_path)  # 保留相對路徑
                    zipf.write(file_path, arcname)
        print(f"[System] Successfully packed into {output_zip_name}")
        return output_zip_name

    except Exception as e:
        print(f"[Error] Failed to zip files: {e}")
        return None
    
def compare_versions_player(v1, v2):
    """
    比較兩個版本號字串 (格式: x.y.z)
    回傳:
        1 if v1 > v2
        -1 if v1 < v2
        0 if v1 == v2
    """
    nums1 = [int(x) for x in v1.split('.')]
    nums2 = [int(x) for x in v2.split('.')]
    for a, b in zip(nums1, nums2):
        if a > b:
            return v1
        elif a < b:
            return v2
    return v1  # 相同則回傳 v2