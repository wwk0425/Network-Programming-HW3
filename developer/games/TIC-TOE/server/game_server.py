import socket
import threading
import json
import argparse
import time

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

# 遊戲狀態
board = [""] * 9
players = [] # [(conn, addr), ...]
current_turn = 0 # 0 for Player 1 (X), 1 for Player 2 (O)
game_over = False

def check_winner():
    wins = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
    for a, b, c in wins:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    if "" not in board:
        return "Draw"
    return None

def broadcast(data):
    for p in players:
        try:
            send_json(p[0], data)
        except:
            pass

def handle_client(conn, player_id):
    global current_turn, game_over, results
    try:
        while not game_over:
            msg = recv_json(conn)
            if not msg: break
            
            if msg['cmd'] == 'move':
                idx = msg['index']
                # 檢查是否合法的移動
                if board[idx] == "" and player_id == current_turn and not game_over:
                    # 更新盤面
                    symbol = "X" if player_id == 0 else "O"
                    board[idx] = symbol
                    
                    # 檢查勝負
                    winner = check_winner()
                    
                    # 換手
                    current_turn = 1 - current_turn
                    
                    # 廣播新狀態
                    update_msg = {
                        "cmd": "update",
                        "board": board,
                        "turn": current_turn,
                        "winner": winner
                    }
                    broadcast(update_msg)
                    
                    if winner:
                        if winner == "Draw":
                            results = "Draw"
                        elif winner == "X":
                            results = "Player 1 Wins"
                        else:
                            results = "Player 2 Wins"
                        game_over = True
    except Exception as e:
        print(f"Player {player_id} error: {e}")
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--lobby_ip', type=str, default='127.0.0.1', help='Lobby Server IP')
    parser.add_argument('--lobby_port', type=int, default=9000, help='Lobby Server Port')
    parser.add_argument('--room_id', type=int, required=True, help='Room ID')
    parser.add_argument('--players', type=int, required=True, help='Number of Players')
    args = parser.parse_args()

    global results
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', args.port))
    server.listen(2)
    print(f"[TicTacToe Server] Listening on {args.port}")

    # 等待兩位玩家
    while len(players) < 2:
        conn, addr = server.accept()
        pid = len(players)
        players.append((conn, addr))
        
        # 告訴玩家他是誰
        send_json(conn, {
            "cmd": "init",
            "player_id": pid,
            "symbol": "X" if pid == 0 else "O"
        })
        print(f"Player {pid} connected.")

    # 開始遊戲
    broadcast({"cmd": "start", "turn": 0})
    
    # 啟動執行緒處理兩位玩家
    t1 = threading.Thread(target=handle_client, args=(players[0][0], 0))
    t2 = threading.Thread(target=handle_client, args=(players[1][0], 1))
    t1.start(); t2.start()
    t1.join(); t2.join()

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