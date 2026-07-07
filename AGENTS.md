# wsburrow

A stripped-down [wstunnel](https://github.com/erebe/wstunnel)-compatible reverse TCP tunnel client for OpenWRT (client only). Protocol-compatible with wstunnel v10.5.5 server.

## Architecture

```
wsburrow (C11, CMake)
├── main.c          # Entry point: parses args, creates lws context, runs uloop
├── config.c/h      # CLI parsing: -R tunnels, --pool-size, --ping-interval, --insecure, --client-cert/key
├── tunnel.c/h      # Connection pool manager: per-tunnel pool of N parallel WebSocket connections
├── ws_client.c/h   # libwebsockets client connection: connect, send, receive, ping/pong
├── local_tcp.c/h   # Local TCP listener via libubox ustream (async buffered I/O on uloop)
├── jwt.c/h         # JWT token generation in wstunnel v10.5.5 format
└── base64.c/h      # Standalone base64url encoder (no external crypto dependency)
```

- **Event loop:** libubox uloop (the main loop). lws integrates via `LWS_SERVER_OPTION_ULOOP`.
- **TLS:** Handled entirely by libwebsockets — wsburrow has no direct TLS dependency.
- **Wire protocol:** WebSocket frames with JSON JWT auth, compatible with wstunnel v10.5.5.

## Build

### Development (x86 / desktop)

```sh
cd vendor && sh prepare.sh   # fetch libwebsockets 4.5.8 + libubox (git-archived)
cd ..
mkdir build && cd build
cmake .. && make -j$(nproc)
```

`vendor/prepare.sh` fetches the dependencies via curl/git and applies `vendor/01-libublox-build-convenience.patch` (disables Lua/examples, makes json-c optional). The vendored copies are `.gitignore`'d.

### OpenWRT

See `openwrt/Makefile`. Uses system `libubox` and `libwebsockets` from the OpenWRT feed:

```cmake
cmake .. -DWSBURROW_USE_SYSTEM_LIBS=ON -DBUILD_TESTS=OFF
```

## Usage

```
wsburrow [options] ws[s]://server:port

  -R tcp://bind:dest:port    Reverse tunnel (repeatable, up to 16)
  --pool-size N              Connections per tunnel (default: 3)
  --ping-interval N          Ping interval in seconds (default: 15)
  --insecure                 Allow self-signed/expired server certs
  --client-cert FILE         mTLS client certificate
  --client-key FILE          mTLS client private key
```

## Testing

```sh
cd build
ctest -R "test_config|test_jwt" -V          # 15 unit tests (GoogleTest)
python3 ../tests/test_integration.py -v      # 10 integration tests (needs wstunnel binary)
```

## Key behaviors

- **Pooling:** Each `-R` tunnel creates N WebSocket connections (configurable via `--pool-size`). If one drops, a replacement is reconnected with exponential backoff (1s → 30s max).
- **Ping keepalive:** Sends WebSocket pings at `--ping-interval`. An 8s pong timeout marks the connection dead.
- **JWT auth:** Each connection sends a JWT with tunnel metadata (`p:{"ReverseTcp":{}}`). The server validates the token.
- **Exit on cert failure:** If all pool entries are dead, wsburrow checks whether the server likely requires a client certificate (exit(1) with a diagnostic message).
- **No `wss://` without TLS:** wsburrow exits if TLS is needed but lws wasn't built with SSL support.

## Dependencies

| Library | Role | Dev build | OpenWRT build |
|---------|------|-----------|---------------|
| libwebsockets 4.5.8 | WebSocket + TLS transport | Vendored (`vendor/prepare.sh`) | System package |
| libubox | Event loop (uloop), async I/O (ustream), utilities | Vendored | System package |
| OpenSSL / mbedTLS | TLS (used by lws, NOT wsburrow) | System (auto-detected by lws) | System |
