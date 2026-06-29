"""Integration tests for wsburrow against wstunnel server.

Usage:
    python3 tests/test_integration.py [--wsburrow PATH] [--wstunnel PATH] [--verbose]

Environment variables:
    WSBURROW_BIN: path to wsburrow binary (default: build/wsburrow)
    WSTUNNEL_BIN: path to wstunnel binary (default: ../wstunnel-10.5.5/bin/wstunnel)
"""

import subprocess
import socket
import time
import sys
import os
import signal
import threading


WSBURROW = os.environ.get(
    "WSBURROW_BIN",
    os.path.join(os.path.dirname(__file__) or ".", "..", "build", "wsburrow"),
)
WSTUNNEL = os.environ.get(
    "WSTUNNEL_BIN",
    os.path.join(
        os.path.dirname(__file__) or ".",
        "..",
        "..",
        "wstunnel-10.5.5",
        "bin",
        "wstunnel",
    ),
)

WS_PORT = 22345
HTTP_PORT = 28080
TUNNEL_PORT = 22346
TUNNEL_PORT2 = 22347
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def log(msg):
    if VERBOSE:
        print(f"[inttest] {msg}", flush=True)


class ProcManager:
    def __init__(self):
        self.procs = []

    def start(self, args, **kwargs):
        log(f"Starting: {' '.join(args)}")
        p = subprocess.Popen(args, **kwargs)
        self.procs.append(p)
        return p

    def kill_all(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.kill_all()


def tcp_send_recv(host, port, data, timeout=5):
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, port))
    s.sendall(data)
    time.sleep(1.5)
    chunks = []
    while True:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        except socket.timeout:
            break
    s.close()
    return b"".join(chunks)


def serve_echo(host, port, stop):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    srv.settimeout(1)
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        th = threading.Thread(target=handle_echo, args=(conn,), daemon=True)
        th.start()
    srv.close()


def handle_echo(conn):
    with conn:
        conn.settimeout(1)
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                conn.sendall(data)
        except (socket.timeout, ConnectionError):
            pass


