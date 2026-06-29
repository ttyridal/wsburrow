# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PONG timeout detection, exponential-backoff reconnect, and internal health counters to wsburrow.

**Architecture:** ws_client gains an `on_pong` callback for LWS_CALLBACK_CLIENT_RECEIVE_PONG. tunnel.c's pool_entry gets per-entry timers for PONG timeout and reconnect with retry_count. Pool-level reconnect_timer is removed.

**Tech Stack:** C (lws 4.5.8, libubox uloop, gtest)

---

### Task 1: Add `on_pong` callback to ws_client

**Files:**
- Modify: `src/ws_client.h:12-17`
- Modify: `src/ws_client.c:110-180`

- [ ] **Step 1: Add `on_pong` to ws_client_ops**

Edit `src/ws_client.h`, add `on_pong` field:

```c
struct ws_client_ops {
    void (*on_connect)(void *ctx);
    void (*on_data)(void *ctx, const void *data, int len);
    void (*on_close)(void *ctx);
    void (*on_pong)(void *ctx);
    void *ctx;
};
```

- [ ] **Step 2: Handle LWS_CALLBACK_CLIENT_RECEIVE_PONG in wsburrow_callback**

Edit `src/ws_client.c`, add a new case in the switch before `default`:

```c
    case LWS_CALLBACK_CLIENT_RECEIVE_PONG:
        if (c && c->ops.on_pong)
            c->ops.on_pong(c->ops.ctx);
        break;
```

- [ ] **Step 3: Verify build**

```bash
cd /project/wsburrow && cmake --build build
```
Expected: clean build, no errors/warnings.

- [ ] **Step 4: Run unit tests**

