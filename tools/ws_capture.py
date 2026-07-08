import socket, base64, threading, struct, hashlib, sys

OPCODES = {0: "continuation", 1: "text", 2: "binary",
           8: "close", 9: "ping", 10: "pong"}

def parse_frame(sock):
    hdr = sock.recv(2)
    if len(hdr) < 2:
        return None
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0f
    masked = b2 & 0x80
    plen = b2 & 0x7f
    if plen == 126:
        plen = struct.unpack("!H", sock.recv(2))[0]
    elif plen == 127:
        plen = struct.unpack("!Q", sock.recv(8))[0]
    mask = sock.recv(4) if masked else b""
    data = b""
    while len(data) < plen:
        chunk = sock.recv(plen - len(data))
        if not chunk:
            break
        data += chunk
    if masked:
        data = bytes(data[i] ^ mask[i % 4] for i in range(len(data)))
    return opcode, data

def handle(conn, addr):
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = conn.recv(4096)
        if not d:
            conn.close(); return
        buf += d
    req = buf.split(b"\r\n")
    print(f"=== UPGRADE from {addr} ===", flush=True)
    key = ""
    proto = ""
    for line in req:
        print("  " + line.decode("latin1"), flush=True)
        lw = line.lower()
        if lw.startswith(b"sec-websocket-key:"):
            key = line.split(b":", 1)[1].strip().decode()
        if lw.startswith(b"sec-websocket-protocol:"):
            proto = line.split(b":", 1)[1].strip().decode()
    if key:
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n")
        if proto:
            resp += f"Sec-WebSocket-Protocol: {proto.split(',')[0].strip()}\r\n"
            if "bearer." in proto:
                jwt = proto.split("bearer.", 1)[1].strip()
                parts = jwt.split(".")
                if len(parts) >= 2:
                    pad = "=" * (-len(parts[1]) % 4)
                    try:
                        payload = base64.urlsafe_b64decode(parts[1] + pad)
                        print(f"  JWT PAYLOAD: {payload.decode('latin1')}", flush=True)
                    except Exception as e:
                        print(f"  JWT decode error: {e}", flush=True)
        resp += "\r\n"
        conn.sendall(resp.encode())
        print("=== HANDSHAKE DONE ===", flush=True)
    else:
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n"); conn.close(); return
    while True:
        f = parse_frame(conn)
        if f is None:
            break
        opcode, data = f
        print(f"FRAME op={OPCODES.get(opcode, opcode)} len={len(data)} "
              f"payload={data.hex()}", flush=True)
        if opcode == 9:
            conn.sendall(struct.pack("!BB", 0x8a, len(data)) + data)
        elif opcode == 8:
            break
    conn.close()

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 22450
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port)); s.listen(5)
    print(f"capture server on :{port}", flush=True)
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c, a), daemon=True).start()

if __name__ == "__main__":
    main()
