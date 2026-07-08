"""
Integration test: verify reverse tunnel handles sequential client connections.

Flow:
  external client -> wstunnel server -> wsburrow -> echo server
  The echo server responds with all data received in THIS connection.

Tests that each new client gets a fresh connection, not a resumed session.
"""

import socket, time, sys, subprocess, os, signal, threading

# Configuration
WSTUNNEL_PORT = 22560
BIND_PORT = 22561
ECHO_PORT = 22552

def start_echo_server():
    """Echo server that responds per-message using delimiter protocol.
    
    Reads until b'\n---END---\n', then responds with ECHO:<hex of data>:END
    This allows multiple messages per connection without closing.
    """
    DELIM = b"\n---END---\n"
    
    def handle(conn, addr):
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # Process complete messages
                while DELIM in buf:
                    msg, buf = buf.split(DELIM, 1)
                    response = f"ECHO:{msg.hex()}:END".encode()
                    conn.sendall(response)
            except:
                break
        conn.close()
    
    def server():
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', ECHO_PORT))
        s.listen(5)
        while True:
            c, a = s.accept()
            threading.Thread(target=handle, args=(c, a), daemon=True).start()
    
    t = threading.Thread(target=server, daemon=True)
    t.start()
    time.sleep(0.3)
    return t

def start_wstunnel_server():
    proc = subprocess.Popen(
        ['/project/wstunnel-10.5.5/bin/wstunnel', 'server',
         f'ws://0.0.0.0:{WSTUNNEL_PORT}',
         '--websocket-mask-frame',
         '--log-lvl', 'TRACE'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    # Read stdout (merged with stderr) in a thread
    def log_reader():
        with open('/tmp/wstunnel_seq.log', 'w') as f:
            for line in iter(proc.stdout.readline, b''):
                f.write(line.decode())
                f.flush()
    threading.Thread(target=log_reader, daemon=True).start()
    time.sleep(1)
    return proc

def start_wsburrow():
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = '/project/wsburrow/build'
    proc = subprocess.Popen(
        ['/project/wsburrow/build/wsburrow',
         f'-R', f'tcp://{BIND_PORT}:localhost:{ECHO_PORT}',
         # Note: ECHO_PORT is both the bind target and the echo server port
         f'ws://localhost:{WSTUNNEL_PORT}',
         '--pool-size', '1', '--ping-interval', '5'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
    )
    # Wait for wsburrow to connect and server to start listening
    for i in range(20):
        try:
            s = socket.socket()
            s.settimeout(1)
            s.connect(('127.0.0.1', BIND_PORT))
            s.close()
            break
        except:
            time.sleep(0.5)
    return proc

def connect_client(client_id, data):
    """Connect an external client, send data, read response, return response.
    
    Uses a delimiter-based protocol: sends data followed by b'\n---END---\n'
    to signal end-of-message without closing the connection.
    The echo server responds with b'ECHO:<hex>:END' when it sees the delimiter.
    """
    try:
        s = socket.socket()
        s.settimeout(15)
        s.connect(('127.0.0.1', BIND_PORT))
        # Send data with end-of-message marker
        s.sendall(data + b"\n---END---\n")
        # Read response (don't shutdown, just wait for data)
        response = b""
        end = time.time() + 10
        while time.time() < end:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b":END" in response:
                    break
            except socket.timeout:
                break
        s.close()
        return response
    except Exception as e:
        return f"ERROR:{e}".encode()

def main():
    print("=== Sequential Client Connection Test ===")
    print()
    
    # Start services
    print("1. Starting echo server...")
    start_echo_server()
    
    print("2. Starting wstunnel server...")
    wstunnel = start_wstunnel_server()
    
    print("3. Starting wsburrow...")
    wsburrow = start_wsburrow()
    
    try:
        # Client 1
        print("\n4. Client 1 connecting, sending 'HELLO1'...")
        resp1 = connect_client(1, b"HELLO1")
        print(f"   Response 1: {resp1}")
        
        # Wait a moment
        time.sleep(1)
        
        # Client 2
        print("\n5. Client 2 connecting, sending 'HELLO2'...")
        resp2 = connect_client(2, b"HELLO2")
        print(f"   Response 2: {resp2}")
        
        # Show server log for lifecycle analysis
        print("\n=== SERVER LOG (tunnel lifecycle) ===")
        try:
            with open('/tmp/wstunnel_seq.log') as f:
                for line in f:
                    if 'Closing' in line or 'connected to' in line or 'Accepting' in line or 'Incomplete' in line:
                        print(f"  {line.strip()}")
        except:
            pass
        
        # Analysis
        print("\n=== ANALYSIS ===")
        hex1 = b"HELLO1".hex().encode()  # b"48454c4c4f31"
        hex2 = b"HELLO2".hex().encode()  # b"48454c4c4f32"
        
        if resp1 and resp2:
            if hex1 in resp1:
                print(f"✅ Client 1: received correct echo of 'HELLO1'")
            else:
                print(f"❌ Client 1: unexpected response: {resp1}")
            
            if hex2 in resp2:
                print(f"✅ Client 2: received correct echo of 'HELLO2'")
            else:
                print(f"❌ Client 2: unexpected response: {resp2}")
            
            # Check for session resume bug
            if hex1 in resp2:
                print("\n❌ BUG DETECTED: Client 2 received Client 1's data!")
                print("   The server is RESUMING the old session instead of")
                print("   creating a new connection for each client.")
            elif hex2 in resp2:
                print("\n✅ Client 2 received ONLY its own data - session is fresh.")
        else:
            print("\n❌ One or both clients failed to connect.")
    
    finally:
        print("\n6. Cleaning up...")
        wsburrow.terminate()
        wstunnel.terminate()
        wsburrow.wait()
        wstunnel.wait()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()
