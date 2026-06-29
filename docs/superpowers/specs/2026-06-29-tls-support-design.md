# TLS Support — Stage 1 (wss:// + --insecure) [IMPLEMENTED]

## Problem

wsburrow supports only `ws://` connections. `wss://` URLs are parsed but rejected at connect because `ci.ssl_connection` is hardcoded to 0.

## Scope

Stage 1: enable TLS client connections with server cert verification. Add `--insecure` flag to skip verification. Server cert failures are transient (connection error → backoff reconnect).

Stage 2 (future): mTLS client certificate authentication (`--client-cert`, `--client-key`). Client cert rejection is fatal (no retry).

## Changes

### ws_client.h/c

Add `use_tls` parameter to `ws_client_connect()`:

```c
int ws_client_connect(struct ws_client *c, const char *host, int port,
                       const char *path, const char *jwt, int use_tls);
```

When `use_tls` is non-zero, set `ci.ssl_connection = LCCSCF_USE_SSL`.  
When `insecure` flag is also set, add `LCCSCF_ALLOW_SELFSIGNED | LCCSCF_SKIP_SERVER_CERT_HOSTNAME_CHECK | LCCSCF_ALLOW_EXPIRED | LCCSCF_ALLOW_INSECURE`.

> Note: `LCCSCF_SERVER_SSL` does not exist in lws 4.5.8. `LCCSCF_ALLOW_INSECURE` alone is insufficient for self-signed certs — must set all four flags.

### config.h/c

Add `int insecure;` to `struct config`.  
Parse `--insecure` flag.

### tunnel.c

`pool_entry_connect()` passes `cfg->use_tls` and `cfg->insecure` through to `ws_client_connect()`.  
`tunnel_pool_create()` passes `cfg->use_tls` and `cfg->insecure` into pool.

`struct tunnel_pool` gains `int use_tls; int insecure;` fields.

### Error handling

Server cert failure → `LWS_CALLBACK_CLIENT_CONNECTION_ERROR` → `pool_entry_on_close` → backoff reconnect. No code change needed — this path already exists.

## Build

No build changes. lws is already built with `LWS_WITH_SSL=ON` and links OpenSSL. `LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT` is already set in `main.c`.

## Test

Add `test_tls` integration test: start wstunnel with `wss://` (needs self-signed cert/key), connect wsburrow with `wss://`, verify data round-trips.

Skip verification: `--insecure`.
