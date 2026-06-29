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

### Error handling

Server rejecting client cert → TLS alert during handshake → `LWS_CALLBACK_CLIENT_CONNECTION_ERROR` callback. In `pool_entry_on_close`, check if `--client-cert` was provided; if so, treat all pool entries failing as fatal → exit. Simpler approach: if any connection fails with client cert configured, print error and exit immediately in `pool_entry_on_close`.

### ws_client.c/h

No changes needed — lws handles cert presentation internally when context is configured.

## Test

Add `test_mtls_roundtrip` integration test:
1. Generate CA key/cert, server cert signed by CA, client cert signed by CA
2. Start wstunnel with `--tls-certificate`, `--tls-private-key`, `--tls-client-ca-certs <ca-cert>`
3. Connect wsburrow with `wss://`, `--client-cert`, `--client-key`
4. Verify data round-trips

Add `test_mtls_rejected` negative test:
1. Same setup but without `--client-cert` → connection fails, wsburrow exits non-zero
