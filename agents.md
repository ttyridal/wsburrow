# wsburrow — Agent Context

## Project Goal
Build wsburrow: a stripped-down wstunnel-compatible C client for OpenWRT (client only, reverse TCP tunnels). Protocol compatible with wstunnel 10.5.5 server.

## Build System
- **CMake** 3.28.3, **gcc** 13.3.0
- Remove stale builds: `rm build/CMakeCache.txt && cmake -B build && cmake --build build -j$(nproc)`
- No pkg-config on this system
- Git repo at `/project/wsburrow`

## Dependencies
| Library | Location | Notes |
|---------|----------|-------|
| libwebsockets 4.5.8 | `vendor/libwebsockets-4.5.8/` (source) | Built from source with LWS_WITH_ULOOP=ON, LWS_WITH_SSL=ON, LWS_WITH_EVLIB_PLUGINS=OFF |
| mbedtls 2.28.8 | System (`/usr/lib/x86_64-linux-gnu/libmbedtls.a`) | Used for JWT base64url encoding |
| libubox | `vendor/libubox/` (source) | Provides uloop event loop; vendored as git submodule. Symlink: `vendor/include/libubox` → `../libubox` |
| wstunnel 10.5.5 | `/project/wstunnel-10.5.5/bin/wstunnel` | Reference server for integration testing (not in wsburrow repo) |
| openssl CLI | System | Used for generating test certificates |

### lws build caveats
- lws links against OpenSSL (`libssl.so.3`, `libcrypto.so.3`) and mbedtls (`libmbedcrypto.so.7`)
- `LWS_WITH_EXPORT_LWSTARGETS=OFF` because linking `ubox` target into export set fails
- `LCCSCF_SERVER_SSL` does not exist in lws 4.5.8 — use `LCCSCF_USE_SSL` alone
- For `--insecure`, must set all four ALLOW_* flags (`ALLOW_INSECURE` alone is insufficient for self-signed certs)

## Architecture
- Single uloop event loop with `LWS_SERVER_OPTION_ULOOP` integration
- Pool of N WebSocket connections per tunnel (`--pool-size`, default 3)
- Exponential backoff reconnect: 1s, 2s, 4s, 8s, 16s, 30s max
- Mandatory ping/pong keepalive (`--ping-interval`, default 15s), PONG timeout 8s

### Key source files
| File | Purpose |
|------|---------|
| `src/config.c/h` | CLI parsing: `-R`, `--pool-size`, `--ping-interval`, `--insecure`, `--client-cert`, `--client-key`, URL |
| `src/jwt.c/h` | JWT generation with base64url via mbedtls |
| `src/ws_client.c/h` | lws WebSocket client with pending buffer, ping, on_pong callback |
| `src/local_tcp.c/h` | Local TCP connect/relay via usock+ustream, 64KB pending buffer |
| `src/tunnel.c/h` | Pool manager with per-entry pong_timer (8s), reconnect_timer (exponential backoff), health counters |
| `src/main.c` | Entry point — uloop init, lws context creation, tunnel pool start |

### Config fields (struct config in config.h)
- `server_host[256]`, `server_port` — from URL
- `use_tls` — from `wss://` vs `ws://` scheme
- `pool_size`, `ping_interval` — CLI flags
- `insecure` — `--insecure` flag (skip TLS verification)
- `client_cert[512]`, `client_key[512]` — `--client-cert`, `--client-key` paths
- `num_tunnels`, `tunnels[MAX_TUNNELS]` — from `-R` flags

## JWT Format
- Header: `{"typ":"JWT","alg":"HS256"}` (27 bytes, static)
- Payload: `{"id":"00000000","p":"ReverseTcp","r":"<bind-addr>","rp":<bind-port>}` — `p` is string `"ReverseTcp"`, NOT an object
- Signature: dummy base64 string (not validated by insecure_decode)
- WS upgrade path: `/v1/events`
- Sec-WebSocket-Protocol: `v1, authorization.bearer.<jwt>` via `ci.protocol`

