#!/usr/bin/env python3
"""
test_tunnel_resilience.py

Tests whether wstunnel connections survive a WebSocket-level disconnection
and whether the client can reconnect and resume operation.

Architecture:
    cli-server (22452) <- wstunnel client <- test proxy (22460) <- wstunnel server (22470) <- cli-app

The test proxy sits between wstunnel client and wstunnel server. It can simulate
a tunnel disconnection by closing all active WebSocket TCP connections.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time

# ── Constants ──────────────────────────────────────────────────────────────────
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 22460
SERVER_PORT = 22470
ECHO_PORT = 22452
CLIENT_LISTEN_PORT = 22471

WSTUNNEL_BIN = "/project/wstunnel-10.5.5/bin/wstunnel"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_resilience")


# ── Kill-Switch Proxy ──────────────────────────────────────────────────────────
class KillSwitchProxy:
    """TCP proxy that can kill all active connections on demand."""

    def __init__(self, listen_host: str, listen_port: int, target_host: str, target_port: int):
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._target_host = target_host
        self._target_port = target_port
        self._kill_event = asyncio.Event()
        self._active_pairs: list[tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = []
        self._lock = asyncio.Lock()
        self._connection_count = 0
        self._server: asyncio.AbstractServer | None = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_connection, self._listen_host, self._listen_port
        )
        log.info("[proxy] Listening on %s:%d (forwarding to %s:%d)",
                 self._listen_host, self._listen_port, self._target_host, self._target_port)
        return self._server

    async def _handle_connection(self, client_reader: asyncio.StreamReader,
                                 client_writer: asyncio.StreamWriter):
        peer = client_writer.get_extra_info("peername", ("?", 0))
        async with self._lock:
            self._connection_count += 1
            cid = self._connection_count
        log.info("[proxy:%d] CONNECT from %s", cid, peer)

        try:
            target_reader, target_writer = await asyncio.wait_for(
                asyncio.open_connection(self._target_host, self._target_port),
                timeout=10,
            )
        except (OSError, asyncio.TimeoutError) as e:
            log.info("[proxy:%d] Failed to connect to target: %s", cid, e)
            client_writer.close()
            return

        log.info("[proxy:%d] Connected to target %s:%d", cid, self._target_host, self._target_port)

        # Register the pair
        async with self._lock:
            self._active_pairs.append((client_writer, target_writer))

        closed = asyncio.Event()

        async def forward(src_reader, dst_writer, label):
            try:
                while True:
                    data = await src_reader.read(65536)
                    if not data:
                        break
                    dst_writer.write(data)
                    await dst_writer.drain()
                    log.info("[proxy:%d] %s %d bytes", cid, label, len(data))
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                closed.set()

        tasks = [
            asyncio.create_task(forward(client_reader, target_writer, ">>>")),
            asyncio.create_task(forward(target_reader, client_writer, "<<<")),
        ]

        # Wait for the kill event OR connection close
        kill_task = asyncio.create_task(self._kill_event.wait())
        closed_task = asyncio.create_task(closed.wait())
        done, _ = await asyncio.wait(
            [closed_task, kill_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks
        for t in tasks:
            t.cancel()
        kill_task.cancel()
        closed_task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Close both sides
        for w in (client_writer, target_writer):
            try:
                w.close()
            except Exception:
                pass

        # Remove from active pairs
        async with self._lock:
            self._active_pairs = [(cw, tw) for cw, tw in self._active_pairs
                                  if cw is not client_writer and tw is not target_writer]

        if self._kill_event.is_set():
            log.info("[proxy:%d] CLOSE (kill switch)", cid)
        else:
            log.info("[proxy:%d] CLOSE (connection closed)", cid)

    async def kill_all(self):
        """Trigger the kill switch: close all active connections."""
        log.info("[proxy] KILL SWITCH triggered!")
        self._kill_event.set()
        # Also directly close all tracked writers
        async with self._lock:
            pairs = list(self._active_pairs)
            self._active_pairs.clear()
        for cw, tw in pairs:
            try:
                cw.close()
            except Exception:
                pass
            try:
                tw.close()
            except Exception:
                pass
        log.info("[proxy] All %d active connections closed", len(pairs))
        # Reset the event so new connections can proceed normally
        self._kill_event.clear()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


# ── CLI Server (echo) ──────────────────────────────────────────────────────────
async def run_cli_server(host: str, port: int):
    """Simple echo server that responds ECHO:<data> for each newline-delimited message."""

    async def handle(reader, writer):
        peer = writer.get_extra_info("peername", ("?", 0))
        log.info("[cli-server] CONNECT %s", peer)
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                msg = data.decode().rstrip("\r\n")
                log.info("[cli-server] RECV %s: %s", peer, msg)
                response = f"ECHO:{msg}\n"
                writer.write(response.encode())
                await writer.drain()
                log.info("[cli-server] SEND %s: ECHO:%s", peer, msg)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
            log.info("[cli-server] CLOSE %s", peer)

    server = await asyncio.start_server(handle, host, port)
    log.info("[cli-server] Listening on %s:%d", host, port)
    return server


# ── CLI App (connect and talk through tunnel) ─────────────────────────────────
class CliApp:
    """Connects to the tunnel endpoint and sends/receives messages."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

    async def connect(self):
        """Establish connection to the tunnel endpoint."""
        log.info("[cli-app] Connecting to %s:%d...", self._host, self._port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=10,
            )
            self._connected = True
            peer = self._writer.get_extra_info("peername", ("?", 0))
            log.info("[cli-app] Connected (local peer: %s)", peer)
            return True
        except (OSError, asyncio.TimeoutError) as e:
            log.info("[cli-app] Connection failed: %s", e)
            self._connected = False
            return False

    async def send_and_recv(self, message: str, timeout: float = 5.0):
        """Send a message and wait for the echo response."""
        if not self._connected or not self._writer:
            raise ConnectionError("Not connected")

        data = (message + "\n").encode()
        log.info("[cli-app] SEND %s", message)
        try:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=timeout)
            response = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
            resp_str = response.decode().rstrip("\r\n")
            log.info("[cli-app] RECV %s", resp_str)
            return resp_str
        except (OSError, asyncio.TimeoutError, asyncio.CancelledError) as e:
            log.info("[cli-app] ERROR: %s", e)
            self._connected = False
            raise ConnectionError(str(e)) from e

    async def close(self):
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        self._connected = False


