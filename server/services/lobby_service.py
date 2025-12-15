import socket
import threading
import subprocess
import os
import time
import json

# 引用工具與資料庫
from utils import recv_json, send_json, zip_game_folder_to_player, send_file, compare_versions_player
from db_storage.database import verify_login, register_user, get_all_games, create_room_in_db, get_all_rooms, join_room_in_db, update_room_status, remove_player_from_room, get_room_info, add_player_ready, remove_player_ready, record_player_game_record, get_player_game_records, add_review, player_exit
from config import LOBBY_PORT
# --- 全域變數 ---
online_users = {} # username -> conn
room_processes = {} # room_id -> subprocess.Popen
room_id_counter = 1
online_users_lock = threading.Lock()

# --- 輔助函式: 尋找閒置 Port ---
def find_free_port():
    """
    找一個目前沒被佔用的 Port 給遊戲 Server 使用
    範圍: 10000 ~ 20000 (避免撞到系統 Port)
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0)) # OS 自動分配
        return s.getsockname()[1]

# --- 廣播函式 ---
def broadcast_to_room(room_id, message_dict):
    """
    將訊息傳送給房間內的所有人
    """
    room_info = get_room_info(room_id)
    if not room_info:
        return
    
    player_names = room_info['players']

    with online_users_lock:
        for pname in player_names:
            if pname in online_users:
                conn = online_users[pname]
                try:
                    send_json(conn, message_dict)
                except:
                    print(f"[Error] Failed to send message to {pname}")

# --- 主邏輯 ---
def handle_lobby_client(conn, addr):
    global room_id_counter
    print(f"[Lobby] {addr} connected.")
    
    current_user = None
    current_room_id = None

    try:
        while True:
            req = recv_json(conn)
            if not req: break
            
            cmd = req.get('cmd')
            print(f"[Lobby] {addr} User: {current_user} | Cmd: {cmd}")

            # === 1. 註冊 (Register) ===
            if cmd == 'register':
                username = req.get('username')
                password = req.get('password')
                if register_user(username, password, role="player"):
                    send_json(conn, {"status": "ok", "msg": "Register success"})
                else:
                    send_json(conn, {"status": "error", "msg": "Username exists"})

            # === 2. 登入 (Login) ===
            elif cmd == 'login':
                username = req.get('username')
                password = req.get('password')
                if verify_login(username, password, role="player"):
                    current_user = username

                    with online_users_lock:
                        online_users[username] = conn

                    send_json(conn, {"status": "ok", "msg": f"Welcome {username}"})
                else:
                    send_json(conn, {"status": "error", "msg": "Wrong username or password or already online"})

            elif cmd == 'end_game':
                # 玩家遊戲結束後的回報 (可選)
                room_id = req.get('room_id')
                result = req.get('result')  # Win/Lose/Draw
                # 這裡可以更新玩家的遊戲紀錄或評分
                room = get_room_info(room_id)
                player = room['players']
                for p in player:
                    record_player_game_record(p, room['game_id'], result.lower())
                #移除房間中準備的人數
                remove_player_ready(room_id)
                update_room_status(room_id, "Waiting", None)
                broadcast_to_room(room_id, {"cmd": "game_ended", "result": result})
                proc = room_processes.get(room_id)
                if proc:
                    proc.terminate()
                if room_id in room_processes:
                    del room_processes[room_id]
            # === Middleware: 以下指令都需要登入 ===
            elif not current_user:
                send_json(conn, {"status": "error", "msg": "Please login first"})
                continue

            # === 3. 列出所有遊戲 (List Games) ===
            elif cmd == 'list_games':
                # 從 DB 讀取遊戲列表 (包含評分)
                games_data = get_all_games()
                # 轉成 List 回傳
                game_list = list(games_data.values())
                send_json(conn, {"status": "ok", "games": game_list})

            # === 4. 列出房間 (List Rooms) ===
            elif cmd == 'list_rooms':
                rooms_data = get_all_rooms()
                room_list = []

                all_games = get_all_games()
                for rid, rdata in rooms_data.items():
                    game_name = rdata['game_id']
                    room_list.append({
                        "id": rid,
                        "game_id": game_name,
                        "host": rdata['host'],
                        "status": rdata['status'],
                        "cur_players": len(rdata['players']),
                        "max_players": rdata['max_players']
                    })
                send_json(conn, {"status": "ok", "rooms": room_list})

            elif cmd == 'get_host':
                if not current_room_id:
                    send_json(conn, {"status": "error", "msg": "Not in a room"})
                    continue
                room_info = get_room_info(current_room_id)
                if not room_info:
                    send_json(conn, {"status": "error", "msg": "Room not found"})
                    continue
                host_name = room_info['host']
                flag = (host_name == current_user)
                send_json(conn, {"status": "ok", "host": flag})

            # === 5. 建立房間 (Create Room) ===
            elif cmd == 'create_room':
                game_id = req.get('game_id')
                all_games = get_all_games()
                
                if game_id not in all_games:
                    send_json(conn, {"status": "error", "msg": "遊戲不存在或者剛剛被下架了"})
                    continue
                #檢查遊戲是否為不可用狀態
                if all_games[game_id]['status'] == "unavailable":
                    send_json(conn, {"status": "error", "msg": "遊戲目前不可用，請聯絡開發者"})
                    continue
                max_p = all_games[game_id].get('max_players', 4)
                rid = room_id_counter

                create_room_in_db(rid, game_id, current_user, max_p)
                current_room_id = rid
                room_id_counter += 1

                send_json(conn, { "status": "ok", "room_id": rid, "msg": "Room created"})
                broadcast_to_room(rid, {"cmd": "player_joined", "username": current_user})
                
            # === 6. 加入房間 (Join Room) ===
            elif cmd == 'join_room':
                target_rid = req.get('room_id')

                # 判斷是否可加入
                room_info = get_room_info(target_rid)
                if not room_info:
                    send_json(conn, {"status": "error", "msg": "Room not found"})
                    continue
                games = get_all_games()
                if room_info['game_id'] not in games:
                    send_json(conn, {"status": "error", "msg": "遊戲不存在或者剛剛被下架了"})
                    continue
                if games[room_info['game_id']]['status'] == "unavailable":
                    send_json(conn, {"status": "error", "msg": "遊戲目前不可用，請聯絡開發者"})
                    continue

                success, msg = join_room_in_db(target_rid, current_user)
                if success:
                    current_room_id = target_rid
                    send_json(conn, {"status": "ok", "msg": msg})

                    broadcast_to_room(target_rid, {
                        "cmd": "player_joined", "username": current_user
                    })
                else:
                    send_json(conn, {"status": "error", "msg": msg})

            # === 7. 開始遊戲 (Start Game) - 核心難點 ===
            elif cmd == 'start_game':
                if not current_room_id:
                    send_json(conn, {"cmd": "start_game_error", "status": "error", "msg": "Not in a room"})
                    continue
                
                room_info = get_room_info(current_room_id)
                if not room_info:
                    send_json(conn, {"cmd": "start_game_error", "status": "error", "msg": "Room not found"})
                    continue
                if room_info['host'] != current_user:
                    #讓非房主進行準備
                    add_player_ready(current_room_id, current_user)
                    send_json(conn, {"cmd": "player_ready", "msg": "You are ready"})
                    continue
                
                if room_info['host'] == current_user:
                    #先檢查遊戲被下架了沒
                    all_games = get_all_games()
                    if room_info['game_id'] not in all_games:
                        broadcast_to_room(current_room_id, {"cmd": "start_game_error", "status": "error", "msg": "遊戲不存在或者剛剛被下架了"})
                        remove_player_ready(current_room_id)
                        continue
                    #檢查遊戲是否為不可用狀態
                    if all_games[room_info['game_id']]['status'] == "unavailable":
                        broadcast_to_room(current_room_id, {"cmd": "start_game_error", "status": "error", "msg": "遊戲目前不可用，請聯絡開發者"})
                        remove_player_ready(current_room_id)
                        continue
                    #確認有沒有滿足最少玩家數
                    if len(room_info['players']) < all_games[room_info['game_id']].get('min_players', 2):
                        send_json(conn, {"cmd": "start_game_error", "status": "error", "msg": "Not enough players to start the game"})
                        continue
                    #確認除了自己 大家都準備好就開始
                    all_ready = all(player in room_info.get('ready_players', []) for player in room_info['players'] if player != current_user)
                    if not all_ready:
                        send_json(conn, {"cmd": "start_game_error", "status": "error", "msg": "Not all players are ready"})
                        continue
                    add_player_ready(current_room_id, current_user)
                # 1. 找 Port
                game_port = find_free_port()
                
                # 2. 啟動 Process (邏輯同前，略過細節)
                game_id = room_info['game_id']
                all_games = get_all_games()
                game_path = all_games[game_id]['path']
                server_exe = all_games[game_id]['server_exe']
                client_exe = all_games[game_id]['client_exe']
                client_args = all_games[game_id].get('client_args', "")
                full_exe_path = os.path.abspath(os.path.join(game_path, server_exe))
                player_num = len(room_info['players'])
                try:
                    cmd_list = ["python", full_exe_path, "--port", str(game_port), "--lobby_ip", "140.113.17.11", "--lobby_port", str(LOBBY_PORT), "--room_id", str(current_room_id), "--players", str(player_num)] + all_games[game_id].get('server_args', "").split() if full_exe_path.endswith('.py') else [full_exe_path, "--port", str(game_port), "--lobby_ip", "127.0.0.1", "--lobby_port", str(LOBBY_PORT), "--room_id", str(current_room_id), "--players", str(player_num)] + all_games[game_id].get('server_args', "").split()
                    proc = subprocess.Popen(cmd_list, cwd=os.path.abspath(game_path))
                    room_processes[current_room_id] = proc
                    # 3. 更新 DB 狀態
                    update_room_status(current_room_id, "Playing", game_port)
                    
                    # 4. 廣播
                    broadcast_to_room(current_room_id, {
                        "cmd": "game_start", 
                        "ip": "140.113.17.11", 
                        "port": game_port,
                        "client_args": client_args,
                        "game_path": game_path,
                        "client_exe": client_exe,
                        "room_id": current_room_id
                    })
                    
                except Exception as e:
                    if current_room_id in room_processes:
                        proc = room_processes[current_room_id]
                        if proc:
                            proc.terminate()
                        if current_room_id in room_processes:
                            del room_processes[current_room_id]
                    broadcast_to_room(current_room_id, {"cmd": "game_start_failed", "msg": "有玩家啟動遊戲失敗，遊戲已中止"})
                    remove_player_ready(current_room_id)
                    update_room_status(current_room_id, "Waiting", None)

            elif cmd == 'client_start_failed':
                # 玩家端無法啟動遊戲的回報
                room_id = req.get('room_id')
                proc = room_processes.get(room_id)
                if proc:
                    proc.terminate()
                    print(f"[System] 已關閉房間 {room_id} 的遊戲進程")
                if room_id in room_processes:
                    del room_processes[room_id] 
                    remove_player_ready(room_id)
                    update_room_status(room_id, "Waiting", None)
                    broadcast_to_room(room_id, {"cmd": "game_start_failed", "msg": "有玩家啟動遊戲失敗，遊戲已中止"})

            elif cmd == 'leave_room':
                if not current_room_id:
                    send_json(conn, {"status": "error", "msg": "Not in a room"})
                    continue
                #紀錄房主以外的人 來告訴他們房間關閉了
                
                result = remove_player_from_room(current_room_id, current_user)
                room_info = get_room_info(current_room_id)
                host_name = room_info['host'] if room_info else None
                if result == "player_left":
                    broadcast_to_room(current_room_id, {
                        "cmd": "player_left", "username": current_user
                    })
                elif result == "host_changed":
                    broadcast_to_room(current_room_id, {
                        "cmd": "host_changed", "msg": f"Host left, new host {host_name} assigned."
                    })
                elif result == "room_closed":
                    broadcast_to_room(current_room_id, {
                        "cmd": "room_closed", "msg": "Host left, room closed."
                    })
                
                current_room_id = None
                send_json(conn, {"status": "ok", "msg": "Left the room"})

            # === 8. 下載遊戲 (Download) ===
            elif cmd == 'compare_version':
                game_id = req.get('game_id')
                current_version = req.get('current_version')

                all_games = get_all_games()
                if game_id not in all_games:
                    send_json(conn, {"status": "error", "msg": "遊戲不存在或者剛剛被下架了"})
                    continue

                latest_version = all_games[game_id]['version']
                if latest_version == current_version:
                    send_json(conn, {"status": "ok", "up_to_date": True, "msg": "You have the latest version."})
                else:
                    send_json(conn, {"status": "ok", "up_to_date": False, "latest_version": latest_version, "msg": "A new version is available."})

            # === 9. 下載遊戲 (Download) ===
            elif cmd == 'download_game':
                # 這是給 Client 下載 ZIP 用的
                target_game_id = req.get('game_id')
                all_games = get_all_games()
                if target_game_id not in all_games:
                    send_json(conn, {"status": "error", "msg": "遊戲不存在或者剛剛被下架了"})
                    continue
                
                game_info = all_games[target_game_id]
                game_path = game_info['path'] # e.g. "games/snake/1.0"
                
                # 我們需要把這個資料夾打包成 zip 傳給玩家
                # 或是如果開發者上傳時留了 zip 備份，直接傳那個也可以
                # 這裡示範: 即時打包 (或你可以回傳之前上傳暫存的 zip，看你設計)
                
                # 簡化版：假設我們不打包，請玩家自己去跟 Developer Server 下載 (不建議)
                # 進階版：呼叫 utils 的 send_file 傳送
                # 為了 Demo 方便，這裡先留白，或直接用 send_file 傳送 "games/{id}/{ver}/client" 資料夾
                # (作業提示通常是讓 Client 下載整包)
                zip_path = zip_game_folder_to_player(game_path)
                if not zip_path:
                    send_json(conn, {"status": "error", "msg": "Failed to create zip"})
                    continue

                try:
                    # 2. 發送上傳請求
                    print("[Upload] 正在請求上傳...")
                    send_json(conn, {"status": "ok", "file_size": os.path.getsize(zip_path)})

                    # 3. 等待 client 說 "Ready" (Handshake)
                    # 這對應我們在 dev_service 寫的邏輯
                    res = recv_json(conn)
                    if not res or res.get('status') != 'ready_to_receive':
                        print(f"[Error] Client 拒絕上傳: {res.get('msg')}")
                        return

                    # 4. 開始傳檔
                    print("[Upload] 開始傳輸檔案...")
                    send_file(conn, zip_path)

                    # 5. 等待最終確認
                    final_res = recv_json(conn)
                    if final_res and final_res['status'] == 'ok':
                        print(f"\n>>> {final_res['msg']} <<<")
                    else:
                        print(f"[Error] 上傳失敗: {final_res.get('msg')}")

                except Exception as e:
                    print(f"[Error]連線異常: {e}")
                finally:
                    # 清除暫存檔
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
            # 評論
            elif cmd == "played_game_list":
                records = get_player_game_records(current_user)
                unique_game_ids = set(record["game_id"] for record in records)
                games_data = get_all_games()
                # 轉成 List 回傳
                filtered_games = [games_data[gid] for gid in unique_game_ids if gid in games_data]
                send_json(conn, {"status": "ok", "played_games": filtered_games})

            elif cmd == 'submit_review':
                game_id = req.get('game_id')
                rating = req.get('rating')
                comment = req.get('comment')
                add_review(
                    game_id=game_id,
                    player_name=current_user,
                    score=rating,
                    comment=comment)
                send_json(conn, {"status": "ok", "msg": "Review submitted successfully."})
            else:
                send_json(conn, {"status": "error", "msg": "Unknown command"})

    except Exception as e:
        print(f"[Lobby Error] {e}")
        import traceback
        traceback.print_exc()
    finally:
        # === 斷線處理 (Cleanup) ===
        # 如果玩家斷線，要從房間移除。如果他是房主，解散房間。
        if current_user:
            with online_users_lock:
                if current_user in online_users:
                    del online_users[current_user]
            if current_room_id:
                result = remove_player_from_room(current_room_id, current_user)
                if result == "player_left":
                    broadcast_to_room(current_room_id, {
                        "cmd": "player_left", "username": current_user
                    })
                elif result == "room_closed":
                    broadcast_to_room(current_room_id, {
                        "cmd": "room_closed", "msg": "Host left, room closed."
                    })
        player_exit(current_user, role="player")
        conn.close()
        print(f"[Lobby] {addr} disconnected.")