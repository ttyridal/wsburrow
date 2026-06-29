# TLS Stage 2 — Client Certificate Support

> **Goal:** Add `--client-cert <file>` and `--client-key <file>` CLI flags for mTLS client authentication.
>
> **Architecture:** lws 4.5.8 `client_ssl_cert_filepath` / `client_ssl_private_key_filepath` in `lws_context_creation_info`. Config parsing stores paths. Context creation sets them. No ws_client changes needed.
>
> **Tech Stack:** C (lws 4.5.8, OpenSSL), Python (integration test)
>
> **Status: IMPLEMENTED (all tasks complete)**

---

### Task 1: Add `--client-cert` and `--client-key` to config parsing

- [x] Fields `client_cert[512]`/`client_key[512]` in `src/config.h`
- [x] Parse `--client-cert` and `--client-key` in `src/config.c`
- [x] Mutual validation: both-or-neither, returns -1 if mismatch
- [x] Committed in b565120

---

### Task 2: Thread cert paths through main.c to lws context

- [x] `info.client_ssl_cert_filepath` and `info.client_ssl_private_key_filepath` set from config
- [x] NULL when fields are empty (no `--client-cert` provided)
- [x] Committed in b565120

---

### Task 3: Add mTLS integration tests

- [x] `_gen_ca_chain()` helper: generates CA + server + client v3 certs
- [x] v3 certs via `-extfile /dev/stdin` (rustls rejects v1 certs with `UnsupportedCertVersion`)
- [x] **test_mtls_roundtrip** — mTLS with valid client cert, data roundtrip verified
- [x] **test_mtls_rejected** — wstunnel with `--tls-client-ca-certs`, wsburrow without `--client-cert` → exits non-zero
- [x] 10/10 integration tests pass
- [x] Committed in b565120, refined in 0ba5ac3/e66df34

---

### Task 4: Handle client cert rejection as fatal

- [x] **Three fatal exit paths implemented:**
  1. `--client-cert` configured + connection fails before any success → `exit(1)` immediately (server rejected cert)
  2. wss://, no `--client-cert`, never connected, retry_count >= 2 → `exit(1)` (server requires mTLS)
  3. `--client-cert` configured + all pool entries dead → `exit(1)` (redundant with #1, kept for safety)
- [x] Changed from `uloop_end()` to `exit(1)` for non-zero exit code
- [x] Added `ever_connected` flag to `tunnel_pool`
- [x] Committed in 0ba5ac3 and e66df34
