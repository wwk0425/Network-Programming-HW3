import socket
import json
import argparse
import threading
import tkinter as tk
from tkinter import messagebox

# ... (send_json, recv_json 保持不變) ...
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

class GuessGameApp:
    def __init__(self, ip, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ip, port))
        
        self.my_pid = 0
        
        # GUI Setup
        self.root = tk.Tk()
        self.root.title("終極密碼 (輪流版)")
        self.root.geometry("400x550")
        
        # 狀態區
        self.status_lbl = tk.Label(self.root, text="連線中...", font=("Arial", 16))
        self.status_lbl.pack(pady=10)

        # 顯示現在輪到誰
        self.turn_lbl = tk.Label(self.root, text="", font=("Arial", 12, "bold"), fg="blue")
        self.turn_lbl.pack(pady=5)
        
        # 歷史紀錄區
        self.history_list = tk.Listbox(self.root, font=("Courier", 12))
        self.history_list.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 輸入區
        input_frame = tk.Frame(self.root)
        input_frame.pack(pady=10)
        
        self.entry = tk.Entry(input_frame, font=("Arial", 14), width=10)
        self.entry.pack(side=tk.LEFT, padx=5)
        self.entry.bind('<Return>', self.submit_guess)
        
        self.btn = tk.Button(input_frame, text="猜！", command=self.submit_guess)
        self.btn.pack(side=tk.LEFT)
        
        # 預設禁用，等輪到我再開
        self.disable_input()
        
        threading.Thread(target=self.network_loop, daemon=True).start()
        self.root.mainloop()
        
    def disable_input(self):
        self.entry.config(state='disabled')
        self.btn.config(state='disabled')

    def enable_input(self):
        self.entry.config(state='normal')
        self.btn.config(state='normal')
        self.entry.focus() # 自動聚焦輸入框，方便打字

    def submit_guess(self, event=None):
        val = self.entry.get()
        if val.isdigit():
            send_json(self.sock, {"cmd": "guess", "number": val})
            self.entry.delete(0, tk.END)
            # 送出後馬上鎖定，防止連點
            self.disable_input()
            
    def network_loop(self):
        try:
            while True:
                msg = recv_json(self.sock)
                if not msg: break
                
                cmd = msg['cmd']
                
                if cmd == 'init':
                    self.my_pid = msg['player_id']
                    self.root.title(f"我是玩家 {self.my_pid}")
                    
                elif cmd == 'waiting_status':
                    cur = msg['current']
                    tot = msg['total']
                    self.status_lbl.config(text=f"等待玩家 ({cur}/{tot})...")
                    
                elif cmd == 'start':
                    turn_pid = msg['turn']
                    self.status_lbl.config(text="遊戲開始！請猜 1-100", fg="black")
                    self.history_list.insert(tk.END, ">>> 遊戲開始！ <<<")
                    
                    # === 判斷是否輪到我 ===
                    self.update_turn_ui(turn_pid)

                elif cmd == 'guess_result':
                    pid = msg['player_id']
                    num = msg['guess']
                    res = msg['result'] 
                    winner = msg.get('winner')
                    next_turn = msg.get('next_turn') # 取得下一位
                    
                    # 顯示結果
                    display_text = f"P{pid} 猜了 {num} => {res}"
                    self.history_list.insert(tk.END, display_text)
                    self.history_list.see(tk.END)
                    
                    if winner:
                        self.disable_input()
                        self.turn_lbl.config(text="遊戲結束")
                        if winner == self.my_pid:
                            self.status_lbl.config(text="恭喜你猜對了！ 🏆", fg="red")
                            messagebox.showinfo("勝利", "你是終極密碼之王！")
                        else:
                            self.status_lbl.config(text=f"玩家 {winner} 贏了...", fg="gray")
                            messagebox.showinfo("結束", f"玩家 {winner} 猜對了 {num}")
                        self.root.quit()
                    else:
                        # === 遊戲繼續，更新輪次 ===
                        self.update_turn_ui(next_turn)
                
                elif cmd == 'error':
                    messagebox.showerror("錯誤", msg['msg'])

        except Exception as e:
            print(f"Error: {e}")
        finally:
            self.sock.close()

    def update_turn_ui(self, turn_pid):
        """
        根據現在是誰的回合來更新 UI
        """
        if turn_pid == self.my_pid:
            self.turn_lbl.config(text="現在是：你的回合！", fg="green")
            self.enable_input()
        else:
            self.turn_lbl.config(text=f"現在是：玩家 {turn_pid} 的回合", fg="red")
            self.disable_input()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    GuessGameApp(args.ip, args.port)