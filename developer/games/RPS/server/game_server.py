import socket
import argparse
import threading
import json
import time

# 簡單的通訊協定 (Length-Prefix)，避免黏包
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

def handle_game(p1_sock, p2_sock):
    """處理一局遊戲邏輯"""
    global results
    try:
        # 1. 通知雙方遊戲開始
        start_msg = {"event": "start", "msg": "遊戲開始！請出拳 (R/P/S)"}
        send_json(p1_sock, start_msg)
        send_json(p2_sock, start_msg)

        # 2. 接收出拳 (簡單起見，這裡依序接收，實際上可以用 Thread 平行接收)
        # 為了公平，我們用 Thread 同時等待
        moves = {}
        def get_move(player_id, sock):
            resp = recv_json(sock)
            if resp:
                moves[player_id] = resp.get('move')

        t1 = threading.Thread(target=get_move, args=("p1", p1_sock))
        t2 = threading.Thread(target=get_move, args=("p2", p2_sock))
        t1.start(); t2.start()
        t1.join(); t2.join()

        m1 = moves.get("p1")
        m2 = moves.get("p2")

        # 3. 判定勝負
        result_p1 = "Draw"
        result_p2 = "Draw"

        if m1 and m2:
            if m1 == m2:
                pass # Draw
            elif (m1 == 'R' and m2 == 'S') or \
                 (m1 == 'S' and m2 == 'P') or \
                 (m1 == 'P' and m2 == 'R'):
                result_p1 = "Win"
                result_p2 = "Lose"
            else:
                result_p1 = "Lose"
                result_p2 = "Win"
        elif m1:
            result_p1 = "Win" # 對方斷線
            result_p2 = "Lose"
        else:
            result_p1 = "Lose" # 自己斷線
            result_p2 = "Win"

        # 4. 發送結果
        try:
            send_json(p1_sock, {"event": "end", "result": result_p1, "opp_move": m2})
        except Exception as e:
            print(f"[Error] Send to p1 failed: {e}")
        try:
            send_json(p2_sock, {"event": "end", "result": result_p2, "opp_move": m1})
        except Exception as e:
            print(f"[Error] Send to p2 failed: {e}")
            
        print(f"[Game] Result: P1({m1}) vs P2({m2})")
        if result_p1 == "Win":
            results = "Player 1 Wins"
        elif result_p2 == "Win":
            results = "Player 2 Wins"
        else:
            results = "Draw"
    except Exception as e:
        print(f"[Error] Game logic error: {e}")
    finally:
        time.sleep(1) # 等一下確保訊息傳送
        p1_sock.close()
        p2_sock.close()

def main():
    # 接收平台傳來的參數
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True, help='Game Server Port')
    parser.add_argument('--lobby_ip', type=str, default='127.0.0.1', help='Lobby Server IP')
    parser.add_argument('--lobby_port', type=int, default=9000, help='Lobby Server Port')
    parser.add_argument('--room_id', type=int, required=True, help='Room ID')
    parser.add_argument('--players', type=int, default=2, help='Number of players')

    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 綁定 0.0.0.0 讓外部 Client 可以連入
    server.bind(('0.0.0.0', args.port))
    server.listen(2)
    
    print(f"[Game Server] Listening on port {args.port}...")
    global results
    clients = []
    # 等待兩人加入
    while len(clients) < 2:
        conn, addr = server.accept()
        print(f"[Game Server] Player {len(clients)+1} connected from {addr}")
        clients.append(conn)
        # 告訴玩家你是第幾位
        send_json(conn, {"event": "info", "msg": f"You are Player {len(clients)}"})

    print("[Game Server] Both players connected. Starting game...")
    handle_game(clients[0], clients[1])
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