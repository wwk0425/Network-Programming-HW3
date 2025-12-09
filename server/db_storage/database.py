import json
import threading
import os
import time

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
            "name": manifest_data.get("name", game_id),
            "version": manifest_data.get("version", "1.0"),
            "description": manifest_data.get("description", ""),
            "min_players": manifest_data.get("min_players", 1),
            "max_players": manifest_data.get("max_players", 4),
            "server_exe": manifest_data.get("server_exe"), # 重要：啟動時需要
            "client_exe": manifest_data.get("client_exe"), # 重要：下載時需要
            
            # 系統維護欄位
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
        data[group][username] = password
        
        with open(USER_DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True

def verify_login(username, password, role="player"):
    with user_lock:
        with open(USER_DB_FILE, 'r') as f:
            data = json.load(f)
            
        group = "players" if role == "player" else "developers"
        
        # 檢查帳密
        if username in data[group] and data[group][username] == password:
            return True
        return False
    
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
            "players": [host_name] # 只存名字 (String)，不存 Socket
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
    玩家離開或斷線。如果房主離開，回傳 'room_closed'，否則回傳 'player_left'
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
        
        # 檢查: 如果沒人了，或房主離開 -> 刪除房間
        if not room['players'] or room['host'] == player_name:
            del rooms[rid]
            result = "room_closed"
        else:
            # 寫回更新後的房間資料
             pass # Python 的 dict 是 reference，只要最後 dump rooms 即可
             
        with open(ROOM_DB_FILE, 'w') as f:
            json.dump(rooms, f, indent=4)
            
        return result