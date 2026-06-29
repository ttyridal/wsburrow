# TLS Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable `wss://` connections with server cert verification and `--insecure` flag to skip verification.

**Architecture:** `ws_client_connect` gets `use_tls` and `insecure` params to set `ci.ssl_connection`. Config parses `--insecure`. Tunnel threads flags from config to pool to ws_client.

**Tech Stack:** C (lws 4.5.8, OpenSSL), Python (integration test)

**Status: IMPLEMENTED (all tasks complete)**

---

### Task 1: Add `use_tls` and `insecure` parameters to ws_client_connect

- [x] **Step 1: Update function signature in ws_client.h**

```c
int ws_client_connect(struct ws_client *c, const char *host, int port,
                       const char *path, const char *jwt,
                       int use_tls, int insecure);
```

- [x] **Step 2: Update implementation in ws_client.c**

`LCCSCF_SERVER_SSL` does not exist in lws 4.5.8. Use `LCCSCF_USE_SSL` alone.
For `--insecure`, set all four flags: `LCCSCF_ALLOW_SELFSIGNED | LCCSCF_SKIP_SERVER_CERT_HOSTNAME_CHECK | LCCSCF_ALLOW_EXPIRED | LCCSCF_ALLOW_INSECURE`.

```c
    if (use_tls) {
        ci.ssl_connection = LCCSCF_USE_SSL;
        if (insecure)
            ci.ssl_connection |= LCCSCF_ALLOW_SELFSIGNED |
                                 LCCSCF_SKIP_SERVER_CERT_HOSTNAME_CHECK |
                                 LCCSCF_ALLOW_EXPIRED |
                                 LCCSCF_ALLOW_INSECURE;
    }
```

- [x] **Step 3: Verify build**

Expected: build error because tunnel.c calls old signature (confirmed).

---

### Task 2: Add `--insecure` to config

- [x] **Step 1: Add `insecure` field to config struct** (`src/config.h`)
- [x] **Step 2: Parse `--insecure` flag in config.c**
- [x] **Step 3: Verify build** — still fails due to tunnel.c calling old signature (confirmed).

---

### Task 3: Thread use_tls and insecure through tunnel

- [x] **Step 1: Add fields to tunnel_pool** (`src/tunnel.c`)
- [x] **Step 2: Initialize in tunnel_pool_create**
- [x] **Step 3: Pass flags in pool_entry_connect**
- [x] **Step 4: Verify build** — clean build
- [x] **Step 5: Run existing tests** — 3/3 pass (test_config, test_jwt, test_integration)

---

### Task 4: Add integration test for wss:// round-trip

- [x] **Step 1: Generate self-signed cert** (inline in test, temp dir with mkdtemp)
- [x] **Step 2: Add test_tls function to test_integration.py** — uses base=20 port offset to avoid conflicts
- [x] **Step 3: Register test in main()**
- [x] **Step 4: Generate certs and run integration test** — 8/8 tests pass
- [x] **Step 5: Increase ctest timeout** — 120s → 200s (TLS test adds ~10s)
