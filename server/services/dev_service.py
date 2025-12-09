import os
from utils import send_json, recv_json, recv_file, send_file, handle_upload_game
from db_storage.database import add_or_update_game
#處理開發者的指令
def handle_dev_client(conn, addr):
    print(f"[Dev] {addr} connected.")
    try:
        while True:
            req = recv_json(conn)
            if not req: break
            
            cmd = req.get('cmd')
            
            if cmd == 'upload_game':
                # 呼叫我們先前寫好的上傳處理邏輯
                handle_upload_game(conn, req) 
            
            # 未來還可以加: update_game, delete_game
            
    except Exception as e:
        print(f"[Dev Error] {e}")
    finally:
        conn.close()

d