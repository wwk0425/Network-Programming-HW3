import os
import shutil
import zipfile
import json
import threading

# 引用我們之前定義好的工具
from utils import recv_json, send_json, recv_file
from db_storage.database import register_user, verify_login, add_or_update_game, get_all_games

# 設定遊戲儲存根目錄
GAMES_ROOT_DIR = "games"

def handle_dev_client(conn, addr):
    """
    Developer Server 的主邏輯
    負責處理開發者的登入、上傳、管理遊戲指令
    """
    print(f"[Dev] {addr} connected.")
    current_user = None # 記錄目前連線的開發者帳號

    try:
        while True:
            # 1. 等待指令
            req = recv_json(conn)
            if not req:
                break # 連線中斷
            
            cmd = req.get('cmd')
            print(f"[Dev] {addr} Request: {cmd}")

            # --- 指令處理 ---

            # === 1. 註冊登入處理 ===
            if cmd == 'register':
                username = req.get('username')
                password = req.get('password')
                
                # 呼叫 database.py 的註冊函式
                if register_user(username, password, role="developer"):
                    send_json(conn, {"status": "ok", "msg": "Registration successful"})
                else:
                    send_json(conn, {"status": "error", "msg": "Username already exists"})
            
            elif cmd == 'login':
                username = req.get('username')
                password = req.get('password')
                
                # 呼叫 database.py 的驗證函式
                if verify_login(username, password, role="developer"):
                    current_user = username
                    send_json(conn, {"status": "ok", "msg": f"Welcome, {username}!"})
                else:
                    send_json(conn, {"status": "error", "msg": "Invalid credentials"})

            # === 2. 檢查登入狀態 (Middleware check) ===
            elif not current_user:
                send_json(conn, {"status": "error", "msg": "Please login first."})
                continue

            # === 3. 上傳遊戲 ===
            elif cmd == 'upload_game':
                # 進入上傳處理專用函式
                handle_upload_process(conn, current_user)

            # === 4. 列出我上傳的遊戲 (Optional) ===
            elif cmd == 'my_games':
                # 簡單過濾一下 database 裡的資料
                all_games = get_all_games()
                my_games = [
                    g for g in all_games.values() 
                    if g.get('uploader') == current_user
                ]
                send_json(conn, {"status": "ok", "games": my_games})

            # === 5. 未知指令 ===
            else:
                send_json(conn, {"status": "error", "msg": "Unknown command"})

    except Exception as e:
        print(f"[Dev Error] {addr}: {e}")
        # 在開發階段建議印出詳細錯誤
        import traceback
        traceback.print_exc()
    finally:
        print(f"[Dev] {addr} disconnected.")
        conn.close()


def handle_upload_process(conn, uploader_name):
    """
    處理具體的檔案接收與部署邏輯
    """
    temp_zip = "temp_upload.zip"
    temp_extract_folder = "temp_extract"

    try:
        # 1. 告訴 Client: "準備好了，請傳檔案"
        # Client 端應該在收到這個訊號後呼叫 send_file
        send_json(conn, {"status": "ready_to_receive"})

        # 2. 接收檔案 (存到暫存區)
        saved_path = recv_file(conn, save_dir=".")
        if not saved_path:
            raise Exception("File transfer failed")
        
        # 重新命名以便識別 (recv_file 可能存成 client 傳來的檔名)
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
        os.rename(saved_path, temp_zip)

        # 3. 解壓縮
        if os.path.exists(temp_extract_folder):
            shutil.rmtree(temp_extract_folder)
        
        print(f"[System] Unzipping {temp_zip}...")
        with zipfile.ZipFile(temp_zip, 'r') as zf:
            zf.extractall(temp_extract_folder)

        # 4. 讀取 Manifest 並驗證
        manifest_path = os.path.join(temp_extract_folder, "manifest.json")
        if not os.path.exists(manifest_path):
            raise Exception("Manifest not found in zip!")

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        # 取得關鍵資訊
        game_id = manifest.get('game_id')
        version = manifest.get('version')
        
        if not game_id or not version:
            raise Exception("Invalid manifest: missing game_id or version")

        # 5. 部署到最終目錄: games/{game_id}/{version}/
        # 使用 os.path.join 確保跨平台相容
        final_dir = os.path.join(GAMES_ROOT_DIR, game_id, version)

        # 如果該版本已存在，先刪除舊的 (Overwrite)
        if os.path.exists(final_dir):
            shutil.rmtree(final_dir)
        
        # 移動資料夾
        # 注意: shutil.move 的目標上層目錄必須存在
        os.makedirs(os.path.dirname(final_dir), exist_ok=True)
        shutil.move(temp_extract_folder, final_dir)

        print(f"[System] Game deployed at: {final_dir}")

        # 6. 更新資料庫 (games.json)
        # 這裡會保存評論數據，只更新版本資訊
        add_or_update_game(
            game_id=game_id,
            manifest_data=manifest,
            relative_path=final_dir, # 存入 DB 的路徑
            uploader_name=uploader_name
        )

        # 7. 回傳成功訊息
        send_json(conn, {
            "status": "ok", 
            "msg": f"Game '{game_id}' (v{version}) uploaded successfully!"
        })

    except Exception as e:
        error_msg = str(e)
        print(f"[Upload Error] {error_msg}")
        send_json(conn, {"status": "error", "msg": error_msg})
    
    finally:
        # 8. 清理垃圾 (無論成功失敗都要做)
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
        if os.path.exists(temp_extract_folder):
            shutil.rmtree(temp_extract_folder)