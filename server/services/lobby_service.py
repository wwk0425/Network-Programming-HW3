import os
from utils import send_json, recv_json, recv_file, send_file

def handle_lobby_client(conn, addr):
    print(f"[Player] {addr} connected.")
    try:
        while True:
            req = recv_json(conn)
            if not req: break
            
            cmd = req.get('cmd')
            
            if cmd == 'list_games':
                # 從共用資料庫取得遊戲列表
                games = get_game_list()
                send_json(conn, {"status": "ok", "games": games})
            
            elif cmd == 'create_room':
                # 處理開房邏輯...
                pass

            # 注意：這裡沒有 upload_game，玩家傳這個指令會被視為 Unknown

    except Exception as e:
        print(f"[Player Error] {e}")
    finally:
        conn.close()