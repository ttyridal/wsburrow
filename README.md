# wsBurrow

A lightweight [wstunnel](https://github.com/erebe/wstunnel)-compatible reverse TCP tunnel client for constrained environments. Written in C, designed for OpenWRT.

## Why

[wstunnel](https://github.com/erebe/wstunnel) is a great tool, but the Rust binary is heavy. On routers and embedded devices every kilobyte counts. wsburrow implements the same wire protocol in C with a fraction of the footprint — protocol-compatible with wstunnel v10.5.5 server.

## Features

- **Reverse TCP tunnels** — expose local services through WebSocket tunnels
- **TLS** — plain `ws://` and encrypted `wss://`
- **mTLS** — client certificate authentication (`--client-cert` / `--client-key`)
- **Pooling** — multiple parallel connections per tunnel for resilience (`--pool-size`)
- **Keepalive** — configurable WebSocket ping interval (`--ping-interval`)
- **JWT auth** — tokens in the wstunnel v10.5.5 format
- **No TLS library dependency** — wsburrow itself links zero crypto; TLS is handled by libwebsockets with whichever backend the platform provides (OpenSSL on x86, mbedTLS on OpenWRT)

## Building

### Development (x86 / desktop)

```shell
git clone https://github.com/ttyridal/wsburrow
cd wsburrow
pushd vendor;bash prepare.sh;popd
mkdir build && cd build
cmake ..
make -j$(nproc)
```

This builds local copies of libubox and libwebsockets (4.5.8) so no system libraries beyond `openssl` and `libjson-c` are needed.

### OpenWRT

wsburrow includes an OpenWRT package feed:

```shell
# feeds.conf
src-git wsburrow https://github.com/ttyridal/wsburrow.git
```

Then:

```shell
./scripts/feeds update wsburrow
./scripts/feeds install wsburrow
make package/wsburrow/compile
```

This uses system `libubox` and `libwebsockets` from the OpenWRT feed (with `-DWSBURROW_USE_SYSTEM_LIBS=ON`).

## Usage

```shell
wsburrow [options] ws[s]://server:port
```

note that wsburrow follows the websocket specification. wstunnel needs to be started with --websocket-mask-frame


### Openwrt
```shell
# Configure
uci set wsburrow.main.server_url='ws://tun.example.com:8080'
uci set wsburrow.main.arguments='-R tcp://9090:127.0.0.1:22 --pool-size 1'
uci commit wsburrow
# Start
/etc/init.d/wsburrow enable
/etc/init.d/wsburrow start
```

### Options

| Flag | Description |
|------|-------------|
| `-R tcp://bind:dest:port` | Reverse tunnel (repeatable, up to 16 tunnels) |
| `--pool-size N` | Connections per tunnel (default: 3) |
| `--ping-interval N` | WebSocket ping interval in seconds (default: 15) |
| `--insecure` | Allow self-signed / expired server certificates |
| `--client-cert FILE` | mTLS client certificate |
| `--client-key FILE` | mTLS client private key |

### Examples

```shell
# Basic tunnel — expose localhost:8080 through a WebSocket server
wsburrow -R tcp://8080:localhost:80 ws://tun.example.com:8080

# With TLS and a larger connection pool
wsburrow -R tcp://9090:localhost:22 wss://tun.example.com:443 --pool-size 5

# With mTLS, skipping server cert verification
wsburrow -R tcp::2222:localhost:22 wss://tun.example.com:443 \
  --insecure --client-cert cli.pem --client-key cli-key.pem
```

## Dependencies

### Build-time (vendored for dev, system for OpenWRT)
(downloaded by vendor/prepare.sh)

- [libubox](https://github.com/openwrt/libubox) — event loop (uloop), utilities
- [libwebsockets](https://libwebsockets.org/) v4.5.8 — WebSocket + TLS transport

### Runtime
- OpenSSL (x86) or mbedTLS (OpenWRT) — brought in by libwebsockets; wsburrow has no direct dependency on either

## Testing

```shell
# Unit tests
cd build && ctest -R "test_config|test_jwt" -V

# Integration tests (requires wstunnel v10.5.5 server)
python3 tests/test_integration.py --verbose
```

