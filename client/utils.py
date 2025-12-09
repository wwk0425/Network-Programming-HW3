import json
import os
import struct

def send_json(sock, data_dict):
    """
    將 Python Dict 轉為 JSON -> 加上長度 Header -> 發送
    """
    # 1. 序列化: Dict -> JSON String -> Bytes
    json_str = json.dumps(data_dict)
    msg_bytes = json_str.encode('utf-8')
    
    # 2. 計算長度: 取得 bytes 的長度
    msg_len = len(msg_bytes)
    
    # 3. 打包 Header: '!I' 代表 Network byte order (Big-endian), Unsigned Int (4 bytes)
    header = struct.pack('!I', msg_len)
    
    # 4. 發送: Header + Body
    sock.sendall(header + msg_bytes)


def recv_json(sock):
    """
    接收 4 bytes Header -> 讀取對應長度 Body -> 解析 JSON 回傳 Dict
    若連線中斷則回傳 None
    """
    # 1. 先讀取 4 bytes (Header)
    header = recvall(sock, 4)
    if not header:
        return None # 連線已關閉
        
    # 2. 解包 Header 取得內容長度
    msg_len = struct.unpack('!I', header)[0]
    
    # 3. 根據長度讀取完整的 Body
    body_bytes = recvall(sock, msg_len)
    if not body_bytes:
        return None # 讀取 Body 途中發生錯誤或斷線
        
    # 4. 反序列化: Bytes -> JSON String -> Dict
    try:
        json_str = body_bytes.decode('utf-8')
        return json.loads(json_str)
    except json.JSONDecodeError:
        print("[Error] Received invalid JSON")
        return None

def recvall(sock, n):
    """
    輔助函式: 確保一定讀滿 n 個 bytes 才會 return
    解決 TCP 斷包問題 (例如一次只收到半個 JSON 的情況)
    """
    data = b''
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None # 對方關閉了連線
            data += packet
        except ConnectionResetError:
            return None
    return data

def recv_file(sock, save_dir):
    """
    流程：
    1. 接收 JSON Header
    2. 解析檔案大小
    3. 循環接收 Binary 直到收滿大小
    4. 存檔
    """
    # 1. 等待 Header
    header = recv_json(sock)
    if not header or header.get('status') != 'ok':
        print(f"[Error] Download failed: {header.get('msg')}")
        return None

    filename = header['filename']
    filesize = header['size']
    save_path = os.path.join(save_dir, filename)

    print(f"[Download] Receiving {filename} ({filesize} bytes)...")

    # 2. 接收檔案內容
    received_size = 0
    with open(save_path, 'wb') as f:
        while received_size < filesize:
            # 計算還剩多少沒收
            remaining = filesize - received_size
            # 這次最多收 4096 或 剩下的量
            chunk_size = 4096 if remaining > 4096 else remaining
            
            chunk = sock.recv(chunk_size)
            if not chunk:
                break # 斷線保護
            
            f.write(chunk)
            received_size += len(chunk)

    print(f"[Download] Saved to {save_path}")
    return save_path