def serve_http(host, port, stop):
    """Serves a minimal HTTP response on any request."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    srv.settimeout(1)
    while not stop.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        th = threading.Thread(target=handle_http, args=(conn,), daemon=True)
        th.start()
    srv.close()


def handle_http(conn):
    with conn:
        conn.settimeout(3)
        try:
            data = conn.recv(4096)
            if data:
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 6\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"\r\n"
                    b"hello\n"
                )
                conn.sendall(response)
        except (socket.timeout, ConnectionError):
            pass


def test_basic_roundtrip(manager):
    """Test basic TCP data round trip through the tunnel."""
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    manager.start(
        [WSTUNNEL, "server", f"ws://0.0.0.0:{WS_PORT}", "--websocket-mask-frame",
         "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    manager.start(
        [WSBURROW, "-R", f"tcp://{TUNNEL_PORT}:localhost:{HTTP_PORT}",
         f"ws://localhost:{WS_PORT}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    data = tcp_send_recv("localhost", TUNNEL_PORT, b"GET / HTTP/1.0\r\n\r\n")
    assert b"hello" in data, f"Expected 'hello' in response, got: {data}"
    log("PASS: test_basic_roundtrip")
    return True


def test_large_data(manager):
    """Test that larger payloads (multiple TCP segments) go through correctly."""
    stop = threading.Event()
    srv = threading.Thread(target=serve_echo, args=("0.0.0.0", HTTP_PORT + 1, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    manager.start(
        [WSTUNNEL, "server", f"ws://0.0.0.0:{WS_PORT + 1}", "--websocket-mask-frame",
         "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    manager.start(
        [WSBURROW, "-R", f"tcp://{TUNNEL_PORT + 1}:localhost:{HTTP_PORT + 1}",
         f"ws://localhost:{WS_PORT + 1}", "--pool-size", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    payload = b"x" * 50000
    echoed = tcp_send_recv("localhost", TUNNEL_PORT + 1, payload, timeout=8)
    assert len(echoed) == len(payload), f"Expected {len(payload)} bytes, got {len(echoed)}"
    assert echoed == payload, "Payload mismatch"
    log("PASS: test_large_data")
    return True


def test_pool_size(manager):
    """Check that --pool-size creates the expected number of WS connections by making requests from multiple clients."""
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT + 2, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    manager.start(
        [WSTUNNEL, "server", f"ws://0.0.0.0:{WS_PORT + 2}", "--websocket-mask-frame",
         "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    manager.start(
        [WSBURROW, "-R", f"tcp://{TUNNEL_PORT + 2}:localhost:{HTTP_PORT + 2}",
         f"ws://localhost:{WS_PORT + 2}", "--pool-size", "2"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    for i in range(4):
        data = tcp_send_recv("localhost", TUNNEL_PORT + 2, b"GET / HTTP/1.0\r\n\r\n")
        assert b"hello" in data, f"Attempt {i}: Expected 'hello', got: {data}"
    log("PASS: test_pool_size")
    return True


def test_ping_keepalive(manager):
    """Verify --ping-interval keeps connections alive (connection stays up after idling)."""
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT + 3, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    manager.start(
        [WSTUNNEL, "server", f"ws://0.0.0.0:{WS_PORT + 3}", "--websocket-mask-frame",
         "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    manager.start(
        [WSBURROW, "-R", f"tcp://{TUNNEL_PORT + 3}:localhost:{HTTP_PORT + 3}",
         f"ws://localhost:{WS_PORT + 3}", "--ping-interval", "3", "--pool-size", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    # idle for 7 seconds (2+ ping cycles)
    time.sleep(7)

    data = tcp_send_recv("localhost", TUNNEL_PORT + 3, b"GET / HTTP/1.0\r\n\r\n")
    assert b"hello" in data, f"After idle, expected 'hello', got: {data}"
    log("PASS: test_ping_keepalive")
    return True


def test_multiple_tunnels(manager):
    """Test two -R tunnels in one wsburrow instance."""
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT + 4, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    manager.start(
        [WSTUNNEL, "server", f"ws://0.0.0.0:{WS_PORT + 4}", "--websocket-mask-frame",
         "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    manager.start(
        [WSBURROW, "-R", f"tcp://{TUNNEL_PORT + 4}:localhost:{HTTP_PORT + 4}",
         "-R", f"tcp://{TUNNEL_PORT + 5}:localhost:{HTTP_PORT + 4}",
         f"ws://localhost:{WS_PORT + 4}", "--pool-size", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(5)

    for port in [TUNNEL_PORT + 4, TUNNEL_PORT + 5]:
        data = tcp_send_recv("localhost", port, b"GET / HTTP/1.0\r\n\r\n")
        assert b"hello" in data, f"Tunnel on {port}: Expected 'hello', got: {data}"
    log("PASS: test_multiple_tunnels")
    return True


def test_tls_roundtrip(manager):
    """Test basic roundtrip over wss:// with --insecure."""
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    cert_file = os.path.join(tmpdir, "cert.pem")
    key_file = os.path.join(tmpdir, "key.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key_file,
         "-out", cert_file, "-days", "1", "-nodes",
         "-subj", "/CN=localhost"],
        capture_output=True, check=True,
    )

    base = 20
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT + base, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    wss_port = WS_PORT + base
    manager.start(
        [WSTUNNEL, "server", f"wss://0.0.0.0:{wss_port}", "--websocket-mask-frame",
         "--tls-certificate", cert_file, "--tls-private-key", key_file,
         "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    manager.start(
        [WSBURROW, "-R", f"tcp://{TUNNEL_PORT + base}:localhost:{HTTP_PORT + base}",
         f"wss://localhost:{wss_port}", "--insecure", "--pool-size", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)

    data = tcp_send_recv("localhost", TUNNEL_PORT + base, b"GET / HTTP/1.0\r\n\r\n")
    assert b"hello" in data, f"Expected 'hello' in response, got: {data}"
    shutil.rmtree(tmpdir, ignore_errors=True)
    log("PASS: test_tls_roundtrip")
    return True


def _gen_ca_chain(tmpdir):
    """Generate CA, server cert signed by CA, client cert signed by CA.
    Returns (ca_cert, server_cert, server_key, client_cert, client_key).
    """
    import subprocess as sp

    # CA
    sp.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout",
            os.path.join(tmpdir, "ca-key.pem"), "-out", os.path.join(tmpdir, "ca-cert.pem"),
            "-days", "1", "-nodes", "-subj", "/CN=TestCA"],
           capture_output=True, check=True)

    # Server CSR + cert (use -extfile to force v3; rustls rejects v1 certs)
    sp.run(["openssl", "req", "-newkey", "rsa:2048", "-keyout",
            os.path.join(tmpdir, "srv-key.pem"), "-out", os.path.join(tmpdir, "srv.csr"),
            "-nodes", "-subj", "/CN=localhost"],
           capture_output=True, check=True)
    sp.run(["openssl", "x509", "-req", "-in", os.path.join(tmpdir, "srv.csr"),
            "-CA", os.path.join(tmpdir, "ca-cert.pem"),
            "-CAkey", os.path.join(tmpdir, "ca-key.pem"),
            "-CAcreateserial", "-out", os.path.join(tmpdir, "srv-cert.pem"),
            "-days", "1",
            "-extfile", "/dev/stdin"],
           input=b"basicConstraints = CA:FALSE\nkeyUsage = digitalSignature, keyEncipherment\nextendedKeyUsage = serverAuth\nsubjectAltName = DNS:localhost\n",
           capture_output=True, check=True)

    # Client CSR + cert (CN=v1 to match wstunnel's mTLS upgrade path restriction)
    sp.run(["openssl", "req", "-newkey", "rsa:2048", "-keyout",
            os.path.join(tmpdir, "cli-key.pem"), "-out", os.path.join(tmpdir, "cli.csr"),
            "-nodes", "-subj", "/CN=v1"],
           capture_output=True, check=True)
    sp.run(["openssl", "x509", "-req", "-in", os.path.join(tmpdir, "cli.csr"),
            "-CA", os.path.join(tmpdir, "ca-cert.pem"),
            "-CAkey", os.path.join(tmpdir, "ca-key.pem"),
            "-CAcreateserial", "-out", os.path.join(tmpdir, "cli-cert.pem"),
            "-days", "1",
            "-extfile", "/dev/stdin"],
           input=b"basicConstraints = CA:FALSE\nkeyUsage = digitalSignature, keyEncipherment\nextendedKeyUsage = clientAuth\n",
           capture_output=True, check=True)

    return (os.path.join(tmpdir, "ca-cert.pem"),
            os.path.join(tmpdir, "srv-cert.pem"),
            os.path.join(tmpdir, "srv-key.pem"),
            os.path.join(tmpdir, "cli-cert.pem"),
            os.path.join(tmpdir, "cli-key.pem"))


