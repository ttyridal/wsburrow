# TLS Stage 2 — Client Certificate Support

> **Goal:** Add `--client-cert <file>` and `--client-key <file>` CLI flags for mTLS client authentication.
>
> **Architecture:** lws 4.5.8 `client_ssl_cert_filepath` / `client_ssl_private_key_filepath` in `lws_context_creation_info`. Config parsing stores paths. Context creation sets them. No ws_client changes needed.
>
> **Tech Stack:** C (lws 4.5.8, OpenSSL), Python (integration test)
>
> **For agentic workers:** Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task.

---

### Task 1: Add `--client-cert` and `--client-key` to config parsing

**Files:**
- Modify: `src/config.h` (add `client_cert[512]`/`client_key[512]`)
- Modify: `src/config.c` (parse flags, validate both-set-or-neither)

**Acceptance:**
- `./build/wsburrow --client-cert foo.pem --client-key bar.key ws://...` parses correctly
- `./build/wsburrow --client-cert foo.pem ws://...` returns error (missing --client-key)
- `./build/wsburrow --client-key bar.key ws://...` returns error (missing --client-cert)
- Existing tests still pass

---

### Task 2: Thread cert paths through main.c to lws context

**Files:**
- Modify: `src/main.c` (set `info.client_ssl_cert_filepath` and `info.client_ssl_private_key_filepath`)

**Acceptance:**
- clean build
- Unit tests pass

---

### Task 3: Add mTLS integration tests

**Files:**
- Modify: `tests/test_integration.py`

**Sub-tasks:**

1. **test_mtls_roundtrip** — Generate CA + server + client cert chain, start wstunnel with `--tls-client-ca-certs`, connect wsburrow with `--client-cert --client-key`, verify data flows.

2. **test_mtls_rejected** — Same wstunnel setup but wsburrow omits `--client-cert` → `LWS_CALLBACK_CLIENT_CONNECTION_ERROR` → wsburrow should exit or log error. Verify non-zero exit or connection timeout.

**Acceptance:**
- 10/10 integration tests pass (8 existing + 2 new)
- Full ctest suite passes

---

### Task 4: Handle client cert rejection as fatal

**Files:**
- Modify: `src/tunnel.c` (detect cert rejection, exit instead of reconnect backoff)

**Approach:**
When all pool connections fail with a client cert configured, treat it as fatal: print error to stderr and `exit(1)`. Detection: in `pool_entry_on_close`, if `pool->client_cert[0]` is set and `e->dead` transitions to 1, increment a `fatal_error` counter. When it reaches `pool_size`, call `exit(1)`.

**Acceptance:**
- Server with `--tls-client-ca-certs` but wsburrow without `--client-cert` → wsburrow exits within 10s
