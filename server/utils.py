import json
import os
import struct
import zipfile
import shutil # 用來移動資料夾
GAMES_DIR = './games'

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

# --- 輔助函式: 掃描 games 資料夾載入遊戲列表 ---
def load_games():
    """
    從硬碟讀取所有遊戲的 manifest，並載入到記憶體 (available_games) 中。
    結構假設: games/{game_id}/{version}/manifest.json
    """
    global available_games
    available_games = {} # 清空舊資料
    print(f"[System] Scanning games in '{GAMES_DIR}'...")

    if not os.path.exists(GAMES_DIR):
        os.makedirs(GAMES_DIR)
        print("[System] Games directory created.")
        return

    # 1. 遍歷第一層：取得 game_id (例如: snake, tetris)
    for game_id in os.listdir(GAMES_DIR):
        game_root_path = os.path.join(GAMES_DIR, game_id)

        # 確保它是資料夾
        if not os.path.isdir(game_root_path):
            continue

        # 2. 遍歷第二層：取得所有版本號 (例如: 1.0, 1.1)
        versions = []
        for v in os.listdir(game_root_path):
            if os.path.isdir(os.path.join(game_root_path, v)):
                versions.append(v)
        
        if not versions:
            print(f"  [Warn] Empty game folder: {game_id}")
            continue

        # 3. 找出「最新版本」
        # 這裡用簡單的字串排序，所以 '1.2' 會大於 '1.0'。
        # (注意: 字串排序中 '1.10' 會排在 '1.2' 前面，作業若不要求 Semantic Versioning 可忽略)
        latest_version = sorted(versions)[-1]
        
        # 4. 讀取該版本的 manifest.json
        manifest_path = os.path.join(game_root_path, latest_version, "manifest.json")
        
        if not os.path.exists(manifest_path):
            print(f"  [Error] Manifest not found for {game_id} v{latest_version}")
            continue

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                game_data = json.load(f)
            
            # 5. 補強資料：把 Server 才知道的路徑資訊加進去，方便之後處理
            # (這些資訊不用寫在 manifest 裡，是 Server 運行時動態決定的)
            game_data['latest_version'] = latest_version
            
            # 為了讓之後啟動遊戲方便，我們把絕對路徑算好存進去
            # 注意：這裡存的是 Server 本機的路徑，之後啟動 Subprocess 要用
            base_dir = os.path.abspath(os.path.join(game_root_path, latest_version))
            game_data['server_exe_path'] = os.path.join(base_dir, game_data['server_exe'])
            game_data['client_exe_path'] = os.path.join(base_dir, game_data['client_exe'])
            
            # 存入全域字典
            available_games[game_id] = game_data
            print(f"  [Loaded] {game_data.get('name', game_id)} (v{latest_version})")

        except json.JSONDecodeError:
            print(f"  [Error] Invalid JSON format in {game_id}")
        except Exception as e:
            print(f"  [Error] Failed to load {game_id}: {e}")

    print(f"[System] Load complete. Total games: {len(available_games)}")

def handle_upload_game(conn):
    """
    處理上傳指令的 Server 端邏輯
    """
    # 1. 接收 Zip 檔案到暫存區
    temp_zip_path = "temp_upload.zip"
    temp_extract_folder = "temp_extract_folder"
    
    # 這裡呼叫我們之前定義的 recv_file (假設它會把檔案存到 temp_zip_path)
    # 實際上 recv_file 應該要能指定存檔路徑
    saved_path = recv_file(conn, save_dir=".") 
    
    if not saved_path:
        return # 接收失敗

    try:
        # 2. 解壓縮到暫存資料夾
        if os.path.exists(temp_extract_folder):
            shutil.rmtree(temp_extract_folder) # 清空舊的暫存
        
        with zipfile.ZipFile(saved_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_folder)

        # 3. 讀取 manifest 以決定最終路徑
        manifest_path = os.path.join(temp_extract_folder, "manifest.json")
        if not os.path.exists(manifest_path):
            send_json(conn, {"status": "error", "msg": "No manifest in zip"})
            return

        with open(manifest_path, 'r') as f:
            data = json.load(f)
            game_id = data['game_id']
            version = data['version']

        # 4. 建立最終儲存目錄: games/{game_id}/{version}/
        final_dir = os.path.join("games", game_id, version)
        
        if os.path.exists(final_dir):
            # 如果版本已存在，看你要覆蓋還是報錯
            shutil.rmtree(final_dir) 
        
        # 5. 將暫存資料夾搬移到最終位置
        shutil.move(temp_extract_folder, final_dir)
        
        print(f"[System] Game deployed to {final_dir}")
        send_json(conn, {"status": "ok", "msg": f"Game {game_id} v{version} uploaded successfully!"})

        # 6. 更新記憶體中的遊戲列表 (重要！不然玩家看不到新遊戲)
        load_games() 

    except Exception as e:
        print(f"[Error] Upload processing failed: {e}")
        send_json(conn, {"status": "error", "msg": str(e)})
    finally:
        # 清理暫存 zip
        if os.path.exists(saved_path):
            os.remove(saved_path)

def get_game_list():
    """
    回傳目前可用的遊戲列表給 Lobby Service 使用
    格式: List of Dicts
    """
    game_list = []
    for game_id, data in available_games.items():
        game_info = {
            "game_id": game_id,
            "name": data.get("name", "Unknown"),
            "description": data.get("description", ""),
            "latest_version": data.get("latest_version", "N/A")
        }
        game_list.append(game_info)
    return game_list