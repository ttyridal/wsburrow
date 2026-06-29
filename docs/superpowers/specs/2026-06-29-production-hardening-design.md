# Production Hardening — PONG Timeout, Exponential Backoff, Health Stats

## Problem

wsburrow has no mechanism to detect silent connection loss (e.g., network partition where TCP half-open persists). Reconnects use a fixed 1s delay with no backoff. No connection health data exists for diagnostics.

## Changes

### 1. PONG Timeout Detection

**ws_client.h** — add `on_pong` to ops:
```c
struct ws_client_ops {
    void (*on_connect)(void *ctx);
    void (*on_data)(void *ctx, const void *data, int len);
    void (*on_close)(void *ctx);
    void (*on_pong)(void *ctx);   // NEW
    void *ctx;
};
```

**ws_client.c** — handle `LWS_CALLBACK_CLIENT_RECEIVE_PONG` in `wsburrow_callback`; calls `c->ops.on_pong(c->ops.ctx)` if set.

**tunnel.c** — `pool_entry` gains a `struct uloop_timeout pong_timer`. On PING send, start timer. On PONG receipt, cancel timer. Timer expiry destroys the WS client, marks entry dead, triggers reconnect with backoff.

Constants (defined at top of tunnel.c):
```c
#define PONG_TIMEOUT_MS 8000
```

### 2. Exponential Backoff Reconnect

**tunnel.c** — `pool_entry` gains:
- `struct uloop_timeout reconnect_timer` — per-entry timer (replaces pool-level `reconnect_timer` + `reconnecting` flag)
- `int retry_count` — reset to 0 on successful connect, incremented on each failure

Backoff schedule: `delay = 1000 << retry_count` (1s, 2s, 4s, 8s, 16s, 32s) capped at 30s.

Constants:
```c
#define BACKOFF_BASE_MS  1000
#define BACKOFF_MAX_MS   30000
```

`pool_entry_on_connect` resets `retry_count = 0`. Close/timeout callbacks increment retry_count and schedule entry's own reconnect timer.

### 3. Health Stats

Three counters per pool_entry:
```c
unsigned long rx_bytes;        // incremented in pool_entry_on_data
unsigned long tx_bytes;        // incremented in pool_entry_on_local_data
unsigned long reconnect_count; // incremented each reconnection
```

No user-facing output. Internal only.

### 4. Removed

- `struct uloop_timeout reconnect_timer` from `struct tunnel_pool`
- `int reconnecting` from `struct tunnel_pool`
- `reconnect_cb()` — replaced by per-entry `entry_reconnect_cb()`

### 5. Cleanup

`tunnel_pool_destroy` cancels each entry's `pong_timer` and `reconnect_timer` before destroying the entry's WS client and local TCP.

## Files Changed

| File | Change |
|------|--------|
| src/ws_client.h | Add `on_pong` to ops struct |
| src/ws_client.c | Handle `LWS_CALLBACK_CLIENT_RECEIVE_PONG` |
| src/tunnel.h | (none — pool_entry internal to tunnel.c) |
| src/tunnel.c | Add `pong_timer`, `reconnect_timer`, `retry_count`, `rx_bytes`, `tx_bytes`, `reconnect_count` to pool_entry; replace pool-level reconnect with per-entry; add PONG timeout handling |

## No CLI Changes

No new flags. PONG timeout is hardcoded. Backoff schedule is hardcoded. Existing `--ping-interval` controls PING frequency.
