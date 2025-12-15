import socket
import json
import argparse
import threading
import tkinter as tk
from tkinter import messagebox

# --- 網路工具 ---
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

# --- GUI 應用程式 ---
class TicTacToeApp:
    def __init__(self, ip, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ip, port))
        
        self.player_id = None
        self.symbol = None
        self.my_turn = False
        self.buttons = []
        
        # 建立視窗
        self.root = tk.Tk()
        self.root.title("連線中...")
        self.root.geometry("300x350")
        
        self.status_label = tk.Label(self.root, text="等待對手...", font=("Arial", 14))
        self.status_label.pack(pady=10)
        
        frame = tk.Frame(self.root)
        frame.pack()
        
        # 建立 3x3 按鈕
        for i in range(9):
            btn = tk.Button(frame, text="", font=("Arial", 20), width=5, height=2,
                            command=lambda idx=i: self.on_click(idx))
            btn.grid(row=i//3, column=i%3)
            self.buttons.append(btn)
            
        # 啟動接收執行緒
        threading.Thread(target=self.network_loop, daemon=True).start()
        
        self.root.mainloop()

    def on_click(self, idx):
        if self.my_turn and self.buttons[idx]['text'] == "":
            send_json(self.sock, {"cmd": "move", "index": idx})

    def update_gui(self, data):
        # 這是從子執行緒呼叫的，使用 after 把工作排程回主執行緒
        # 但 tkinter 對簡單屬性修改通常是 thread-safe 的，這裡簡化處理
        board = data['board']
        turn = data['turn']
        winner = data.get('winner')
        
        # 更新盤面
        for i, val in enumerate(board):
            self.buttons[i].config(text=val, state="disabled" if val else "normal")
        
        # 更新狀態文字
        if winner:
            if winner == "Draw":
                msg = "遊戲平手！"
            elif winner == self.symbol:
                msg = "你贏了！ 🎉"
            else:
                msg = "你輸了... 😢"
            self.status_label.config(text=msg, fg="red")
            messagebox.showinfo("遊戲結束", msg)
            self.root.quit()
        else:
            self.my_turn = (turn == self.player_id)
            if self.my_turn:
                self.status_label.config(text=f"輪到你了 ({self.symbol})", fg="green")
            else:
                self.status_label.config(text="對手思考中...", fg="black")

    def network_loop(self):
        try:
            while True:
                msg = recv_json(self.sock)
                if not msg: break
                
                cmd = msg['cmd']
                if cmd == 'init':
                    self.player_id = msg['player_id']
                    self.symbol = msg['symbol']
                    self.root.title(f"我是玩家 {self.symbol}")
                    
                elif cmd == 'start':
                    # 根據這局誰先手更新狀態
                    self.update_gui({"board": [""]*9, "turn": msg['turn']})
                    
                elif cmd == 'update':
                    self.update_gui(msg)
                    
        except Exception as e:
            print(f"Network error: {e}")
        finally:
            self.sock.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    
    TicTacToeApp(args.ip, args.port)