# ── Wstunnel Process Management ──────────────────────────────────────────────
async def run_wstunnel(args: list[str], label: str) -> asyncio.subprocess.Process:
    """Start a wstunnel process."""
    cmd = [WSTUNNEL_BIN] + args
    log.info("[%s] Starting: %s", label, " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        WSTUNNEL_BIN,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    # Read a line to confirm it started
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=3)
        log.info("[%s] %s", label, line.decode().rstrip())
    except asyncio.TimeoutError:
        log.warning("[%s] No output within 3s", label)
    return proc


async def stream_output(proc: asyncio.subprocess.Process, label: str):
    """Continuously read and log process output."""
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            log.info("[%s] %s", label, line.decode().rstrip())
    except Exception:
        pass


async def wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    """Wait for a TCP port to start accepting connections."""
    log.info("Waiting for %s:%d to be listening...", host, port)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=2,
            )
            writer.close()
            log.info("Port %s:%d is now listening", host, port)
            return True
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.5)
    log.error("Timeout waiting for %s:%d", host, port)
    return False


# ── Process Cleanup ────────────────────────────────────────────────────────────
async def terminate_process(proc: asyncio.subprocess.Process, label: str):
    """Gracefully terminate a process, with escalation."""
    if proc.returncode is not None:
        log.info("[%s] Already exited (code %d)", label, proc.returncode)
        return
    log.info("[%s] Terminating...", label)
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
        log.info("[%s] Terminated (code %d)", label, proc.returncode)
    except asyncio.TimeoutError:
        log.warning("[%s] Didn't exit in 5s, killing...", label)
        proc.kill()
        await proc.wait()
        log.info("[%s] Killed (code %d)", label, proc.returncode)


async def terminate_processes(procs: list[tuple[asyncio.subprocess.Process, str]]):
    """Terminate multiple processes concurrently."""
    await asyncio.gather(*[terminate_process(p, l) for p, l in procs], return_exceptions=True)