```bash
cd /project/wsburrow && (cd build && ctest --output-on-failure -R wsburrow_test)
```
Expected: 2/2 test suites pass (15 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ws_client.h src/ws_client.c
git commit -m "feat: add on_pong callback to ws_client_ops"
```

---

### Task 2: Add PONG timeout, exponential backoff, health stats to tunnel

**Files:**
- Modify: `src/tunnel.c` (entire file, many sections)

- [ ] **Step 1: Add constants at top of tunnel.c**

After `#define MAX_POOL 32`, add:

```c
#define PONG_TIMEOUT_MS  8000
#define BACKOFF_BASE_MS  1000
#define BACKOFF_MAX_MS   30000
```

- [ ] **Step 2: Extend pool_entry struct**

Replace the existing pool_entry with:

```c
struct pool_entry {
    struct tunnel_pool *pool;
    struct ws_client *ws;
    struct local_tcp *local;
    int active;
    int dead;
    char jwt[512];
    struct uloop_timeout pong_timer;
    struct uloop_timeout reconnect_timer;
    int retry_count;
    unsigned long rx_bytes;
    unsigned long tx_bytes;
    unsigned long reconnect_count;
};
```

- [ ] **Step 3: Remove pool-level reconnect fields from tunnel_pool**

Remove from `struct tunnel_pool`:
```c
    struct uloop_timeout reconnect_timer;
    int reconnecting;
```

- [ ] **Step 4: Set on_pong in pool_entry_connect**

In `pool_entry_connect()`, update the ops initializer:

```c
    struct ws_client_ops ops = {
        .on_connect = pool_entry_on_connect,
        .on_data = pool_entry_on_data,
        .on_close = pool_entry_on_close,
        .on_pong = pool_entry_on_pong,
        .ctx = e,
    };
```

- [ ] **Step 5: Implement pong timeout callback**

Add before `pool_entry_connect`:

```c
static void pong_timeout_cb(struct uloop_timeout *t)
{
    struct pool_entry *e = container_of(t, struct pool_entry, pong_timer);
    if (e->ws) {
        e->dead = 1;
        ws_client_destroy(e->ws);
        e->ws = NULL;
        int delay = BACKOFF_BASE_MS << e->retry_count;
        if (delay > BACKOFF_MAX_MS) delay = BACKOFF_MAX_MS;
        e->retry_count++;
        e->reconnect_count++;
        uloop_timeout_set(&e->reconnect_timer, delay);
    }
}
```

- [ ] **Step 6: Implement entry reconnect callback**

```c
static void entry_reconnect_cb(struct uloop_timeout *t)
{
    struct pool_entry *e = container_of(t, struct pool_entry, reconnect_timer);
    e->dead = 0;
    struct tunnel_pool *pool = e->pool;
    int idx = e - pool->entries;
    pool_entry_connect(pool, idx);
}
```

- [ ] **Step 7: Implement pool_entry_on_pong**

```c
static void pool_entry_on_pong(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    uloop_timeout_cancel(&e->pong_timer);
}
```

- [ ] **Step 8: Update ping_cb to start pong timer**

Edit `ping_cb`, after `ws_client_ping(e->ws)`:

```c
static void ping_cb(struct uloop_timeout *t)
{
    struct tunnel_pool *pool = container_of(t, struct tunnel_pool, ping_timer);
    for (int i = 0; i < pool->pool_size; i++) {
        if (pool->entries[i].ws) {
            ws_client_ping(pool->entries[i].ws);
            uloop_timeout_set(&pool->entries[i].pong_timer, PONG_TIMEOUT_MS);
        }
    }
    uloop_timeout_set(t, pool->ping_interval * 1000);
}
```

- [ ] **Step 9: Update pool_entry_on_connect**

```c
static void pool_entry_on_connect(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    e->retry_count = 0;
}
```

- [ ] **Step 10: Update pool_entry_on_close**

Replace the current body with:

```c
static void pool_entry_on_close(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    uloop_timeout_cancel(&e->pong_timer);
    e->dead = 1;

    int delay = BACKOFF_BASE_MS << e->retry_count;
    if (delay > BACKOFF_MAX_MS) delay = BACKOFF_MAX_MS;
    e->retry_count++;
    e->reconnect_count++;
    uloop_timeout_set(&e->reconnect_timer, delay);
}
```

Note: `e->ws` is already NULL at this point (set in LWS_CALLBACK_CLIENT_CLOSED handler before on_close fires), and the ws_client struct itself is still valid memory. `pool_entry_connect` will call `ws_client_destroy` on it before creating a new one.

- [ ] **Step 11: Increment rx_bytes in pool_entry_on_data**

Add at the start of `pool_entry_on_data`:

```c
    e->rx_bytes += len;
```

- [ ] **Step 12: Increment tx_bytes and reconnect_count in pool_entry_on_local_data and entry_reconnect_cb**

In `pool_entry_on_local_data`:
```c
    e->tx_bytes += len;
```

In `pong_timeout_cb` and `pool_entry_on_close` (already done in steps 5 and 10).

- [ ] **Step 13: Remove pool-level reconnect timer initialization from tunnel_pool_create**

Remove these lines from `tunnel_pool_create`:
```c
    pool->reconnect_timer.cb = reconnect_cb;
    uloop_timeout_set(&pool->reconnect_timer, 1000);
```
(They don't exist yet — the pool-level reconnect timer is initialized in `pool_entry_on_close` at line 176-179. Just don't add them.)

- [ ] **Step 14: Update tunnel_pool_destroy to cancel per-entry timers**

Replace the loop body:

```c
    for (int i = 0; i < pool->pool_size; i++) {
        uloop_timeout_cancel(&pool->entries[i].pong_timer);
        uloop_timeout_cancel(&pool->entries[i].reconnect_timer);
        if (pool->entries[i].local)
            local_tcp_destroy(pool->entries[i].local);
        if (pool->entries[i].ws)
            ws_client_destroy(pool->entries[i].ws);
    }
```

- [ ] **Step 15: Remove old reconnect_cb function**

Delete the `reconnect_cb` function entirely (it was the pool-level batch reconnect handler).

- [ ] **Step 16: Verify build**

```bash
cd /project/wsburrow && cmake --build build
```
Expected: clean build.

- [ ] **Step 17: Run unit tests**

```bash
cd /project/wsburrow && (cd build && ctest --output-on-failure -R wsburrow_test)
```
Expected: 2/2 test suites pass (15 tests).

- [ ] **Step 18: Run integration tests**

```bash
cd /project/wsburrow && python3 tests/test_integration.py --verbose
```
Expected: 7/7 tests pass.

- [ ] **Step 19: Commit**

```bash
git add src/tunnel.c
git commit -m "feat: pong timeout detection, exponential backoff, health stats"
```
