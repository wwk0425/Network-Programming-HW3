import socket
import os
import sys
import time
import zipfile
import json

# 假設 network.py 放在同層級的 utils 資料夾
# 如果放在同層，直接 from network import ...
from utils import send_json, recv_json, send_file, zip_game_folder
from config import DEV_PORT

# --- 設定 ---
SERVER_IP = '127.0.0.1'
# DEV_PORT = 9001  # 開發者專用 Port

# --- 功能函式 ---
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
        print("\n=== 開發者登入 ===")
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

def upload_game_workflow(sock, username):
    """
    Use Case D1: 上架新遊戲
    """
    print("\n=== 上架新遊戲 ===")
    print("請輸入您的遊戲專案資料夾路徑 (例如: ./my_games/snake)")
    folder_path = input("路徑: ").strip()

    if not os.path.exists(folder_path):
        print("[Error] 路徑不存在。")
        return

    # 1. 本地檢查與壓縮
    zip_path = zip_game_folder(folder_path)
    if not zip_path:
        return # 檢查失敗，中止

    try:
        # 2. 發送上傳請求
        print("[Upload] 正在請求上傳...")
        send_json(sock, {"cmd": "upload_game"})

        # 3. 等待 Server 說 "Ready" (Handshake)
        # 這對應我們在 dev_service 寫的邏輯
        res = recv_json(sock)
        if not res or res.get('status') != 'ready_to_receive':
            print(f"[Error] Server 拒絕上傳: {res.get('msg')}")
            return

        # 4. 開始傳檔
        print("[Upload] 開始傳輸檔案...")
        send_file(sock, zip_path)

        # 5. 等待最終確認
        final_res = recv_json(sock)
        if final_res and final_res['status'] == 'ok':
            print(f"\n>>> {final_res['msg']} <<<")
            print("(您現在可以在 '我的遊戲' 列表中看到它了)")
        else:
            print(f"[Error] 上架失敗: {final_res.get('msg')}")

    except Exception as e:
        print(f"[Error]連線異常: {e}")
    finally:
        # 清除暫存檔
        if os.path.exists(zip_path):
            os.remove(zip_path)

def list_my_games(sock):
    """
    列出該開發者擁有的遊戲 (Optional but useful)
    """
    send_json(sock, {"cmd": "my_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        games = res['games']
        print(f"\n=== 我的遊戲列表 ({len(games)}) ===")
        print(f"{'ID':<15} {'名稱':<20} {'版本':<10} {'評分'}")
        print("-" * 60)
        for g in games:
            print(f"{g['game_id']:<15} {g['name']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
    else:
        print("無法取得列表。")

# --- 主程式 (選單迴圈) ---

def main():
    # 1. 建立連線
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, DEV_PORT))
        print(f"[System] 已連線至 Developer Server ({SERVER_IP}:{DEV_PORT})")
    except Exception as e:
        print(f"[Error] 無法連線至 Server: {e}")
        return

    # 2. 先登入才能進主選單
    while True:
        print("\n=== 開發者入口 ===")
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

    if not current_user:
        print("登入取消，程式結束。")
        sock.close()
        return

    # 3. 主選單迴圈
    while True:
        print("\n" + "="*10 + " Developer Menu " + "="*10)
        print("1. 上架新遊戲 (Upload Game)")
        print("2. 列出我的遊戲 (List My Games)")
        print("3. 登出/離開 (Exit)")
        
        choice = input("請選擇功能 (1-3): ").strip()

        if choice == '1':
            upload_game_workflow(sock, current_user)
        elif choice == '2':
            list_my_games(sock)
        elif choice == '3':
            print("Bye!")
            break
        else:
            print("無效的輸入，請重新選擇。")

    sock.close()

if __name__ == "__main__":
    main()