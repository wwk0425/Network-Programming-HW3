import shutil
import socket
import os
import sys
import time
import zipfile
import json
import threading
import subprocess
import argparse
# 假設 network.py 放在同層級的 utils 資料夾
# 如果放在同層，直接 from network import ...
from utils import send_json, recv_json, recv_file, paged_cli_menu
from config import LOBBY_PORT


# --- 設定 ---
SERVER_IP = '140.113.17.11'
# DEV_PORT = 9001  # 開發者專用 Port
GAMES_ROOT_DIR = "games"  # 下載後遊戲存放根目錄
in_game = threading.Event()
game_process = None
# --- 功能函式 ---
def room_listener(sock):
    """
    房間專用的監聽執行緒
    """
    global stop_room_listener
    print("[System] 已進入房間監聽模式...")
    #先收一次player_joined得到歡迎訊息
    msg = recv_json(sock)
    if not msg:
        print("[System] Server 斷線")
        os._exit(0)
    cmd = msg.get('cmd')
    status = msg.get('status')
    if cmd == 'player_joined':
        print(f"\n>>> [通知] {msg['username']} 加入了房間！")
    #先確認自己是不是房主

    is_host = False
    state = "waiting"
    send_json(sock, {"cmd": "get_host"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        is_host = res['host']
    
    if not stop_room_listener and state == "waiting" and is_host:
        print("\n====房間功能選單====")
        print("1. 開始遊戲 (Start Game)")
        print("2. 離開房間 (Leave Room)")
        print("請選擇功能: ", end='', flush=True)
    elif not stop_room_listener and state == "waiting" and not is_host:
        print("\n====房間功能選單====")
        print("1. 準備 (Ready) [若按下準備就無法取消，請等待房主開始遊戲]")
        print("2. 離開房間 (Leave Room)")
        print("請選擇功能: ", end='', flush=True)

    while not stop_room_listener:
        try:
            # 設定 timeout，讓執行緒有機會檢查 stop_room_listener 變數
            sock.settimeout(0.5) 
            try:
                msg = recv_json(sock)
            except socket.timeout:
                continue # 沒收到東西，繼續迴圈檢查 stop flag
            
            if not msg:
                print("[System] Server 斷線")
                os._exit(0)

            cmd = msg.get('cmd')
            status = msg.get('status')

            # === 關鍵修改：在這裡處理 "離開房間" 的回應 ===
            # 因為主執行緒只負責送，所以 Server 回傳的 "status": "ok", "msg": "left room" 會被這裡收到
            if (status == 'ok' and 'left' in str(msg.get('msg', '')).lower()):
                print(f"\n[System] {msg.get('msg', '已離開房間')}")
                stop_room_listener = True # 通知迴圈結束
                break

            # 處理房間內的廣播
            if cmd == 'player_joined':
                print(f"\n>>> [通知] {msg['username']} 加入了房間！")
                
            elif cmd == 'player_left':
                print(f"\n>>> [通知] {msg['username']} 離開了房間。")
                
            elif cmd == 'game_start':
                in_game.set()
                print(f"\n>>> [通知] 遊戲開始！請連線至 {msg['ip']} {msg['port']}")
                state = "playing"
                # 這裡呼叫 subprocess 啟動遊戲...
                client_args = msg.get('client_args', "")
                # 伺服器傳來的 game_path 只到 games/game_id/version，要補上本地 username 目錄
                server_game_path = msg.get('game_path', '.')
                # 取出 game_id, version
                parts = server_game_path.replace("/", os.sep).replace("\\", os.sep).split(os.sep)
                game_id = parts[1]
                version = parts[2]
                game_path = os.path.join(GAMES_ROOT_DIR, game_id, version)
                client_exe = msg.get('client_exe', '')
                current_room_id = msg.get('room_id', '')
                full_exe_path = os.path.abspath(os.path.join(game_path, client_exe))
                try:
                    cmd_list = ["python", full_exe_path,"--ip", str(msg['ip']), "--port", str(msg['port'])] + client_args.split() if full_exe_path.endswith('.py') else [full_exe_path, "--ip", msg['ip'], "--port", str(msg['port'])] + client_args.split()
                    game_process = subprocess.Popen(cmd_list, cwd=os.path.abspath(game_path))
                except Exception as e:
                    game_process = None
                    print (f"[Error] 啟動遊戲失敗: {e}")
                    send_json(sock, {"cmd": "client_start_failed", "room_id": current_room_id, "reason": str(e)})

            elif cmd == 'game_start_failed':
                if game_process:
                    game_process.terminate()
                    game_process = None
                in_game.set()
                time.sleep(1)
                in_game.clear()
                print(f"\n>>> [錯誤] 遊戲無法開始: {msg.get('msg', 'Unknown error')}")
                state = "waiting"

            elif cmd == 'create_room':
                print(f"\n>>> [通知] 房間建立成功！房間 ID: {msg['room_id']}")
            elif cmd == 'room_closed':
                # 處理例如 "房主離開，房間解散" 的訊息
                print(f"\n>>> [通知] {msg['msg']}")
                stop_room_listener = True
                print("\n" + "="*10 + " Player Menu " + "="*10)
                print("1. 進入商城 (Enter Marketplace)")
                print("2. 下載遊戲 (Download Games)")
                print("3. 建立房間 (Create Room)")
                print("4. 加入房間 (Join Room)")
                print("5. 登出/離開 (Exit)")
                print("請選擇功能 (1-5): ", end='', flush=True)
                break
            elif cmd == 'host_changed':
                print(f"\n>>> [通知] {msg['msg']}")
                send_json(sock, {"cmd": "get_host"})
                res = recv_json(sock)
                if res and res['status'] == 'ok':
                    is_host = res['host']
            elif cmd == 'game_ended':
                if game_process:
                    game_process.terminate()
                    game_process = None
                in_game.clear()
                print(f"\n>>> [通知] 遊戲結束！")
                state = "waiting"
            elif cmd == 'player_ready':
                print(f"\n>>> [通知] 你已經準備，請等待其他人準備和房主開始遊戲")
                state = "ready"
            elif cmd == 'start_game_error':
                print(f"\n>>> [錯誤] 無法開始遊戲: {msg.get('msg', 'Unknown error')}")
                in_game.set()
                time.sleep(1)
                in_game.clear()
            else:
                print(f"\n>>> [通知] 收到未知指令: {msg}")

            

            if not stop_room_listener and state == "waiting" and is_host:
                print("\n====房間功能選單====")
                print("1. 開始遊戲 (Start Game)")
                print("2. 離開房間 (Leave Room)")
                print("請選擇功能: ", end='', flush=True)
            elif not stop_room_listener and state == "waiting" and not is_host:
                print("\n====房間功能選單====")
                print("1. 準備 (Ready) [若按下準備就無法取消，請等待房主開始遊戲]")
                print("2. 離開房間 (Leave Room)")
                print("請選擇功能: ", end='', flush=True)
        except Exception as e:
            if not stop_room_listener:
                print(f"[Error] Listener error: {e}")
            break

def register(sock):
    """
    處理註冊流程
    """
    while True:
        print("\n=== 開發者註冊 ===")
        username = input("帳號: ").strip()
        if not username: continue
        password = input("密碼: ").strip()

        req = {
            "cmd": "register",
            "username": username,
            "password": password,
        }
        send_json(sock, req)
        
        res = recv_json(sock)
        if res and res['status'] == 'ok':
            print(f"註冊成功！{res['msg']}")
            return username
        else:
            print(f"註冊失敗: {res.get('msg', 'Unknown error')}")
            retry = input("是否重試? (y/n): ")
            if retry.lower() != 'y':
                return None

def login(sock):
    """
    處理登入流程
    """
    while True:
        print("\n=== 玩家登入 ===")
        username = input("帳號: ").strip()
        if not username: continue
        password = input("密碼: ").strip()

        req = {
            "cmd": "login",
            "username": username,
            "password": password
        }
        send_json(sock, req)
        
        res = recv_json(sock)
        if res and res['status'] == 'ok':
            print(f"登入成功！{res['msg']}")
            return username
        else:
            print(f"登入失敗: {res.get('msg', 'Unknown error')}")
            retry = input("是否重試? (y/n): ")
            if retry.lower() != 'y':
                return None

            
def list_all_games(sock):
    """
    列出商城中的遊戲 (Optional but useful)
    """
    while True:
        while True:
            try:
                send_json(sock, {"cmd": "list_games"})
                res = recv_json(sock)
                if res and res['status'] == 'ok':
                    games = res['games']
                    if not games:
                        print("目前沒有可遊玩的遊戲。")
                        return
                    print(f"\n=== 商城遊戲列表 ({len(games)}) ===")
                    print(f"{'名稱':<20} {'作者':<20} {'版本':<10} {'評分'}")
                    print("-" * 60)
                    for g in games:
                        print(f"{g['game_id']:<20} {g['uploader']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
                    break
                else:
                    print("列表載入失敗。")
                    choice = input("是否重試? (y/n): ")
                    if choice.lower() != 'y':
                        return
                    else:
                        continue
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                raise
            except Exception as e:
                print(f"列表載入失敗: {e}")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return

        while True:
            choice = input("輸入編號來更進一步了解遊戲細節，或輸入 q 返回: ")
            if choice.lower() == 'q' or (choice.isdigit() and 0 < int(choice) <= len(games)):
                break
            else:
                print("無效的輸入，請重新輸入。")

        if choice.lower() == 'q':
            return
        selected_game = games[int(choice)-1]
        print(f"\n===({selected_game['game_id']}的詳細資訊) ===")
        print("遊戲名稱:", selected_game['game_id'])
        print("作者:", selected_game['uploader'])
        print("版本:", selected_game['version'])
        if selected_game.get('description') == "":
            print("遊戲簡介: 尚未提供簡介")
        else:
            print("遊戲簡介:", selected_game.get('description', '無'))
        if selected_game.get('update_patch') == "":
            print("更新說明: 尚未提供更新說明")
        else:
            print("更新說明:", selected_game.get('update_patch', '無'))
        print("支援最少人數:", selected_game.get('min_players', '未知'))
        print("支援最多人數:", selected_game.get('max_players', '未知'))
        if selected_game.get('type') == "":
            print("遊戲類型: 尚未提供遊戲類型")
        else:
            print("遊戲類型:", selected_game.get('type', '未知'))
        if selected_game.get('average_rating') == 0.0:
            print("評分: 尚未提供評分")
        else:
            print("評分:", selected_game.get('average_rating', 0))
        if selected_game.get('reviews') == []:
            print("玩家評論: 尚未有玩家評論")
        else:
            #選最新的5則評論顯示
            print("玩家評論:")
            reviews = selected_game.get('reviews', [])
            reviews_sorted = sorted(reviews, key=lambda r: r['time'], reverse=True)
            latest_five_reviews = reviews_sorted[:5]
            for review in latest_five_reviews:
                print(f"  - {review['user']} 評分: {review['score']} 評論: {review['comment']}")

        choice = input("是否返回商城遊戲列表?(若否，則返回商城大廳) (y/n): ")
        if choice.lower() != 'y':
            break

def market_menu(sock):
    """
    玩家商城主選單
    """
    while True:
        print("\n=== 玩家商城 ===")
        print("1. 瀏覽遊戲")
        print("2. 返回主選單")
        choice = input("請選擇功能 (1-2): ").strip()

        if choice == '1':
            list_all_games(sock)
        elif choice == '2':
            print("即將返回主選單。")
            break
        else:
            print("無效的輸入，請重新選擇。")

def check_game_update(sock, game_id, mode='download'):
    """
    檢查遊戲更新
    """
    #先判斷是否有此遊戲了
    find_game_dir = os.path.join(GAMES_ROOT_DIR, game_id)
    if os.path.exists(find_game_dir):
        version = os.listdir(find_game_dir)
        send_json(sock, {
            "cmd": "compare_version",
            "game_id": game_id,
            "current_version": version[0]  # 假設只有一個版本
        })

        res = recv_json(sock)
        if res and res['status'] == 'ok':
            if res.get('up_to_date'):
                print(f"你已擁有此遊戲的最新版本！")
                if mode == 'download':
                    return False
                else:
                    return True, "no_update"
            else:
                latest_version = res.get('latest_version')
                print(f"有新版本可下載！最新版本為 {latest_version}")
                choice = input("是否要下載最新版本？(y/n): ")
                if choice.lower() != 'y':
                    print("取消下載。")
                    if mode == 'download':
                        return False
                    else:
                        return False, "no_update"
                else:
                    if mode == 'download':
                        return True
                    else:
                        return True, "download"
        else:
            print("無法比較版本，請稍後再試。")
            if mode == 'download':
                return False
            else:
                return False, "no_update"
    else:
        print(f"你尚未擁有此遊戲，將下載最新版本。")
        choice = input("是否要下載最新版本？(y/n): ")
        if choice.lower() != 'y':
            print("取消下載。")
            if mode == 'download':
                return False
            else:
                return False, "no_update"
        else:
            if mode == 'download':
                return True
            else:
                return True, "download"
        
def download_game(sock):
    """
    下載遊戲
    """
    temp_zip = "temp_upload.zip"
    temp_extract_folder = "temp_extract"


    send_json(sock, {"cmd": "list_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        games = res['games']
        print(f"\n=== 商城遊戲列表 ({len(games)}) ===")
        print(f"{'名稱':<20} {'作者':<20} {'版本':<10} {'評分'}")
        print("-" * 60)
        for g in games:
            if g['status'] == 'unavailable':
                continue
            print(f"{g['game_id']:<20} {g['uploader']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
    else:
        print("列表載入失敗。")
        return

    while True:
        choice = input(f"請輸入要下載的遊戲編號(1-{len(games)}) (或輸入 q 返回): ").strip()
        if choice.lower() == 'q' or (choice.isdigit() and 1 <= int(choice) <= len(games)):
               break
        else:
            print("無效的輸入，請重新輸入。")

    if choice.lower() == 'q':
        return
    game_id = games[int(choice)-1]['game_id']

    #檢查是否有更新
    if not check_game_update(sock, game_id, mode='download'):
        return

    #下載成最新檔案
    req = {
        "cmd": "download_game",
        "game_id": game_id
    }
    while True:
        try:
            send_json(sock, req)

            res = recv_json(sock)
            if res and res['status'] == 'ok':
                file_size = res['file_size']
                print(f"開始下載遊戲 {game_id}，檔案大小: {file_size} bytes")

                # 1. 告訴 server: "準備好了，請傳檔案"
                # server 端應該在收到這個訊號後呼叫 send_file
                send_json(sock, {"status": "ready_to_receive"})

                # 2. 接收檔案 (存到暫存區)
                saved_path = recv_file(sock, save_dir=".")
                if not saved_path:
                    raise Exception("File transfer failed")
                    
                # 重新命名以便識別 (recv_file 可能存成 client 傳來的檔名)
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                os.rename(saved_path, temp_zip)

                # 3. 解壓縮
                if os.path.exists(temp_extract_folder):
                    shutil.rmtree(temp_extract_folder)
                    
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
                if not os.path.exists(GAMES_ROOT_DIR):
                    os.makedirs(GAMES_ROOT_DIR)

                #檢查是否經有該遊戲資料夾 若有刪掉舊版本 更新成新的版本
                selected_game_dir = os.path.join(GAMES_ROOT_DIR, game_id)
                if os.path.exists(selected_game_dir):
                    shutil.rmtree(selected_game_dir)

                final_dir = os.path.join(GAMES_ROOT_DIR, game_id, version)

                    
                # 移動資料夾
                # 注意: shutil.move 的目標上層目錄必須存在
                os.makedirs(os.path.dirname(final_dir), exist_ok=True)
                shutil.move(temp_extract_folder, final_dir)

                print(f"已成功下載進我的遊戲庫了！")


                # 6. 回傳成功訊息
                send_json(sock, {
                    "status": "ok", 
                    "msg": f"Game '{game_id}' (v{version}) uploaded successfully!"
                })
                break
            else:
                print(f"下載失敗: {res.get('msg', 'Unknown error')}")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            raise
        except Exception as e:
            error_msg = str(e)
            print(f"下載失敗: {error_msg}")
            send_json(sock, {"status": "error", "msg": error_msg})
            choice = input("是否重試? (y/n): ")
            if choice.lower() != 'y':
                return
            else:
                continue
                
        finally:
            # 8. 清理垃圾 (無論成功失敗都要做)
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            if os.path.exists(temp_extract_folder):
                shutil.rmtree(temp_extract_folder)
            
        

def create_room_flow(sock):
    """
    建立房間流程 (Placeholder)
    """
    global stop_room_listener
    stop_room_listener = False

    send_json(sock, {"cmd": "list_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        games = res['games']
        print(f"\n=== 商城遊戲列表 ({len(games)}) ===")
        print(f"{'名稱':<20} {'作者':<20} {'版本':<10} {'評分'}")
        print("-" * 60)
        for g in games:
            if g['status'] == 'unavailable':
                continue
            print(f"{g['game_id']:<20} {g['uploader']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
    else:
        print("列表載入失敗。")

    while True:
        choice = input(f"請輸入要遊玩的遊戲編號(1-{len(games)}) (或輸入 q 返回): ").strip()
        if choice.lower() == 'q' or (choice.isdigit() and 1 <= int(choice) <= len(games)):
            break
        else:
            print("無效的輸入，請重新輸入。")
    
    if choice.lower() == 'q':
        return
    
    game_id = games[int(choice)-1]['game_id']
    #檢查是否有遊戲

    flag, status = check_game_update(sock, game_id, mode='play')

    temp_zip = "temp_upload.zip"
    temp_extract_folder = "temp_extract"

    if not flag:
        return
    if flag and status == 'download':
        #下載成最新檔案
        req = {
            "cmd": "download_game",
            "game_id": game_id
        }
        send_json(sock, req)

        res = recv_json(sock)
        if res and res['status'] == 'ok':
            file_size = res['file_size']
            print(f"開始下載遊戲 {game_id}，檔案大小: {file_size} bytes")

            try:
                # 1. 告訴 server: "準備好了，請傳檔案"
                # server 端應該在收到這個訊號後呼叫 send_file
                send_json(sock, {"status": "ready_to_receive"})

                # 2. 接收檔案 (存到暫存區)
                saved_path = recv_file(sock, save_dir=".")
                if not saved_path:
                    raise Exception("File transfer failed")
                    
                # 重新命名以便識別 (recv_file 可能存成 client 傳來的檔名)
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                os.rename(saved_path, temp_zip)

                # 3. 解壓縮
                if os.path.exists(temp_extract_folder):
                    shutil.rmtree(temp_extract_folder)
                    
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
                if not os.path.exists(GAMES_ROOT_DIR):
                    os.makedirs(GAMES_ROOT_DIR)

                #檢查是否經有該遊戲資料夾 若有刪掉舊版本 更新成新的版本
                selected_game_dir = os.path.join(GAMES_ROOT_DIR, game_id)
                if os.path.exists(selected_game_dir):
                    shutil.rmtree(selected_game_dir)

                final_dir = os.path.join(GAMES_ROOT_DIR, game_id, version)

                    
                # 移動資料夾
                # 注意: shutil.move 的目標上層目錄必須存在
                os.makedirs(os.path.dirname(final_dir), exist_ok=True)
                shutil.move(temp_extract_folder, final_dir)

                print(f"已成功下載進我的遊戲庫了！")


                # 6. 回傳成功訊息
                send_json(sock, {
                    "status": "ok", 
                    "msg": f"Game '{game_id}' (v{version}) uploaded successfully!"
                })

            except Exception as e:
                error_msg = str(e)
                print(f"下載失敗: {error_msg}")
                send_json(sock, {"status": "error", "msg": error_msg})
                return
            finally:
                # 8. 清理垃圾 (無論成功失敗都要做)
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                if os.path.exists(temp_extract_folder):
                    shutil.rmtree(temp_extract_folder) 
        else:
            print(f"下載失敗: {res.get('msg', 'Unknown error')}")
            return
    
    #確認已經有了最新版本
    print(f"建立房間中...")
    req = {
        "cmd": "create_room",
        "game_id": game_id
    }
    send_json(sock, req)

    res = recv_json(sock)
    if res and res['status'] == 'ok':
        room_id = res['room_id']
        print(f"房間建立成功！房間 ID: {room_id}")  
    else:
        print(f"房間建立失敗: {res.get('msg', 'Unknown error')}")
        return
    
    print("等待其他玩家加入房間...")
    # === 進入房間模式 ===
    #建立監聽執行續
    t = threading.Thread(target=room_listener, args=(sock,))
    t.start()

    try:
        while True:
            # 檢查：如果監聽器因為 "被踢出" 或 "Server斷線" 而自己停了，主迴圈也要停
            if stop_room_listener: 
                break
            
            if in_game.is_set():
                # 如果正在遊戲中，就不顯示選單
                time.sleep(1)
                continue
            # print("\n====房間功能選單====")
            # print("1. 開始遊戲 (Start Game)")
            # print("2. 離開房間 (Leave Room)")
            
            # # 使用 sys.stdin.readline 避免 input() 與 print 打架
            # print(">>> 請選擇: ", end='', flush=True)
            choice = sys.stdin.readline().strip()

            if choice == '1':
                # 主執行緒只負責送！不負責聽結果！
                # 結果會由 room_listener 印出來
                send_json(sock, {"cmd": "start_game", "room_id": room_id})
                print(">>> 請求已發送...")
                # 進入等待遊戲結束的狀態
                while not in_game.is_set():
                    time.sleep(1)

            elif choice == '2':
                print(">>> 正在離開房間...")
                send_json(sock, {"cmd": "leave_room", "room_id": room_id})
                
                # === 關鍵修改 ===
                # 這裡絕對不要 recv_json() !!!
                # 我們等待 room_listener 收到 server 回應並將 stop_room_listener 設為 True
                t.join() # 等待監聽執行緒結束
                break
            else:
                print("無效的輸入，請重新選擇。")
                print("請選擇功能: ", end='', flush=True)

    except KeyboardInterrupt:
        send_json(sock, {"cmd": "leave_room", "room_id": room_id})
        stop_room_listener = True
        t.join()
        sys.exit(0)
    
    # 恢復 socket 為阻塞模式 (給大廳用)
    sock.settimeout(None) 
    print("已返回大廳選單。")

def join_room_flow(sock):
    """
    加入房間流程 (Placeholder)
    """
    global stop_room_listener
    stop_room_listener = False

    send_json(sock, {"cmd": "list_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        games = res['games']
        print(f"\n=== 商城遊戲列表 ({len(games)}) ===")
        print(f"{'名稱':<20} {'作者':<20} {'版本':<10} {'評分'}")
        print("-" * 60)
        for g in games:
            if g['status'] == 'unavailable':
                continue
            print(f"{g['game_id']:<20} {g['uploader']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
    else:
        print("列表載入失敗。")

    while True:
        choice = input(f"請輸入要遊玩的遊戲編號(1-{len(games)}) (或輸入 q 返回): ").strip()
        if choice.lower() == 'q' or (choice.isdigit() and 1 <= int(choice) <= len(games)):
            break
        else:
            print("無效的輸入，請重新輸入。")
    
    if choice.lower() == 'q':
        return
    
    game_id = games[int(choice)-1]['game_id']
    #檢查是否有遊戲

    flag, status = check_game_update(sock, game_id, mode='play')

    temp_zip = "temp_upload.zip"
    temp_extract_folder = "temp_extract"

    if not flag:
        return
    if flag and status == 'download':
        #下載成最新檔案
        req = {
            "cmd": "download_game",
            "game_id": game_id
        }
        send_json(sock, req)

        res = recv_json(sock)
        if res and res['status'] == 'ok':
            file_size = res['file_size']
            print(f"開始下載遊戲 {game_id}，檔案大小: {file_size} bytes")

            try:
                # 1. 告訴 server: "準備好了，請傳檔案"
                # server 端應該在收到這個訊號後呼叫 send_file
                send_json(sock, {"status": "ready_to_receive"})

                # 2. 接收檔案 (存到暫存區)
                saved_path = recv_file(sock, save_dir=".")
                if not saved_path:
                    raise Exception("File transfer failed")
                    
                # 重新命名以便識別 (recv_file 可能存成 client 傳來的檔名)
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                os.rename(saved_path, temp_zip)

                # 3. 解壓縮
                if os.path.exists(temp_extract_folder):
                    shutil.rmtree(temp_extract_folder)
                    
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
                if not os.path.exists(GAMES_ROOT_DIR):
                    os.makedirs(GAMES_ROOT_DIR)

                #檢查是否經有該遊戲資料夾 若有刪掉舊版本 更新成新的版本
                selected_game_dir = os.path.join(GAMES_ROOT_DIR, game_id)
                if os.path.exists(selected_game_dir):
                    shutil.rmtree(selected_game_dir)

                final_dir = os.path.join(GAMES_ROOT_DIR, game_id, version)

                    
                # 移動資料夾
                # 注意: shutil.move 的目標上層目錄必須存在
                os.makedirs(os.path.dirname(final_dir), exist_ok=True)
                shutil.move(temp_extract_folder, final_dir)

                print(f"已成功下載進我的遊戲庫了！")


                # 6. 回傳成功訊息
                send_json(sock, {
                    "status": "ok", 
                    "msg": f"Game '{game_id}' (v{version}) uploaded successfully!"
                })

            except Exception as e:
                error_msg = str(e)
                print(f"下載失敗: {error_msg}")
                send_json(sock, {"status": "error", "msg": error_msg})
                return
            finally:
                # 8. 清理垃圾 (無論成功失敗都要做)
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                if os.path.exists(temp_extract_folder):
                    shutil.rmtree(temp_extract_folder) 
        else:
            print(f"下載失敗: {res.get('msg', 'Unknown error')}")
            return
    
    #確認已經有了最新版本 顯示可以加入的房間列表
    send_json(sock, {"cmd": "list_rooms"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        rooms = res['rooms']
        selected_game_rooms = [r for r in rooms if r['game_id'] == game_id]
        print(f"\n=== 可加入的房間列表 ({len(selected_game_rooms)}) ===")
        print(f"{'房間ID':<10} {'遊戲名稱':<20} {'目前人數':<10} {'最大人數'}")
        print("-" * 60)
        for r in selected_game_rooms:
            print(f"{r['id']:<10} {r['game_id']:<20} {r['cur_players']:<10} {r['max_players']}")
    while True:
        choice = input(f"請輸入要加入的房間編號(1~{len(selected_game_rooms)}) (或輸入 q 返回): ").strip()
        if choice.lower() == 'q' or (choice.isdigit() and 1 <= int(choice) <= len(selected_game_rooms)):
            break
        else:
            print("無效的輸入，請重新輸入。")

    if choice.lower() == 'q':
        return
    
    room_id = selected_game_rooms[int(choice)-1]['id']
    #加入房間
    print(f"加入房間中...")
    req = {
        "cmd": "join_room",
        "room_id": room_id
    }
    send_json(sock, req)

    res = recv_json(sock)
    if res and res['status'] == 'ok':
        print(f"房間加入成功！房間 ID: {room_id}")
    else:
        print(f"房間加入失敗: {res.get('msg', 'Unknown error')}")
        return
    print("等待其他玩家加入房間...")
    # === 進入房間模式 ===
    #建立監聽執行續
    t = threading.Thread(target=room_listener, args=(sock,))
    t.start()

    try:
        while True:
            # 檢查：如果監聽器因為 "被踢出" 或 "Server斷線" 而自己停了，主迴圈也要停
            if stop_room_listener: 
                break
            if in_game.is_set():
                # 如果正在遊戲中，就不顯示選單
                time.sleep(1)
                continue
            # print("\n====房間功能選單====")
            # print("1. 開始遊戲 (Start Game)")
            # print("2. 離開房間 (Leave Room)")
            
            # # 使用 sys.stdin.readline 避免 input() 與 print 打架
            # print(">>> 請選擇: ", end='', flush=True)
            choice = sys.stdin.readline().strip()

            if choice == '1':
                # 主執行緒只負責送！不負責聽結果！
                # 結果會由 room_listener 印出來
                send_json(sock, {"cmd": "start_game", "room_id": room_id})
                print(">>> 請求已發送...")
                while not in_game.is_set():
                    time.sleep(0.5)

            elif choice == '2':
                print(">>> 正在離開房間...")
                send_json(sock, {"cmd": "leave_room", "room_id": room_id})
                
                # === 關鍵修改 ===
                # 這裡絕對不要 recv_json() !!!
                # 我們等待 room_listener 收到 server 回應並將 stop_room_listener 設為 True
                t.join() # 等待監聽執行緒結束
                break
            else:
                print("無效輸入，請重新輸入。")

    except KeyboardInterrupt:
        send_json(sock, {"cmd": "leave_room", "room_id": room_id})
        stop_room_listener = True
        t.join()
        sys.exit(0)
    
    # 恢復 socket 為阻塞模式 (給大廳用)
    sock.settimeout(None) 
    print("已返回大廳選單。")

def review_game(sock):
    """
    評論遊戲 (Placeholder)
    """
    #列出玩過的遊戲
    send_json(sock, {"cmd": "played_game_list"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        games = res['played_games']
        print(f"\n=== 你玩過的遊戲列表 ({len(games)}) ===")
        print(f"{'名稱':<20} {'作者':<20} {'版本':<10} {'評分'}")
        print("-" * 60)
        for g in games:
            print(f"{g['game_id']:<20} {g['uploader']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
    else:
        print("列表載入失敗。")
        return
    
    while True:
        choice = input(f"請輸入要評論的遊戲編號(1~{len(games)}) (或輸入 q 返回): ").strip()
        if choice.lower() == 'q' or (choice.isdigit() and 1 <= int(choice) <= len(games)):
            break
        else:
            print("無效的輸入，請重新輸入。")

    if choice.lower() == 'q':
        return
    game_id = games[int(choice)-1]['game_id']

    while True:
        rating = input("請給予遊戲評分 (1-5): ").strip()
        if rating.isdigit() and 1 <= int(rating) <= 5:
            rating = int(rating)
            break
        else:
            print("無效的評分，請輸入 1-5 之間的數字。")
    
    MAX_COMMENT_LEN = 50
    comment = ""
    while True:
        prompt = f"請撰寫評論內容 (限{MAX_COMMENT_LEN}字內)"
        if comment:
            prompt += f"（上次內容：{comment}）"
        comment_new = input(f"{prompt}: ").strip()
        # 若玩家直接按 Enter，保留原本內容
        if not comment_new and comment:
            comment_new = comment
        if not comment_new:
            print("評論內容不可為空，請重新輸入。")
            continue
        if len(comment_new) > MAX_COMMENT_LEN:
            print(f"評論內容過長，請縮短至{MAX_COMMENT_LEN}字以內。")
            comment = comment_new
            continue
        if any(ord(c) < 32 and c not in '\n\r\t' for c in comment_new):
            print("評論內容包含無法處理的特殊字元，請重新輸入。")
            comment = comment_new
            continue
        comment = comment_new
        break
    while True:
        try:
            #送出評論
            send_json(sock, {
                "cmd": "submit_review",
                "game_id": game_id,
                "rating": rating,
                "comment": comment
            })
            res = recv_json(sock)
            if res and res['status'] == 'ok':
                print("評論已送出，謝謝您的回饋！")
                break
            else:
                print("評論送出失敗。")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            raise
        except Exception as e:
            print(f"[Error] 無法送出評論: {e}")
            choice = input("是否重試? (y/n): ")
            if choice.lower() != 'y':
                return
            else:
                continue

def main():
    parser = argparse.ArgumentParser()
    # 讓腳本可以傳入 --user Player1 來區分下載路徑
    parser.add_argument('--user', type=str, default='Player1', help="模擬的使用者名稱 (決定下載路徑)")
    # parser.add_argument('--ip', type=str, default='127.0.0.1')
    # parser.add_argument('--port', type=int, default=9000)
    args = parser.parse_args()

    global GAMES_ROOT_DIR
    GAMES_ROOT_DIR = os.path.join("games", args.user)
    if not os.path.exists(GAMES_ROOT_DIR):
        os.makedirs(GAMES_ROOT_DIR)

    print(f"[System] 歡迎 {args.user}！您的遊戲將下載至: {GAMES_ROOT_DIR}")

    sock = None
    try:
        # 1. 建立連線
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, LOBBY_PORT))
        print(f"[System] 已連線至 Player Server ({SERVER_IP}:{LOBBY_PORT})")

        # 2. 先登入才能進主選單
        while True:
            print("\n=== 玩家入口 ===")
            print("1. 登入 (Login)")
            print("2. 註冊 (Register)")
            print("3. 離開 (Exit)")
            choice = input("請選擇功能 (1-3): ").strip()
            if choice == '1':
                current_user = login(sock)
                if current_user:
                    break
            elif choice == '2':
                register(sock)
            elif choice == '3':
                print("Bye!")
                sock.close()
                return
            else:
                print("無效的輸入，請重新選擇。")
                print("請選擇功能: ", end='', flush=True)

        if not current_user:
            print("登入取消，程式結束。")
            sock.close()
            return

        # 3. 主選單迴圈
        options = [
            "進入商城 (Enter Marketplace)",
            "下載遊戲 (Download Games)",
            "建立房間 (Create Room)",
            "加入房間 (Join Room)",
            "評論遊戲 (Review Games)",
            "登出/離開 (Exit)"
        ]
        while True:
            choice = str(paged_cli_menu(options, page_size=3))

            if choice == '1':
                market_menu(sock)
            elif choice == '2':
                download_game(sock)
            elif choice == '3':
                create_room_flow(sock)
            elif choice == '4':
                join_room_flow(sock)
            elif choice == '5':
                review_game(sock)
            elif choice == '6':
                print("Bye!")
                break
            else:
                print("無效的輸入，請重新選擇。")

    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
        print(f"\n[Error] 與伺服器連線中斷 ({e})，程式即將關閉。")
    except Exception as e:
        print(f"\n[Error] 發生未預期的錯誤: {e}\n程式即將關閉。")
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

if __name__ == "__main__":
    main()