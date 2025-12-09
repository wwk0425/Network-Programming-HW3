import threading
import socket
from config import LOBBY_PORT, DEV_PORT
from services.lobby_service import handle_lobby_client
from services.dev_service import handle_dev_client

def start_service(port, handler_func, service_name):
    """
    通用的 Server 啟動函式
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(5)
    print(f"[System] {service_name} listening on port {port}...")

    while True:
        conn, addr = server.accept()
        # 為每個連線建立一個執行緒
        t = threading.Thread(target=handler_func, args=(conn, addr))
        t.daemon = True # 設定為守護執行緒，主程式結束時會自動關閉
        t.start()

if __name__ == "__main__":
    print("=== Game Platform Server Starting ===")
    
    # 啟動 Lobby Server (玩家用)
    t_lobby = threading.Thread(
        target=start_service, 
        args=(LOBBY_PORT, handle_lobby_client, "Lobby Server")
    )
    
    # 啟動 Developer Server (開發者用)
    t_dev = threading.Thread(
        target=start_service, 
        args=(DEV_PORT, handle_dev_client, "Developer Server")
    )

    t_lobby.start()
    t_dev.start()

    # 主執行緒等待 (防止程式直接結束)
    t_lobby.join()
    t_dev.join()