# Code Review Fixes — Implementation Plan

> **Status: IMPLEMENTED (all tasks complete)**
> **Commit:** 7ba2833

**Goal:** Fix all Critical and Important issues from the correctness/security code review, plus selected Minor issues.

**Architecture:** Targeted fixes across 5 source files.

**Tech Stack:** C (libwebsockets 4.5.8, libubox ustream/uloop, mbedtls)

---

### Fixes implemented

**local_tcp.c:**
- C2: `local_tcp_destroy` closes `connect_fd.fd` when connecting (was `uloop_fd_delete` only)
- M2: `local_tcp_drain` and `local_tcp_read_blocked` guarded with `!t->connecting`

**ws_client.c:**
- I6: `ws_client_destroy` calls `lws_wsi_close(wsi, LWS_TO_KILL_ASYNC)` before free

**tunnel.c:**
- I1: `jwt_encode_reverse_tcp` return value checked in `tunnel_pool_create`
- I2: `pool_entry_on_local_data` blocks local reads when `e->ws == NULL`
- I3: Sync `local_tcp_connect` failure in `pool_entry_on_connect` destroys WS + schedules reconnect. Async connect failure via `conn_fd_cb` → local_tcp destroyed only; WS reconnects lazily via `pool_entry_on_data` (which recreates local_tcp when data arrives)
- I5: First exit heuristic moved inside `all_dead` block (no premature exit with pool_size>1)
- I7: `tx_bytes += n` guarded with `n > 0`
- M4: Removed dead `e->active` field from `struct pool_entry`

**config.c:**
- I4: 3-part IPv4 form: `dest_port = bind_port` (was `atoi(parts[2])` parsing hostname)
- M1: `ping_interval <= INT_MAX / 1000` validation (with `<limits.h>`)
- M11: `valid_bind_addr()` helper validates only alphanumeric, `.`, `-`

**main.c:**
- M6: Early returns replaced with `goto cleanup` pattern; `ret` variable tracks exit code

### Deferred
- C3: WS→local backpressure via `lws_rx_flow_control` — future work
