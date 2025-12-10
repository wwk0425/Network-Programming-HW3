import os

def create_game_template(template_name):
    """
    在當前目錄下創建一個遊戲專案模板資料夾
    內含基本的 manifest.json 與範例執行檔 (空檔案)
    """
    if not template_name:
        print("[Error] 請提供有效的模板名稱。")
        return

    if "games" not in os.listdir('.'):
        os.makedirs("games")
    
    game_path = os.path.join(".", "games", template_name)

    # 1. 建立資料夾
    if not os.path.exists(game_path):
        os.makedirs(game_path)
    else:
        print(f"[Warning] 資料夾 '{template_name}' 已存在。")

    g_server_path = os.path.join(game_path, "server")
    g_client_path = os.path.join(game_path, "client")

    if not os.path.exists(g_server_path):
        os.makedirs(g_server_path)
    if not os.path.exists(g_client_path):
        os.makedirs(g_client_path)

    print(f"[Info] 已建立遊戲專案資料夾: {template_name}，請將game_server放入server資料夾，game_client放入client資料夾。")