# ── Main Test Logic ────────────────────────────────────────────────────────────
async def main():
    result = "FAIL"
    procs: list[tuple[asyncio.subprocess.Process, str]] = []
    servers: list[asyncio.AbstractServer] = []
    output_tasks: list[asyncio.Task] = []
    proxy: KillSwitchProxy | None = None

    start_time = time.monotonic()

    log.info("=" * 70)
    log.info("Tunnel Resilience Test")
    log.info("=" * 70)
    log.info("Architecture:")
    log.info("  cli-server:%d <- wstunnel client <- proxy:%d <- wstunnel server:%d <- cli-app",
             ECHO_PORT, PROXY_PORT, SERVER_PORT)
    log.info("")

    try:
        # ── 1. Start cli-server (echo) ────────────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 1: Starting cli-server on port %d", ECHO_PORT)
        echo_server = await run_cli_server(PROXY_HOST, ECHO_PORT)
        servers.append(echo_server)
        await asyncio.sleep(0.5)

        # ── 2. Start wstunnel server ──────────────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 2: Starting wstunnel server on port %d", SERVER_PORT)
        proc_srv = await run_wstunnel([
            "server", f"ws://{PROXY_HOST}:{SERVER_PORT}",
            "--websocket-mask-frame",
            "--log-lvl", "debug",
        ], "server")
        procs.append((proc_srv, "server"))
        await asyncio.sleep(1)

        # ── 3. Start the kill-switch proxy ────────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 3: Starting test proxy on port %d", PROXY_PORT)
        proxy = KillSwitchProxy(PROXY_HOST, PROXY_PORT, PROXY_HOST, SERVER_PORT)
        proxy_server = await proxy.start()
        servers.append(proxy_server)
        await asyncio.sleep(0.5)

        # ── 4. Start wstunnel client through proxy ────────────────────────────
        log.info("─" * 70)
        log.info("STEP 4: Starting wstunnel client (connecting through proxy)")
        proc_cli = await run_wstunnel([
            "client",
            "-R", f"tcp://{CLIENT_LISTEN_PORT}:localhost:{ECHO_PORT}",
            f"ws://localhost:{PROXY_PORT}",
            "--websocket-ping-frequency", "5s",
            "--log-lvl", "debug",
        ], "client")
        procs.append((proc_cli, "client"))

        # Stream output from wstunnel processes
        output_tasks = [
            asyncio.create_task(stream_output(proc_srv, "server")),
            asyncio.create_task(stream_output(proc_cli, "client")),
        ]

        # ── 5. Wait for tunnel to establish ───────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 5: Waiting for tunnel (port %d)...", CLIENT_LISTEN_PORT)
        tunnel_ready = await wait_for_port(PROXY_HOST, CLIENT_LISTEN_PORT, timeout=15)
        if not tunnel_ready:
            log.error("Tunnel did not establish. Aborting.")
            raise RuntimeError("Tunnel establishment failed")

        # ── 6. Connect cli-app, send MSG1 ─────────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 6: Connecting cli-app, sending MSG1")
        app = CliApp(PROXY_HOST, CLIENT_LISTEN_PORT)
        if not await app.connect():
            raise RuntimeError("cli-app failed to connect")
        resp1 = await app.send_and_recv("MSG1")
        log.info("RESULT: MSG1 -> %s", resp1)
        assert resp1 == "ECHO:MSG1", f"Expected ECHO:MSG1, got {resp1}"

        # ── 7. Send MSG2 through same connection ──────────────────────────────
        log.info("─" * 70)
        log.info("STEP 7: Sending MSG2 through same connection (after 2s)")
        await asyncio.sleep(2)
        resp2 = await app.send_and_recv("MSG2")
        log.info("RESULT: MSG2 -> %s", resp2)
        assert resp2 == "ECHO:MSG2", f"Expected ECHO:MSG2, got {resp2}"

        # ── 8. Trigger kill switch ────────────────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 8: Triggering proxy kill switch")
        await proxy.kill_all()

        # ── 9. Wait for reconnect ─────────────────────────────────────────────
        log.info("─" * 70)
        log.info("STEP 9: Waiting 5 seconds for wstunnel client to reconnect")
        await asyncio.sleep(5)

        # ── 10. Try MSG3 through the SAME connection ──────────────────────────
        log.info("─" * 70)
        log.info("STEP 10: Trying to send MSG3 through SAME connection")
        try:
            resp3 = await app.send_and_recv("MSG3", timeout=8)
            log.info("RESULT: MSG3 -> %s", resp3)
            if resp3 and "MSG3" in resp3:
                log.info("CONNECTION SURVIVED - tunnel reconnected underneath")
            else:
                log.info("CONNECTION BROKEN - empty or wrong response (expected)")
                raise ConnectionError("broken connection")
        except (ConnectionError, OSError) as e:
            log.info("RESULT: MSG3 failed: %s", e)
            log.info("CONNECTION DROPPED - as expected")

            # ── 11. New connection, send MSG4 ────────────────────────────────
            log.info("─" * 70)
            log.info("STEP 11: Opening NEW connection, sending MSG4")
            await app.close()
            await asyncio.sleep(1)

            app2 = CliApp(PROXY_HOST, CLIENT_LISTEN_PORT)
            # Wait up to 15s for tunnel to be available again
            tunnel_back = await wait_for_port(PROXY_HOST, CLIENT_LISTEN_PORT, timeout=15)
            if not tunnel_back:
                raise RuntimeError("Tunnel did not come back after kill")

            if not await app2.connect():
                raise RuntimeError("New cli-app connection failed after kill")

            resp4 = await app2.send_and_recv("MSG4")
            log.info("RESULT: MSG4 -> %s", resp4)
            assert resp4 == "ECHO:MSG4", f"Expected ECHO:MSG4, got {resp4}"
            await app2.close()

        else:
            # Connection survived, no need to test new connection
            await app.close()

        result = "PASS"
        log.info("=" * 70)

    except Exception as e:
        log.error("TEST FAILED: %s", e)
        result = "FAIL"
    finally:
        # ── 12. Cleanup ───────────────────────────────────────────────────────
        log.info("─" * 70)
        log.info("CLEANUP: Shutting down all processes")

        # Cancel output streaming
        for t in output_tasks:
            t.cancel()
        await asyncio.gather(*output_tasks, return_exceptions=True)

        # Terminate wstunnel processes
        await terminate_processes(procs)

        # Stop proxy
        if proxy:
            await proxy.stop()

        # Close all servers
        for srv in servers:
            srv.close()
            await srv.wait_closed()

        elapsed = time.monotonic() - start_time
        log.info("=" * 70)
        log.info("TEST RESULT: %s", result)
        log.info("Elapsed time: %.1f seconds", elapsed)
        log.info("=" * 70)

    sys.exit(0 if result == "PASS" else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(0)
