#include "tunnel.h"
#include "ws_client.h"
#include "local_tcp.h"
#include "jwt.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <libubox/list.h>
#include <unistd.h>

#define MAX_POOL 32
#define PONG_TIMEOUT_MS  8000
#define BACKOFF_BASE_MS  1000
#define BACKOFF_MAX_MS   30000

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

struct tunnel_pool {
    struct lws_context *lwsc;
    struct tunnel_cfg tcfg;
    char server_host[256];
    int server_port;
    int pool_size;
    int ping_interval;
    int use_tls;
    int insecure;
    int client_cert_set;
    int ever_connected;
    struct pool_entry entries[MAX_POOL];
    struct uloop_timeout ping_timer;
};

static const struct lws_protocols tunnel_protocols[] = {
    { "wsburrow", wsburrow_callback, sizeof(struct ws_client *), 0 },
    { "v1", wsburrow_callback, sizeof(struct ws_client *), 0 },
    { NULL, NULL, 0, 0 }
};

const struct lws_protocols *tunnel_get_protocols(void)
{
    return tunnel_protocols;
}

static void pool_entry_on_pong(void *ctx);
static void pool_entry_on_connect(void *ctx);
static void pool_entry_on_data(void *ctx, const void *data, int len);
static void pool_entry_on_close(void *ctx);
static void pool_entry_on_local_close(void *ctx);
static void pool_entry_on_local_data(void *ctx, const void *data, int len);
static void pool_entry_connect(struct tunnel_pool *pool, int idx);

static void pong_timeout_cb(struct uloop_timeout *t)
{
    struct pool_entry *e = container_of(t, struct pool_entry, pong_timer);
    if (e->ws) {
        e->dead = 1;
        ws_client_destroy(e->ws);
        e->ws = NULL;
        int shift = e->retry_count < 5 ? e->retry_count : 5;
        int delay = BACKOFF_BASE_MS << shift;
        if (delay > BACKOFF_MAX_MS) delay = BACKOFF_MAX_MS;
        e->retry_count++;
        e->reconnect_count++;
        uloop_timeout_set(&e->reconnect_timer, delay);
    }
}

static void entry_reconnect_cb(struct uloop_timeout *t)
{
    struct pool_entry *e = container_of(t, struct pool_entry, reconnect_timer);
    e->dead = 0;
    struct tunnel_pool *pool = e->pool;
    int idx = e - pool->entries;
    pool_entry_connect(pool, idx);
}

static void pool_entry_on_pong(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    uloop_timeout_cancel(&e->pong_timer);
}

static void pool_entry_connect(struct tunnel_pool *pool, int idx)
{
    struct pool_entry *e = &pool->entries[idx];
    if (e->ws) {
        uloop_timeout_cancel(&e->pong_timer);
        ws_client_destroy(e->ws);
    }

    struct ws_client_ops ops = {
        .on_connect = pool_entry_on_connect,
        .on_data = pool_entry_on_data,
        .on_close = pool_entry_on_close,
        .on_pong = pool_entry_on_pong,
        .ctx = e,
    };
    e->ws = ws_client_create(pool->lwsc, &ops);
    if (!e->ws) return;

    e->pong_timer.cb = pong_timeout_cb;
    e->reconnect_timer.cb = entry_reconnect_cb;

    if (ws_client_connect(e->ws, pool->server_host, pool->server_port,
                          "/v1/events", e->jwt,
                          pool->use_tls, pool->insecure) != 0) {
        ws_client_destroy(e->ws);
        e->ws = NULL;
        e->dead = 1;
        uloop_timeout_set(&e->reconnect_timer, BACKOFF_BASE_MS);
    }
}

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