def test_mtls_roundtrip(manager):
    """Test mTLS: wsburrow presents client cert, server validates."""
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    ca_cert, srv_cert, srv_key, cli_cert, cli_key = _gen_ca_chain(tmpdir)

    base = 40
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT + base, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    wss_port = WS_PORT + base
    tunnel_port = TUNNEL_PORT + base
    log(f"mTLS: wstunnel on {wss_port}, tunnel on {tunnel_port}")
    manager.start(
        [WSTUNNEL, "server", f"wss://0.0.0.0:{wss_port}", "--websocket-mask-frame",
         "--tls-certificate", srv_cert, "--tls-private-key", srv_key,
         "--tls-client-ca-certs", ca_cert, "--log-lvl", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    manager.start(
        [WSBURROW, "-R", f"tcp://{tunnel_port}:localhost:{HTTP_PORT + base}",
         f"wss://localhost:{wss_port}", "--insecure", "--pool-size", "1",
         "--client-cert", cli_cert, "--client-key", cli_key],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4)

    data = tcp_send_recv("localhost", tunnel_port, b"GET / HTTP/1.0\r\n\r\n", timeout=10)
    assert b"hello" in data, f"Expected 'hello' in response, got: {data}"
    shutil.rmtree(tmpdir, ignore_errors=True)
    log("PASS: test_mtls_roundtrip")
    return True


def test_mtls_rejected(manager):
    """Test that wsburrow keeps retrying (not fatal) when server demands client cert but none configured."""
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    ca_cert, srv_cert, srv_key, _cli_cert, _cli_key = _gen_ca_chain(tmpdir)

    base = 41
    stop = threading.Event()
    srv = threading.Thread(target=serve_http, args=("0.0.0.0", HTTP_PORT + base, stop), daemon=True)
    srv.start()
    time.sleep(0.3)

    wss_port = WS_PORT + base
    with ProcManager() as mgr2:
        mgr2.start(
            [WSTUNNEL, "server", f"wss://0.0.0.0:{wss_port}", "--websocket-mask-frame",
             "--tls-certificate", srv_cert, "--tls-private-key", srv_key,
             "--tls-client-ca-certs", ca_cert, "--log-lvl", "error"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(4)

        p = subprocess.Popen(
            [WSBURROW, "-R", f"tcp://{TUNNEL_PORT + base}:localhost:{HTTP_PORT + base}",
             f"wss://localhost:{wss_port}", "--insecure", "--pool-size", "1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(5)
        try:
            ret = p.poll()
            assert ret is None, f"wsburrow should keep retrying, but exited with code {ret}"
            log("wsburrow running (retrying as expected)")
        finally:
            p.terminate()
            p.wait()

    shutil.rmtree(tmpdir, ignore_errors=True)
    log("PASS: test_mtls_rejected")
    return True


def test_invalid_url_exits(manager):
    """Verify wsburrow exits with code 1 on invalid URL."""
    result = subprocess.run(
        [WSBURROW, "-R", "tcp://9999:localhost:9998", "not-a-valid-url"],
        capture_output=True, timeout=5,
    )
    assert result.returncode != 0, "Should exit non-zero on invalid URL"
    log("PASS: test_invalid_url_exits")
    return True


def test_unreachable_server(manager):
    """Verify wsburrow starts even when server is unreachable (should retry later)."""
    p = subprocess.Popen(
        [WSBURROW, "-R", "tcp://19999:localhost:19998", "ws://localhost:19997",
         "--pool-size", "1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    assert p.poll() is None, "wsburrow should stay running (retry loop)"
    p.terminate()
    p.wait()
    log("PASS: test_unreachable_server")
    return True


def main():
    tests = [
        ("basic_roundtrip", test_basic_roundtrip),
        ("large_data", test_large_data),
        ("pool_size", test_pool_size),
        ("ping_keepalive", test_ping_keepalive),
        ("multiple_tunnels", test_multiple_tunnels),
        ("tls_roundtrip", test_tls_roundtrip),
        ("mtls_roundtrip", test_mtls_roundtrip),
        ("mtls_rejected", test_mtls_rejected),
        ("invalid_url_exits", test_invalid_url_exits),
        ("unreachable_server", test_unreachable_server),
    ]

    if not os.path.exists(WSBURROW):
        print(f"FAIL: wsburrow binary not found at {WSBURROW}")
        sys.exit(1)
    if not os.path.exists(WSTUNNEL):
        print(f"FAIL: wstunnel binary not found at {WSTUNNEL}")
        sys.exit(1)

    passed = 0
    failed = 0
    for name, func in tests:
        test_name = name.replace("_", " ")
        print(f"TEST: {test_name}...", end=" ", flush=True)
        mgr = ProcManager()
        try:
            func(mgr)
            print("PASS")
            passed += 1
        except Exception as e:
            print(f"FAIL ({e})")
            failed += 1
        finally:
            mgr.kill_all()
        time.sleep(1)

    print(f"\n{passed}/{passed + failed} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