## lws Protocol Setup
```c
static const struct lws_protocols tunnel_protocols[] = {
    { "wsburrow", wsburrow_callback, sizeof(struct ws_client *), 0 },
    { "v1", wsburrow_callback, sizeof(struct ws_client *), 0 },
    { NULL, NULL, 0, 0 }
};
```
Both protocols route to the same `wsburrow_callback`.

## Pending Buffer
- 65536 bytes (PENDING_MAX) + LWS_PRE headroom
- Data stored at `pending + LWS_PRE`
- Flushed to local TCP on connect callback

## Fatal Exit Paths
Three cases where wsburrow exits with code 1:

1. **`--client-cert` configured + connection fails before any success** → `exit(1)` immediately (server rejected the cert)
2. **wss://, no `--client-cert`, never connected, retry_count >= 2** → `exit(1)` (server likely requires mTLS)
3. **`--client-cert` configured + all pool entries dead** → `exit(1)` (redundant with #1 now, kept for safety)

All others (plain ws:// failures, TLS failures after successful connection) → retry loop.

## Testing
**Unit tests (gtest):**
- `tests/test_config.cc` — 9 tests
- `tests/test_jwt.cc` — 6 tests
- Run: `cmake --build build && ctest --test-dir build` (also runs integration tests)

**Integration tests (Python):**
- `tests/test_integration.py` — 10 tests (basic_roundtrip, large_data, pool_size, ping_keepalive, multiple_tunnels, tls_roundtrip, mtls_roundtrip, mtls_rejected, invalid_url_exits, unreachable_server)
- Run: `python3 tests/test_integration.py [--verbose]`
- ctest timeout: 200s
- Port base offsets prevent conflicts between tests

**Test cert generation:**
- `_gen_ca_chain(tmpdir)` helper generates CA + server + client v3 cert chain
- v3 certs required: rustls rejects v1 certs with `UnsupportedCertVersion`
- Generated via `openssl x509 -req -extfile /dev/stdin` with proper extensions (serverAuth SAN, clientAuth)

## Fatal Exit Paths
Three cases where wsburrow exits with code 1:

1. **`--client-cert` configured + connection fails before any success** → `exit(1)` immediately (server rejected the cert)
2. **wss://, no `--client-cert`, never connected, retry_count >= 2, all entries dead** → `exit(1)` (server likely requires mTLS)
3. **`--client-cert` configured + all pool entries dead** → `exit(1)` (guarded by all_dead check)

Note: `exit(1)` is used (not uloop_end) for fatal errors. OS handles cleanup. Graceful teardown would add complexity with no practical benefit for fatal error paths.

## Git History
14 commits on master:
```
7ba2833 fix: code review — fd leak, error handling, data loss, parse bug
6ab213a fix: proper ustream backpressure drain + remove 64KB stack buffer
242e742 update plans
e66df34 fix: exit immediately on first connection failure when client cert configured
0ba5ac3 fix: fatal exit when server requires client cert but none configured
b565120 feat: TLS stage 2 -- client certificate support with mTLS tests
d881ad2 feat: wss:// support with --insecure flag
6a0ad95 fix: handle ws_client_connect immediate failure with reconnect
9dcec8b fix: clamp shift to 5 to avoid UB, cancel pong_timer in defensive destroy
c4b7096 refactor: remove redundant loop in pool_entry_on_data, fix shift UB
be92b26 fix: set pong_timer and reconnect_timer callbacks
493737a feat: pong timeout detection, exponential backoff, health stats
6e89b9a feat: add on_pong callback to ws_client_ops
0ca1706 Initial wsburrow implementation
```
`.gitignore` excludes `build/`, `__pycache__/`, `vendor/libwebsockets-4.5.8/`, `wstunnel-*/`

## Next Steps
- OpenWRT packaging (package feed entry in `openwrt/packages/net/wsburrow/`)
