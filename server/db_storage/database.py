import json
import threading
import os
import time
import shutil

# 檔案路徑
USER_DB_FILE = "server_data/users.json"
GAME_DB_FILE = "server_data/games.json"
ROOM_DB_FILE = "server_data/rooms.json"

# 鎖 (分別鎖定，提升效能)
user_lock = threading.Lock()
game_lock = threading.Lock()
room_lock = threading.Lock()

# --- 初始化 ---
def init_db():
    if not os.path.exists("server_data"):
        os.makedirs("server_data")
        
    if not os.path.exists(USER_DB_FILE):
        with open(USER_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump({"developers": {}, "players": {}}, f)
    else:
        #讓玩家都離線
        with open(USER_DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for role in ['developers', 'players']:
            for username in data[role]:
                data[role][username]['status'] = 'offline'
        with open(USER_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    if not os.path.exists(GAME_DB_FILE):
        with open(GAME_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f) # 一開始是空的字典

    with open(ROOM_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)
# --- 遊戲相關功能 ---

def get_all_games():
    """回傳所有遊戲列表 (包含評分)"""
    with game_lock:
        with open(GAME_DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

def add_or_update_game(game_id, manifest_data, relative_path, uploader_name):
    """
    當開發者上傳成功後，呼叫此函式更新資料庫
    """
    with game_lock:
        # 1. 讀取舊資料
        with open(GAME_DB_FILE, 'r', encoding='utf-8') as f:
            games = json.load(f)
        
        # 2. 準備新資料
        # 如果遊戲已存在，保留舊的評論；如果是新遊戲，初始化評論列表
        if game_id in games:
            old_data = games[game_id]
            reviews = old_data.get("reviews", [])
            avg_rating = old_data.get("average_rating", 0.0)
        else:
            reviews = []
            avg_rating = 0.0

        # 更新欄位 (版本、路徑可能變了)
        games[game_id] = {
            "game_id": game_id,
            "version": manifest_data.get("version", "1.0"),
            "description": manifest_data.get("description", ""),
            "min_players": manifest_data.get("min_players", 1),
            "max_players": manifest_data.get("max_players", 4),
            "server_exe": manifest_data.get("server_exe"), # 重要：啟動時需要
            "client_exe": manifest_data.get("client_exe"), # 重要：下載時需要
            "update_patch": manifest_data.get("update_patch", ""),
            "type": manifest_data.get("type", ""),
            # 系統維護欄位
            "status": "available", # 可用/不可用
            "uploader": uploader_name,
            "path": relative_path, # 存例如: games/snake/1.0
            "upload_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            
            # 保留評分數據
            "reviews": reviews,
            "average_rating": avg_rating
        }
        
        # 3. 寫回檔案
        with open(GAME_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(games, f, indent=4, ensure_ascii=False)
            
    print(f"[DB] Game '{game_id}' updated in database.")

def add_review(game_id, player_name, score, comment):
    """
    玩家評分與留言
    """
    with game_lock:
        with open(GAME_DB_FILE, 'r', encoding='utf-8') as f:
            games = json.load(f)
            
        if game_id not in games:
            return False # 遊戲不存在
            
        # 新增評論
        new_review = {
            "user": player_name,
            "score": score,
            "comment": comment,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        games[game_id]["reviews"].append(new_review)
        
        # 重新計算平均分數
        reviews = games[game_id]["reviews"]
        total_score = sum(r["score"] for r in reviews)
        games[game_id]["average_rating"] = round(total_score / len(reviews), 1)
        
        with open(GAME_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(games, f, indent=4, ensure_ascii=False)
            
        return True

def register_user(username, password, role="player"):
    """
    role: 'player' or 'developer'
    回傳: True (成功), False (帳號已存在)
    """
    with user_lock: # 鎖定
        with open(USER_DB_FILE, 'r') as f:
            data = json.load(f)
        
        # 決定要存哪區
        group = "players" if role == "player" else "developers"
        
        # 檢查重複
        if username in data[group]:
            return False 
        
        # 寫入
        if role == "player":
            data[group][username] = {
                "password": password,
                "game_records": [],  # 紀錄玩家的遊戲結果
                "status": "offline"  # 玩家狀態
            }
        else:
            data[group][username] = {
                "password": password,
                "status": "offline"  # 開發者狀態
            }
        
        with open(USER_DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True

def verify_login(username, password, role="player"):
    with user_lock:
        with open(USER_DB_FILE, 'r') as f:
            data = json.load(f)
            
        group = "players" if role == "player" else "developers"
        
        # 檢查帳密
        if username in data[group] and isinstance(data[group][username], dict):
            if data[group][username].get("password") == password:
                if data[group][username].get("status") != "online":
                    data[group][username]["status"] = "online"
                    with open(USER_DB_FILE, 'w') as f:
                        json.dump(data, f, indent=4)
                    return True
        return False
    
def player_exit(username, role="player"):
    with user_lock:
        with open(USER_DB_FILE, 'r') as f:
            data = json.load(f)
        
        # 尋找目前在線的玩家或開發者，並設為離線
        group = "players" if role == "player" else "developers"
        if username in data[group]:
            data[group][username]["status"] = "offline"
        
        with open(USER_DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)

def create_room_in_db(room_id, game_id, host_name, max_players):
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        
        rooms[str(room_id)] = {
            "id": room_id,
            "game_id": game_id,
            "host": host_name,
            "status": "Waiting",
            "max_players": max_players,
            "players": [host_name], # 只存名字 (String)，不存 Socket
            "ready_players": []
        }
        
        with open(ROOM_DB_FILE, 'w') as f:
            json.dump(rooms, f, indent=4)

def get_room_info(room_id):
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        return rooms.get(str(room_id))

def get_all_rooms():
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            return json.load(f)

def join_room_in_db(room_id, player_name):
    """
    回傳: (Success: bool, Message: str)
    """
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        
        rid = str(room_id)
        if rid not in rooms:
            return False, "Room not found"
        
        room = rooms[rid]
        if len(room['players']) >= room['max_players']:
            return False, "Room is full"
        if room['status'] != "Waiting":
            return False, "Game already started"
        if player_name in room['players']:
            return False, "Already in room"

        # 加入玩家
        room['players'].append(player_name)
        
        with open(ROOM_DB_FILE, 'w') as f:
            json.dump(rooms, f, indent=4)
            
        return True, "Joined successfully"
    
def update_room_status(room_id, status, game_port=None):
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        
        rid = str(room_id)
        if rid in rooms:
            rooms[rid]['status'] = status
            if game_port:
                rooms[rid]['port'] = game_port
            
            with open(ROOM_DB_FILE, 'w') as f:
                json.dump(rooms, f, indent=4)

def remove_player_from_room(room_id, player_name):
    """
    玩家離開或斷線。如果房主離開更換房主，回傳 'player_left'
    """
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        
        rid = str(room_id)
        if rid not in rooms:
            return "not_found"
            
        room = rooms[rid]
        
        if player_name in room['players']:
            room['players'].remove(player_name)
        
        result = "player_left"
        
        if room['host'] == player_name:
            # 房主離開，指定新房主
            if room['players']:
                room['host'] = room['players'][0] # 指定第一個玩家為新房主
                result = "host_changed"
                
        # 檢查: 如果沒人了，或房主離開 -> 刪除房間
        if not room['players']:
            del rooms[rid]
            result = "room_closed"
        else:
            # 寫回更新後的房間資料
             pass # Python 的 dict 是 reference，只要最後 dump rooms 即可
             
        with open(ROOM_DB_FILE, 'w') as f:
            json.dump(rooms, f, indent=4)
            
        return result
    
def remove_game(game_id, uploader_name):
    """
    刪除遊戲資料與檔案
    回傳: True (成功), False (失敗)
    """
    with game_lock:
        with open(GAME_DB_FILE, 'r', encoding='utf-8') as f:
            games = json.load(f)
        
        if game_id not in games:
            return False
        
        game = games[game_id]
        
        # 確認是上傳者在刪除
        if game['uploader'] != uploader_name:
            return False
        
        # 刪除遊戲檔案
        if not os.path.exists(game['path']):
            print(f"[Warning] Game path '{game_id}' does not exist.")
            return False
        
        version_path = game['path']
        parts = version_path.split("\\")
        game_path = "\\".join(parts[:2])  # 遊戲主目錄
        
        if os.path.exists(game_path):
            shutil.rmtree(game_path)
        else:
            print(f"[Warning] Game directory '{game_id}' does not exist.")
            return False
        
        # 刪除資料庫中的遊戲記錄
        del games[game_id]
        
        with open(GAME_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(games, f, indent=4, ensure_ascii=False)
        
        print(f"[DB] Game '{game_id}' removed from database.")
        return True

def add_player_ready(room_id, player_name):
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        
        rid = str(room_id)
        if rid in rooms:
            room = rooms[rid]
            if 'ready_players' not in room:
                room['ready_players'] = []
            if player_name not in room['ready_players']:
                room['ready_players'].append(player_name)
            
            with open(ROOM_DB_FILE, 'w') as f:
                json.dump(rooms, f, indent=4)

def remove_player_ready(room_id):
    with room_lock:
        with open(ROOM_DB_FILE, 'r') as f:
            rooms = json.load(f)
        
        rid = str(room_id)
        if rid in rooms:
            room = rooms[rid]
            #移除所有玩家準備狀態
            if 'ready_players' in room:
                room['ready_players'] = []
            
            with open(ROOM_DB_FILE, 'w') as f:
                json.dump(rooms, f, indent=4)

def record_player_game_record(player_name, game_id, result):
    """
    紀錄玩家的遊戲結果
    result: 'win' or 'lose' or 'draw'
    """
    with user_lock:
        with open(USER_DB_FILE, 'r') as f:
            data = json.load(f)
        
        if player_name not in data['players']:
            return False
        
        player_data = data['players'][player_name]
        if 'game_records' not in player_data:
            player_data['game_records'] = []
        
        record = {
            "game_id": game_id,
            "result": result,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        player_data['game_records'].append(record)
        
        with open(USER_DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        
        return True

def get_player_game_records(player_name):
    """
    取得玩家的遊戲紀錄列表
    """
    with user_lock:
        with open(USER_DB_FILE, 'r') as f:
            data = json.load(f)
        
        if player_name not in data['players']:
            return []
        
        player_data = data['players'][player_name]
        return player_data.get('game_records', [])

def change_game_status(game_id, new_status):
    """
    更改遊戲的狀態 (例如: 可用/不可用)
    """
    with game_lock:
        with open(GAME_DB_FILE, 'r', encoding='utf-8') as f:
            games = json.load(f)
        
        if game_id not in games:
            return False
        
        games[game_id]['status'] = new_status
        
        with open(GAME_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(games, f, indent=4, ensure_ascii=False)
        
        return True