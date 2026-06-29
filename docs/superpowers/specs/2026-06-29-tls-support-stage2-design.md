# TLS Support — Stage 2 (Client Certificates)

## Problem

Some wstunnel servers require client certificate authentication (mTLS). wsburrow needs to present a client certificate and private key when connecting to such servers.

## Scope

Stage 2: Add `--client-cert` and `--client-key` CLI flags. Set the paths in `lws_context_creation_info` so lws presents the cert during TLS handshake. Client cert rejection by server is a fatal error (no reconnect backoff).

## Key Decisions

1. **Context-level setting** — lws 4.5.8 configures client certs at context creation via `client_ssl_cert_filepath` and `client_ssl_private_key_filepath` in `lws_context_creation_info`. Apply to all client connections from this context.

2. **Fatal on rejection** — If the server rejects the client cert (TLS alert during handshake), wsburrow exits. Per original spec: "Client cert rejection is fatal (no retry)."

3. **Build** — No build changes needed. lws 4.5.8 already supports `client_ssl_cert_filepath`/`client_ssl_private_key_filepath` fields with OpenSSL backend.

## Changes

### config.h/c

Add to `struct config`:
```c
    char client_cert[512];
    char client_key[512];
```

Parse:
- `--client-cert <file>` → `cfg->client_cert`
- `--client-key <file>` → `cfg->client_key`

Both must be set if either is given (validate in `config_parse`).

### main.c

After `struct lws_context_creation_info info = { 0 };`, set:
```c
    info.client_ssl_cert_filepath = cfg->client_cert[0] ? cfg->client_cert : NULL;
    info.client_ssl_private_key_filepath = cfg->client_key[0] ? cfg->client_key : NULL;
```

### Error handling (actual implementation)

Three fatal exit paths in `pool_entry_on_close` in `src/tunnel.c`:

1. **Client cert configured, never connected:** `--client-cert` is set and `!ever_connected` → `exit(1)` immediately on first connection failure. Covers server rejecting the client cert.
2. **No client cert, TLS, never connected:** `use_tls && !client_cert_set && !ever_connected && retry_count >= 2` → `exit(1)` after 3 failed retry cycles (~3s). Covers server requiring mTLS when wsburrow has no cert.
3. **All entries dead with client cert:** `client_cert_set && all_dead` → `exit(1)`. Safety net in case path #1 doesn't trigger (e.g., transient failure recovered then all entries die later).

Key design: `ever_connected` flag on `tunnel_pool` is set true when any pool entry successfully connects. `exit(1)` is used instead of `uloop_end()` to ensure non-zero exit code.

### ws_client.c/h

No changes needed — lws handles cert presentation internally when context is configured.

## Test (actual implementation)

`tests/test_integration.py` has a `_gen_ca_chain()` helper that generates CA + server + client cert chain. **Important: v3 certs required.** Rustls (wstunnel's TLS library) rejects v1 certs with `UnsupportedCertVersion`. Use `openssl x509 -req -extfile /dev/stdin` with proper extensions to force v3.

Two mTLS tests added:

1. **`test_mtls_roundtrip`** — Generate CA chain (v3), start wstunnel with `--tls-certificate`, `--tls-private-key`, `--tls-client-ca-certs`, connect wsburrow with `wss://`, `--client-cert`, `--client-key`. Verify data round-trips. Uses base=40 port offset.

2. **`test_mtls_rejected`** — Same wstunnel setup but wsburrow omits `--client-cert` → connection fails during TLS → exits non-zero after 3 retry cycles. Uses base=41 port offset.
