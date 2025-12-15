import socket
import argparse
import json
import sys

# 同樣的簡易通訊協定
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

def main():
    # 接收平台傳來的 IP 和 Port
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', type=str, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()

    print(f"=== 剪刀石頭布 Client ===")
    print(f"正在連線至 Game Server {args.ip}:{args.port} ...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((args.ip, args.port))
        print("連線成功！等待對手...")

        while True:
            msg = recv_json(sock)
            if not msg:
                print("Server 斷線。")
                break
            
            event = msg.get('event')

            if event == 'info':
                print(f"[系統] {msg.get('msg')}")

            elif event == 'start':
                print(f"\n>>> {msg.get('msg')} <<<")
                while True:
                    move = input("請輸入 (R=石頭, P=布, S=剪刀): ").upper().strip()
                    if move in ['R', 'P', 'S']:
                        send_json(sock, {"move": move})
                        print("出拳成功，等待結果...")
                        break
                    else:
                        print("輸入錯誤，請重新輸入。")

            elif event == 'end':
                result = msg.get('result')
                opp = msg.get('opp_move')
                print(f"\n==========================")
                print(f"對手出: {opp}")
                print(f"結果: {result}")
                print(f"==========================")
                break
                
    except Exception as e:
        print(f"[Error] {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    main()