import socket
import threading
import json
import argparse
import random
import time

# ... (send_json, recv_json 函式保持不變) ...
def send_json(sock, data):
    msg = json.dumps(data).encode('utf-8')
    sock.sendall(len(msg).to_bytes(4, byteorder='big') + msg)

def recv_json(sock):
    try:
        header = sock.recv(4)
        if not header: return None
        length = int.from_bytes(header, byteorder='big')
        body = sock.recv(length)
        return json.loads(body.decode('utf-8'))
    except:
        return None

target_number = 0
players = []     # 儲存連線 [(conn, addr, pid), ...]
game_over = False
lock = threading.Lock()

# === 新增：記錄現在輪到誰 (儲存的是 players 列表的 index) ===
current_turn_index = 0 

def broadcast(data):
    for p in players:
        try:
            send_json(p[0], data)
        except: pass

def handle_client(conn, pid):
    global game_over, current_turn_index
    global results
    try:
        while not game_over:
            msg = recv_json(conn)
            if not msg: break
            
            if msg['cmd'] == 'guess':
                # === 關鍵修改 1：檢查是否輪到這個人 ===
                # 我們用 players[current_turn_index] 來判斷現在是誰的回合
                # pid 是從 1 開始，列表 index 是從 0 開始，所以要對應一下
                
                expected_pid = players[current_turn_index][2]
                
                if pid != expected_pid:
                    # 如果不是他的回合，傳送錯誤訊息 (或是直接忽略)
                    send_json(conn, {"cmd": "error", "msg": "還沒輪到你！"})
                    continue

                guess = int(msg['number'])
                result = ""
                winner = None
                
                with lock:
                    if game_over: break
                    
                    if guess == target_number:
                        result = "Correct"
                        winner = pid
                        game_over = True
                        results = f"Player {winner} Wins"
                    elif guess < target_number:
                        result = "Too Small"
                        # === 關鍵修改 2：猜錯了，換下一位 ===
                        current_turn_index = (current_turn_index + 1) % len(players)
                    else:
                        result = "Too Big"
                        # === 關鍵修改 2：猜錯了，換下一位 ===
                        current_turn_index = (current_turn_index + 1) % len(players)
                    
                    # 取得下一位玩家的 ID
                    next_pid = players[current_turn_index][2]

                    # 廣播結果，並且告訴大家 "下一個是誰 (next_turn)"
                    broadcast({
                        "cmd": "guess_result",
                        "player_id": pid,
                        "guess": guess,
                        "result": result,
                        "winner": winner,
                        "next_turn": next_pid  # <--- 告訴 Client 更新 UI
                    })
                    
    except Exception as e:
        print(f"Error {pid}: {e}")
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--lobby_ip', type=str, default='127.0.0.1', help='Lobby Server IP')
    parser.add_argument('--lobby_port', type=int, default=9000, help='Lobby Server Port')
    parser.add_argument('--room_id', type=int, required=True, help='Room ID')
    parser.add_argument('--players', type=int, default=3) 
    
    # 接收 Lobby 傳來的額外參數 (避免 Crash)
    args, unknown = parser.parse_known_args()
    global results
    global target_number
    target_number = random.randint(1, 100)
    print(f"[GuessServer] Target is {target_number}, waiting for {args.players} players...")
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', args.port))
    server.listen(5)
    
    # 等待足夠人數
    while len(players) < args.players:
        conn, addr = server.accept()
        pid = len(players) + 1 
        # 將 pid 也存入 tuple: (conn, addr, pid)
        players.append((conn, addr, pid))
        
        send_json(conn, {"cmd": "init", "player_id": pid})
        print(f"Player {pid} joined.")
        
        broadcast({
            "cmd": "waiting_status", 
            "current": len(players), 
            "total": args.players
        })

    print("Game Start!")
    
    # 遊戲開始時，告訴大家現在是 Player 1 (index 0) 的回合
    first_player_pid = players[0][2]
    broadcast({
        "cmd": "start", 
        "turn": first_player_pid
    })
    
    threads = []
    for p in players:
        conn = p[0]
        pid = p[2]
        t = threading.Thread(target=handle_client, args=(conn, pid))
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()
    #要做回傳結束給lobby_server的動作
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((args.lobby_ip, args.lobby_port))
        print(f"[System] 已連線至 Player Server ({args.lobby_ip}:{args.lobby_port})")
    except Exception as e:
        print(f"[Error] 無法連線至 Server: {e}")
        return
    
    # 傳送結束訊息給 Lobby Server
    send_json(sock, {"cmd": "end_game", "room_id": args.room_id, "result": results})
    sock.close()

    server.close()
    print("[Game Server] Closed.")

if __name__ == "__main__":
    main()