import socket
import os
import sys
import time
import zipfile
import json

# 假設 network.py 放在同層級的 utils 資料夾
# 如果放在同層，直接 from network import ...
from utils import send_json, recv_json, send_file, zip_game_folder,paged_dev_menu
from config import DEV_PORT
from template.create_game_template import create_game_template

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
    if "games" not in os.listdir('.'):
        print("[Info] 請先使用創建上傳目錄指令創建 'games' 目錄，並創建好要上傳的遊戲的目錄。")
        return
    
    games_path = os.path.join('.', 'games')

    if os.listdir(games_path) == []:
        print("[Info] 'games' 目錄目前是空的，請先放入要上傳的遊戲資料夾。")
        return
    
    
    print(f"[Info] 目前可上傳的遊戲專案資料夾有:")
    dir_length = len(os.listdir(games_path))
    for idx, game in enumerate(os.listdir(games_path)):
        print(f"  {idx+1}. {game}")

    choice = input(f"請輸入您想上傳的遊戲:(1~{dir_length})").strip()
    if not (choice.isdigit() and 1 <= int(choice) <= dir_length):
        print("[Error] 輸入超出範圍，請重新操作。")
        return
    
    selected_game = os.listdir(games_path)[int(choice)-1]

    #如果遊戲已經上傳過 提示去更新他
    #因為上傳檔案變成 game_id-uploadername 所以這邊要加上-uploadername
    selected_game_with_uploader = f"{selected_game}-{username}"
    send_json(sock, {"cmd": "my_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        my_games = res['games']
        for g in my_games:
            if g['game_id'] == selected_game_with_uploader:
                print(f"[Info] 您已經上傳過此遊戲 '{selected_game}'，請使用更新遊戲內容功能來更新它。")
                return
    else:
        print("[Error] 無法取得已上傳遊戲列表，請稍後再試。")
        return

    game_folder_path = os.path.join(games_path, selected_game)
    # 1. 本地檢查與壓縮
    zip_path = zip_game_folder(game_folder_path, username=username, update=False)
    if not zip_path:
        return # 檢查失敗，中止

    while True:
        try:
            # 2. 發送上傳請求
            print("[Upload] 正在請求上傳...")
            send_json(sock, {"cmd": "upload_game"})

            # 3. 等待 Server 說 "Ready" (Handshake)
            # 這對應我們在 dev_service 寫的邏輯
            res = recv_json(sock)
            if not res or res.get('status') != 'ready_to_receive':
                print(f"[Error] Server 拒絕上傳: {res.get('msg')}")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue

            # 4. 開始傳檔
            print("[Upload] 開始傳輸檔案...")
            send_file(sock, zip_path)

            # 5. 等待最終確認
            final_res = recv_json(sock)
            if final_res and final_res['status'] == 'ok':
                print(f"\n>>> {final_res['msg']} <<<")
                print("(您現在可以在 '我的遊戲' 列表中看到它了)")
                break
            else:
                print(f"[Error] 上架失敗: {final_res.get('msg')}")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            raise
        except Exception as e:
            print(f"[Error] 本地處理異常: {e}")
            choice = input("是否重試? (y/n): ")
            if choice.lower() != 'y':
                return
            else:
                continue
        finally:
            # 清除暫存檔
            if os.path.exists(zip_path):
                os.remove(zip_path)

def update_game_workflow(sock, username):
    """
    Use Case D2: 更新已上架遊戲
    """
    print("\n=== 上架新遊戲 ===")
    if "games" not in os.listdir('.'):
        print("[Info] 請先使用創建上傳目錄指令創建 'games' 目錄，並創建好要上傳的遊戲的目錄。")
        return
    
    games_path = os.path.join('.', 'games')

    if os.listdir(games_path) == []:
        print("[Info] 'games' 目錄目前是空的，請確認已放入要更新的遊戲資料夾。")
        return
    
    send_json(sock, {"cmd": "my_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        my_games = res['games']
    else:
        print("[Error] 無法取得已上傳遊戲列表，請稍後再試。")
        return
            
    print(f"[Info] 目前可更新的遊戲專案有:")

    ##做了確認是否輸入在範圍內
    list_game_length = len(my_games)

    while True:
        for idx, game in enumerate(my_games):
            print(f"  {idx+1}. {game.get('game_id', 'Unknown')}")
        choice = input(f"請輸入您想更新的遊戲:(1~{list_game_length})").strip()
        if 1 <= int(choice) <= list_game_length:
            break
        else:
            print("[Error] 輸入超出範圍，請重新操作。")

    #檢查要更新的遊戲有沒有目錄
    selected_game = my_games[int(choice)-1].get('game_id')
    #因為上傳檔案變成 game_id-uploadername 所以這邊要去掉-uploadername
    if '-' in selected_game:
        selected_game = selected_game.rsplit('-', 1)[0]
    if selected_game not in os.listdir(games_path):
        print(f"[Info] 'games' 目錄中沒有找到遊戲 '{selected_game}' 的資料夾，請確認已放入要更新的遊戲資料夾。")
        return
    game_folder_path = os.path.join(games_path, selected_game)

    # 1. 本地檢查與壓縮
    zip_path = zip_game_folder(game_folder_path, username=username, update=True)
    if not zip_path:
        return # 檢查失敗，中止
    
    while True:
        try:
            # 2. 發送上傳請求
            print("[Upload] 正在請求上傳...")
            send_json(sock, {"cmd": "upload_game"})

            # 3. 等待 Server 說 "Ready" (Handshake)
            # 這對應我們在 dev_service 寫的邏輯
            res = recv_json(sock)
            if not res or res.get('status') != 'ready_to_receive':
                print(f"[Error] Server 拒絕上傳: {res.get('msg')}")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue

            # 4. 開始傳檔
            print("[Upload] 開始傳輸檔案...")
            send_file(sock, zip_path)

            # 5. 等待最終確認
            final_res = recv_json(sock)
            if final_res and final_res['status'] == 'ok':
                print(f"\n>>> {final_res['msg']} <<<")
                print("(您現在可以在 '我的遊戲' 列表中看到新版本號了)")
                break
            else:
                print(f"[Error] 更新失敗: {final_res.get('msg')}，請重新嘗試更新")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            raise
        except Exception as e:
            print(f"[Error]連線異常: {e}，請重新嘗試更新")
            choice = input("是否重試? (y/n): ")
            if choice.lower() != 'y':
                return
            else:
                continue
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
        print(f"{'名稱-作者':<20} {'版本':<10} {'評分'}")
        print("-" * 60)
        for g in games:
            print(f"{g['game_id']:<20} {g['version']:<10} {g.get('average_rating', 0)}")
    else:
        print("無法取得列表。")

def delete_game_workflow(sock, username):
    """
    Use Case D3: 下架遊戲內容
    """
    
    print("\n=== 下架遊戲內容 ===")
    send_json(sock, {"cmd": "my_games"})
    res = recv_json(sock)
    if res and res['status'] == 'ok':
        my_games = res['games']
    else:
        print("[Error] 無法取得已上傳遊戲列表，請稍後再試。")
        return                
    print(f"[Info] 目前可下架的遊戲專案有:")

    ##做了確認是否輸入在範圍內
    list_game_length = len(my_games)

    while True:
        for idx, game in enumerate(my_games):
            print(f"  {idx+1}. {game.get('game_id', 'Unknown')}")
        choice = input(f"請輸入您想下架的遊戲:(1~{list_game_length})").strip()
        if choice == '':
            print("[Error] 輸入不可為空，請重新操作。")
            continue
        if 1 <= int(choice) <= list_game_length:
            break
        else:
            print("[Error] 輸入超出範圍，請重新操作。")
    print(f"[Info] 您是否確定選擇下架遊戲 '{my_games[int(choice)-1].get('game_id')}'，此操作無法復原！")
    confirm = input("請輸入 Y 確認下架，或其他鍵取消: ").strip()
    if confirm.lower() != 'y':
        print("下架操作已取消。")
        return
            
    selected_game = my_games[int(choice)-1].get('game_id')
    while True:
        try:
            # 發送下架請求
            send_json(sock, {"cmd": "delete_game", "game_id": selected_game})
            res = recv_json(sock)
            if res and res['status'] == 'ok':
                print(f"[Info] 遊戲 '{selected_game}' 已成功下架。")
                break
            else:
                print(f"[Error] 無法下架遊戲: {res.get('msg', 'Unknown error')}，請稍後重新嘗試下架")
                choice = input("是否重試? (y/n): ")
                if choice.lower() != 'y':
                    return
                else:
                    continue
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            raise
        except Exception as e:
            print(f"[Error]本地異常: {e}，請重新嘗試下架遊戲。")
            choice = input("是否重試? (y/n): ")
            if choice.lower() != 'y':
                return
            else:
                continue
# --- 主程式 (選單迴圈) ---

def main():
    sock = None
    try:
        # 1. 建立連線
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, DEV_PORT))
        print(f"[System] 已連線至 Developer Server ({SERVER_IP}:{DEV_PORT})")

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
        options = [
                "上架新遊戲 (Upload Game)",
                "列出我的遊戲 (List My Games)",
                "創建遊戲模板 (Create Game Template)",
                "更新遊戲內容 (Update Game Content)",
                "下架遊戲內容 (Remove Game)",
                "登出/離開 (Exit)"
        ]
        while True:
            choice = str(paged_dev_menu(options, page_size=3))
            if choice == '1':
                upload_game_workflow(sock, current_user)
            elif choice == '2':
                list_my_games(sock)
            elif choice == '3':
                print("\n" + "="*7 + " Developer Menu " + "="*7)
                template_name = input("請輸入遊戲名稱: ").strip()
                create_game_template(template_name)
            elif choice == '4':
                update_game_workflow(sock, current_user)
            elif choice == '5':
                delete_game_workflow(sock, current_user)
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