struct tunnel_pool *tunnel_pool_create(struct lws_context *lwsc,
                                        const struct config *cfg,
                                        const struct tunnel_cfg *tcfg)
{
    struct tunnel_pool *pool = calloc(1, sizeof(*pool));
    if (!pool) return NULL;

    pool->lwsc = lwsc;
    pool->tcfg = *tcfg;
    strncpy(pool->server_host, cfg->server_host, sizeof(pool->server_host) - 1);
    pool->server_port = cfg->server_port;
    pool->pool_size = cfg->pool_size;
    pool->ping_interval = cfg->ping_interval;
    pool->use_tls = cfg->use_tls;
    pool->insecure = cfg->insecure;
    pool->client_cert_set = cfg->client_cert[0] ? 1 : 0;
    if (pool->pool_size > MAX_POOL) pool->pool_size = MAX_POOL;

    char jwt[512];
    jwt_encode_reverse_tcp(tcfg->bind_addr, tcfg->bind_port, jwt, sizeof(jwt));

    for (int i = 0; i < pool->pool_size; i++) {
        pool->entries[i].pool = pool;
        strncpy(pool->entries[i].jwt, jwt, sizeof(pool->entries[i].jwt) - 1);
        pool_entry_connect(pool, i);
    }

    pool->ping_timer.cb = ping_cb;
    uloop_timeout_set(&pool->ping_timer, pool->ping_interval * 1000);

    return pool;
}

void tunnel_pool_destroy(struct tunnel_pool *pool)
{
    if (!pool) return;
    uloop_timeout_cancel(&pool->ping_timer);
    for (int i = 0; i < pool->pool_size; i++) {
        uloop_timeout_cancel(&pool->entries[i].pong_timer);
        uloop_timeout_cancel(&pool->entries[i].reconnect_timer);
        if (pool->entries[i].local)
            local_tcp_destroy(pool->entries[i].local);
        if (pool->entries[i].ws)
            ws_client_destroy(pool->entries[i].ws);
    }
    free(pool);
}

static void pool_entry_on_connect(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    e->pool->ever_connected = 1;
    e->retry_count = 0;
}

static void pool_entry_on_data(void *ctx, const void *data, int len)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    if (e->dead) return;
    e->rx_bytes += len;

    if (!e->local) {
        e->active = 1;
        struct local_tcp_ops lops = {
            .on_data = pool_entry_on_local_data,
            .on_close = pool_entry_on_local_close,
            .ctx = e,
        };
        struct local_tcp *t = local_tcp_create(&lops);
        if (t) {
            e->local = t;
            local_tcp_connect(t, e->pool->tcfg.dest_host,
                              e->pool->tcfg.dest_port);
            local_tcp_send(t, data, len);
        }
    } else {
        local_tcp_send(e->local, data, len);
    }
}

static void pool_entry_on_close(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    uloop_timeout_cancel(&e->pong_timer);
    e->dead = 1;

    if (e->pool->client_cert_set && !e->pool->ever_connected) {
        fprintf(stderr, "error: connection failed with client cert configured\n");
        exit(1);
    }

    int all_dead = 1;
    for (int i = 0; i < e->pool->pool_size; i++)
        if (!e->pool->entries[i].dead)
            all_dead = 0;

    if (all_dead) {
        if (e->pool->use_tls && !e->pool->ever_connected && e->retry_count >= 2) {
            fprintf(stderr, "error: server likely requires client certificate (--client-cert)\n");
            exit(1);
        }
    }

    int shift = e->retry_count < 5 ? e->retry_count : 5;
    int delay = BACKOFF_BASE_MS << shift;
    if (delay > BACKOFF_MAX_MS) delay = BACKOFF_MAX_MS;
    e->retry_count++;
    e->reconnect_count++;
    uloop_timeout_set(&e->reconnect_timer, delay);
}

static void pool_entry_on_local_close(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    local_tcp_destroy(e->local);
    e->local = NULL;
    e->active = 0;
}

static void pool_entry_on_local_data(void *ctx, const void *data, int len)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    e->tx_bytes += len;
    if (e->ws)
        ws_client_enqueue(e->ws, data, len);
}
