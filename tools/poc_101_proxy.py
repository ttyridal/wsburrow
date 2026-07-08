#!/usr/bin/env python3
"""
PoC: wstunnel delays 101 response for reverse tunnels until external client connects.

Architecture:
    wstunnel client -> PoC proxy (port 22460) -> wstunnel server (port 22470)

The proxy sits between wstunnel client and server, forwarding connections
but killing idle ones after 40 seconds of no data. This demonstrates that
wstunnel server delays its 101 Switching Protocols response for reverse
tunnels until an external client actually connects.
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
TIMEOUT_SECONDS = 40
RUN_DURATION = 120
IDLE_CHECK_INTERVAL = 1.0

WSTUNNEL_BIN = "/project/wstunnel-10.5.5/bin/wstunnel"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("poc_101_proxy")


# ── Connection Tracker ────────────────────────────────────────────────────────
class ConnectionTracker:
    """Tracks active proxy connections and their idle state."""

    def __init__(self):
        self._connections: dict[int, dict] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()

    async def register(self, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> int:
        async with self._lock:
            cid = self._next_id
            self._next_id += 1
            self._connections[cid] = {
                "reader": reader,
                "writer": writer,
                "last_activity": time.monotonic(),
                "bytes_sent": 0,
                "bytes_recv": 0,
                "peer": writer.get_extra_info("peername", ("?", 0)),
            }
            return cid

    async def remove(self, cid: int):
        async with self._lock:
            self._connections.pop(cid, None)

    async def mark_activity(self, cid: int, sent: int = 0, recv: int = 0):
        async with self._lock:
            conn = self._connections.get(cid)
            if conn:
                conn["last_activity"] = time.monotonic()
                conn["bytes_sent"] += sent
                conn["bytes_recv"] += recv

    def snapshot(self) -> list[tuple[int, float, str]]:
        """Return list of (cid, idle_seconds, peer_str) for all connections."""
        now = time.monotonic()
        result = []
        for cid, conn in list(self._connections.items()):
            idle = now - conn["last_activity"]
            result.append((cid, idle, str(conn["peer"])))
        return result

    @property
    def active_count(self) -> int:
        return len(self._connections)


# ── Proxy Connection Handler ──────────────────────────────────────────────────
async def handle_client(proxy_reader: asyncio.StreamReader,
                        proxy_writer: asyncio.StreamWriter,
                        tracker: ConnectionTracker,
                        stats: dict):
    """Handle a single client connection by proxying to the wstunnel server."""
    peer = proxy_writer.get_extra_info("peername", ("?", 0))
    cid = await tracker.register(proxy_reader, proxy_writer)
    log.info("[%d] CONNECT from %s", cid, peer)
    stats["connections"] += 1

    try:
        # Connect to the wstunnel server
        server_reader, server_writer = await asyncio.wait_for(
            asyncio.open_connection(PROXY_HOST, SERVER_PORT),
            timeout=10,
        )
        log.info("[%d] Connected to server %s:%d", cid, PROXY_HOST, SERVER_PORT)
    except (OSError, asyncio.TimeoutError) as e:
        log.info("[%d] Failed to connect to server: %s", cid, e)
        proxy_writer.close()
        await tracker.remove(cid)
        return

    closed = asyncio.Event()
    stats["active_proxies"] += 1

    async def forward(src_reader, dst_writer, label, direction):
        """Forward bytes from src to dst, tracking activity."""
        nonlocal closed
        try:
            while True:
                data = await src_reader.read(65536)
                if not data:
                    break
                dst_writer.write(data)
                await dst_writer.drain()
                n = len(data)
                await tracker.mark_activity(cid,
                                            sent=n if direction == "send" else 0,
                                            recv=n if direction == "recv" else 0)
                log.info("[%d] %s %d bytes", cid, label, n)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            closed.set()

    # Start bidirectional forwarding
    tasks = [
        asyncio.create_task(forward(proxy_reader, server_writer, ">>>", "send")),
        asyncio.create_task(forward(server_reader, proxy_writer, "<<<", "recv")),
    ]

    # Wait for either direction to finish (connection closed)
    try:
        await closed.wait()
    except asyncio.CancelledError:
        pass
    finally:
        stats["active_proxies"] -= 1
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        for w in (proxy_writer, server_writer):
            try:
                w.close()
            except Exception:
                pass

        await tracker.remove(cid)
        log.info("[%d] CLOSE", cid)


# ── Idle Connection Killer ────────────────────────────────────────────────────
async def idle_killer(tracker: ConnectionTracker, timeout: float, stats: dict):
    """Background task that kills connections idle longer than timeout."""
    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL)
        for cid, idle_secs, peer in tracker.snapshot():
            if idle_secs >= timeout:
                log.info("[%d] TIMEOUT (idle %.1fs, peer=%s) — closing",
                         cid, idle_secs, peer)
                stats["timed_out"] += 1
                conn_info = tracker._connections.get(cid)
                if conn_info:
                    try:
                        conn_info["writer"].close()
                    except Exception:
                        pass
                await tracker.remove(cid)


# ── Echo Server ───────────────────────────────────────────────────────────────
async def run_echo_server(host: str, port: int):
    """Simple TCP echo server."""
    async def handle(reader, writer):
        peer = writer.get_extra_info("peername", ("?", 0))
        log.info("[echo] CONNECT %s", peer)
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
            log.info("[echo] CLOSE %s", peer)

    server = await asyncio.start_server(handle, host, port)
    log.info("Echo server listening on %s:%d", host, port)
    return server


# ── PoC Proxy Server ──────────────────────────────────────────────────────────
async def run_proxy(host: str, port: int, tracker: ConnectionTracker, stats: dict):
    """Run the PoC proxy server."""
    async def on_connect(reader, writer):
        await handle_client(reader, writer, tracker, stats)

    server = await asyncio.start_server(on_connect, host, port)
    log.info("PoC proxy listening on %s:%d", host, port)
    return server


# ── Wstunnel Process Management ──────────────────────────────────────────────
async def run_wstunnel(args: list[str],
                       label: str,
                       env: dict | None = None) -> asyncio.subprocess.Process:
    """Start a wstunnel process and wait briefly to confirm it started."""
    log.info("Starting wstunnel %s: %s", label, " ".join(args))
    proc = await asyncio.create_subprocess_exec(
        WSTUNNEL_BIN,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    # Read a few lines to confirm it's alive
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


# ── Main Orchestrator ─────────────────────────────────────────────────────────
async def main():
    stats = {
        "connections": 0,
        "timed_out": 0,
        "active_proxies": 0,
    }
    tracker = ConnectionTracker()
    start_time = time.monotonic()

    processes: list[asyncio.subprocess.Process] = []
    servers: list[asyncio.AbstractServer] = []

    log.info("=" * 60)
    log.info("PoC: wstunnel 101 delay for reverse tunnels")
    log.info("=" * 60)
    log.info("Architecture: client -> proxy:%d -> server:%d", PROXY_PORT, SERVER_PORT)
    log.info("Idle timeout: %ds", TIMEOUT_SECONDS)
    log.info("Run duration: %ds", RUN_DURATION)
    log.info("")

    try:
        # 1. Start echo server
        echo_server = await run_echo_server(PROXY_HOST, ECHO_PORT)
        servers.append(echo_server)

        # 2. Start wstunnel server
        proc_server = await run_wstunnel([
            "server", f"ws://{PROXY_HOST}:{SERVER_PORT}",
            "--log-lvl", "debug",
        ], "server")
        processes.append(proc_server)

        # Give server a moment to bind
        await asyncio.sleep(1)

        # 3. Start PoC proxy
        proxy_server = await run_proxy(PROXY_HOST, PROXY_PORT, tracker, stats)
        servers.append(proxy_server)

        # 4. Start idle connection killer
        killer_task = asyncio.create_task(
            idle_killer(tracker, TIMEOUT_SECONDS, stats)
        )

        # 5. Start wstunnel client (reverse tunnel)
        proc_client = await run_wstunnel([
            "client",
            "-R", f"tcp://{ECHO_PORT + 1}:localhost:{ECHO_PORT}",
            f"ws://localhost:{PROXY_PORT}",
            "--websocket-ping-frequency", "5s",
            "--log-lvl", "debug",
        ], "client")
        processes.append(proc_client)

        # 6. Stream output from wstunnel processes
        output_tasks = [
            asyncio.create_task(stream_output(proc_server, "server")),
            asyncio.create_task(stream_output(proc_client, "client")),
        ]

        # 7. Run for the specified duration
        log.info("\nRunning for %d seconds...", RUN_DURATION)
        await asyncio.sleep(RUN_DURATION)

        # 8. Stop everything
        log.info("\n" + "=" * 60)
        log.info("Shutting down...")
        log.info("=" * 60)

        # Cancel output streaming
        for t in output_tasks:
            t.cancel()
        await asyncio.gather(*output_tasks, return_exceptions=True)

        # Terminate processes
        for proc in processes:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

        # Cancel killer
        killer_task.cancel()
        try:
            await killer_task
        except asyncio.CancelledError:
            pass

        # Close servers
        for srv in servers:
            srv.close()
            await srv.wait_closed()

    except Exception as e:
        log.error("Fatal error: %s", e)
        # Emergency cleanup
        for proc in processes:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        raise

    finally:
        elapsed = time.monotonic() - start_time
        log.info("\n" + "=" * 60)
        log.info("SUMMARY")
        log.info("=" * 60)
        log.info("Total connections proxied: %d", stats["connections"])
        log.info("Connections timed out:    %d", stats["timed_out"])
        log.info("Total run duration:       %.1f seconds", elapsed)
        log.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(0)
