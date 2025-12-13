import json
import os
import struct
import zipfile
import math
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
    
def validate_game_folder(folder_path):
    print(f"[Check] 正在檢查遊戲資料夾: {folder_path} ...")

    # 1. 檢查 manifest 是否存在
    manifest_path = os.path.join(folder_path, "manifest.json")
    if not os.path.exists(manifest_path):
        print("[Error] 找不到 manifest.json！請確認它在資料夾根目錄。")
        return False

    try:
        # 2. 嘗試讀取 manifest 內容
        with open(manifest_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 3. 檢查必要欄位
        required_keys = ["game_id", "version", "server_exe", "client_exe"]
        for key in required_keys:
            if key not in config:
                print(f"[Error] manifest.json 缺少必要欄位: {key}")
                return False
        
        # 4. 檢查執行檔是否真的存在 (這步最重要！)
        # 因為 manifest 裡寫的路徑是相對路徑
        server_exe_path = os.path.join(folder_path, config["server_exe"])
        client_exe_path = os.path.join(folder_path, config["client_exe"])

        if not os.path.exists(server_exe_path):
            print(f"[Error] 找不到 Server 執行檔: {config['server_exe']}")
            return False
            
        if not os.path.exists(client_exe_path):
            print(f"[Error] 找不到 Client 執行檔: {config['client_exe']}")
            return False

    except json.JSONDecodeError:
        print("[Error] manifest.json 格式錯誤，無法解析 (Syntax Error)。")
        return False
    except Exception as e:
        print(f"[Error] 檢查過程發生未預期錯誤: {e}")
        return False

    print("[Check] 檢查通過！準備壓縮...")
    return True


def zip_game_folder(folder_path, output_zip_name="temp_game.zip", username = "developer", update = False):
    """
    將指定資料夾的內容壓縮成 zip 檔
    回傳: 壓縮後的 zip 檔案路徑，如果失敗則回傳 None
    """
    # 1. 基本檢查
    if not os.path.exists(folder_path):
        print(f"[Error] Folder '{folder_path}' does not exist.")
        return None
    if update:
        if not manifest_update_setting(folder_path, username):
            return None
    else:    
        if not manifest_initial_setting(folder_path, username):
            return None

    # 2. 檢查是否有 manifest.json (關鍵步驟！)
    if not validate_game_folder(folder_path):
        return None

    # 3. 開始壓縮
    print(f"[System] Zipping game files from '{folder_path}'...")
    
    try:
        with zipfile.ZipFile(output_zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # os.walk 會遞迴遍歷所有子資料夾
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # 計算在 zip 內的相對路徑 (重要！)
                    # 例如把 /home/user/snake/server/main.py 變成 server/main.py
                    # 這樣解壓縮時才不會有一堆多餘的層級
                    arcname = os.path.relpath(file_path, folder_path)
                    
                    zipf.write(file_path, arcname)
                    
        print(f"[System] Successfully packed into {output_zip_name}")
        return output_zip_name

    except Exception as e:
        print(f"[Error] Failed to zip files: {e}")
        return None
    
def manifest_initial_setting(folder_path, username="developer"):
    """
    回傳一個基本的 manifest.json 範本內容 (Dict)
    """
    while True:
        print("\n" + "="*10 + " 遊戲內容填寫 " + "="*10)
        template = {
            "game_id": "your_game_id",
            "version": "1.0.0",
            "min_players": 1,
            "max_players": 4,
            "server_exe": "server/your_server_executable.exe",
            "client_exe": "client/your_client_executable.exe",
            "description": "",
            "author": "遊戲開發者名稱",
            "client_args": "",
            "server_args": ""
        }

        game_id = input("請輸入遊戲 ID (英文、數字、底線): ").strip()
        if game_id:
            template['game_id'] = game_id
        else:
            print("[Warning] 未輸入遊戲 ID，將使用預設值(your_game_id)。")
        
        min_players = input("請輸入最少玩家數 (預設 1): ").strip()
        if min_players.isdigit():
            template['min_players'] = int(min_players)
        else:
            template['min_players'] = 1
            print("[Info] 偵測填入非數字或是空值，使用預設最少玩家數 1。")

        max_players = input("請輸入最多玩家數 (預設 4): ").strip()
        if max_players.isdigit():
            template['max_players'] = int(max_players)
        else:
            template['max_players'] = 4
            print("[Info] 偵測填入非數字或是空值，使用預設最多玩家數 4。")

        server_path = os.path.join(folder_path, "server")
        client_path = os.path.join(folder_path, "client")

        if os.listdir(server_path) == []:
            print("[Info] 'server' 目錄目前是空的，請先放入要上傳的遊戲伺服器。")
            return
        
        for idx , name in enumerate(os.listdir(server_path)):
            print(f"  {idx+1}. {name}")
        server_files_length = len(os.listdir(server_path))
        while True:
            server_choice = input(f"請輸入要上傳的 Server 執行檔(1~{server_files_length}): ").strip()
            if server_choice.isdigit() and 1 <= int(server_choice) <= server_files_length:
                break
            else:
                print(f"[Warning] 請輸入有效的選項 (1~{server_files_length})。")

        selected_server = os.listdir(server_path)[int(server_choice)-1]
        template['server_exe'] = f"server/{selected_server}"

        if os.listdir(client_path) == []:
            print("[Info] 'client' 目錄目前是空的，請先放入要上傳的遊戲客戶端。")
            return
        
        for idx , name in enumerate(os.listdir(client_path)):
            print(f"  {idx+1}. {name}")
        client_files_length = len(os.listdir(client_path))
        while True:
            client_choice = input(f"請輸入要上傳的 Client 執行檔(1~{client_files_length}): ").strip()
            if client_choice.isdigit() and 1 <= int(client_choice) <= client_files_length:
                break
            else:
                print(f"[Warning] 請輸入有效的選項 (1~{client_files_length})。")

        selected_client = os.listdir(client_path)[int(client_choice)-1]
        template['client_exe'] = f"client/{selected_client}"

        description = input("請輸入遊戲描述: ").strip()
        if description:
            template['description'] = description
        else:
            template['description'] = ""
            print("[Info] 偵測未輸入描述，使用預設空值。")

        template['author'] = username
        
        server_args = input("請輸入遊戲 Server 執行檔的啟動參數列表 (ex:--args args): ").strip()
        if server_args:
            template['server_args'] = server_args
        else:
            template['server_args'] = ""
            print("[Info] 未輸入參數，使用預設空值。")
        
        client_args = input("請輸入遊戲 Client 執行檔的啟動參數列表 (ex:--args args): ").strip()
        if client_args:
            template['client_args'] = client_args
        else:
            template['client_args'] = ""
            print("[Info] 未輸入參數，使用預設空值。")
        #重新輸出遊戲簡介確認是否要重新填寫
        print("\n=== 遊戲簡介確認 ===")
        for key, value in template.items():
            print(f"{key}: {value}")

        confirm = input("是否要重新填寫更新遊戲簡介? (y/n) 或輸入(q)取消: ").strip().lower()
        if confirm == 'q':
            return None
        if confirm != 'y':
            manifest_path = os.path.join(folder_path, "manifest.json")
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(template, f, indent=4, ensure_ascii=False)
            
            break
    return template

def is_valid_version_format(version):
    """
    檢查版本號格式是否正確 (x.y.z)
    """
    parts = version.split('.')
    if len(parts) != 3:
        return False
    for part in parts:
        if not part.isdigit():
            return False
    return True

def compare_versions(v1, v2):
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
    return v2  # 相同則回傳 v2

def manifest_update_setting(folder_path, username="developer"):
    """
    回傳一個基本的 manifest.json 範本內容 (Dict)
    """
    while True:
        print("\n" + "="*10 + " 更新遊戲內容填寫 " + "="*10)
        with open(os.path.join(folder_path, "manifest.json"), 'r', encoding='utf-8') as f:
            template = json.load(f)

        while True:
            version = input("請輸入更新遊戲版本 (範本格式 1.0.0): ").strip()
            #先確認格式是否正確
            if version == "" or not is_valid_version_format(version):
                print("[Warning] 未輸入版本號或格式錯誤，請使用範本格式 1.0.0。")
                continue
            #確認版本號不能用舊的
            if compare_versions(version, template.get('version', '0.0.0')) == template.get('version', '0.0.0'):
                print("[Warning] 版本號不能比現有版本舊或相同，請重新輸入。")
                continue
            else:
                break

        if version:
            template['version'] = version
        
        min_players = input("請輸入更新後最少玩家數 (預設 1): ").strip()
        if min_players.isdigit():
            template['min_players'] = int(min_players)
        else:
            template['min_players'] = 1
            print("[Info] 偵測填入非數字或是空值，使用預設最少玩家數 1。")

        max_players = input("請輸入更新後最多玩家數 (預設 4): ").strip()
        if max_players.isdigit():
            template['max_players'] = int(max_players)
        else:
            template['max_players'] = 4
            print("[Info] 偵測填入非數字或是空值，使用預設最多玩家數 4。")

        server_path = os.path.join(folder_path, "server")
        client_path = os.path.join(folder_path, "client")

        if os.listdir(server_path) == []:
            print("[Info] 'server' 目錄目前是空的，請先放入要上傳的遊戲伺服器。")
            return
        
        for idx , name in enumerate(os.listdir(server_path)):
            print(f"  {idx+1}. {name}")
        files_length = len(os.listdir(server_path))
        while True:
            server_choice = input(f"請輸入要上傳的新 Server 執行檔(1~{files_length}): ").strip()
            if server_choice.isdigit() and 1 <= int(server_choice) <= files_length:
                break
            else:
                print(f"[Warning] 請輸入有效的選項 (1~{files_length})。")
                
        selected_server = os.listdir(server_path)[int(server_choice)-1]
        template['server_exe'] = f"server/{selected_server}"

        if os.listdir(client_path) == []:
            print("[Info] 'client' 目錄目前是空的，請先放入要上傳的遊戲客戶端。")
            return
        
        for idx , name in enumerate(os.listdir(client_path)):
            print(f"  {idx+1}. {name}")
        
        client_files_length = len(os.listdir(client_path))
        while True:
            client_choice = input(f"請輸入要上傳的新 Client 執行檔(1~{client_files_length}): ").strip()
            if client_choice.isdigit() and 1 <= int(client_choice) <= client_files_length:
                break
            else:
                print(f"[Warning] 請輸入有效的選項 (1~{client_files_length})。")
                
        selected_client = os.listdir(client_path)[int(client_choice)-1]
        template['client_exe'] = f"client/{selected_client}"

        description = input("請輸入更新內容描述: ").strip()
        if description:
            template['update_patch'] = description
        else:
            template['update_patch'] = ""
            print("[Info] 偵測未輸入描述，使用預設空值。")

        template['author'] = username

        server_args = input("請輸入遊戲 Server 執行檔的啟動參數列表 (ex:--args args): ").strip()
        if server_args:
            template['server_args'] = server_args
        else:
            template['server_args'] = ""
            print("[Info] 未輸入參數，使用預設空值。")
        
        client_args = input("請輸入遊戲 Client 執行檔的啟動參數列表 (ex:--args args): ").strip()
        if client_args:
            template['client_args'] = client_args
        else:
            template['client_args'] = ""
            print("[Info] 未輸入參數，使用預設空值。")
            
        #重新輸出遊戲簡介確認是否要重新填寫
        print("\n=== 遊戲簡介確認 ===")
        for key, value in template.items():
            print(f"{key}: {value}")

        confirm = input("是否要重新填寫更新遊戲簡介? (y/n) 或輸入(q)取消: ").strip().lower()
        if confirm == 'q':
            return None
        if confirm != 'y':
            manifest_path = os.path.join(folder_path, "manifest.json")
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(template, f, indent=4, ensure_ascii=False)
            
            break
    return template

def paged_dev_menu(options, page_size=3):
    page = 0
    total_pages = math.ceil(len(options) / page_size)
    #total_pages = (len(options) + page_size - 1) // page_size
    while True:
        start = page * page_size
        end = start + page_size
        print("\n" + "="*10 + " Developer Menu " + "="*10)
        for idx, opt in enumerate(options[start:end], start=1):
            print(f"{idx}. {opt}")
        if total_pages > 1:
            if page > 0:
                print("p. 上一頁 (Prev Page)")
            if page < total_pages - 1:
                print("n. 下一頁 (Next Page)")
        choice = input("請選擇功能: ").strip().lower()
        if choice == 'n' and page < total_pages - 1:
            page += 1
        elif choice == 'p' and page > 0:
            page -= 1
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < min(page_size, len(options) - start):
                print(start + idx + 1)
                return start + idx + 1  # 回傳選項編號（1-based）
            else:
                print("無效的輸入，請重新選擇yr。")
        else:
            print("無效的輸入，請重新選擇。")