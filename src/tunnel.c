#include "tunnel.h"
#include "ws_client.h"
#include "local_tcp.h"
#include "jwt.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <libubox/list.h>

#define MAX_POOL 32

struct pool_entry {
    struct tunnel_pool *pool;
    struct ws_client *ws;
    struct local_tcp *local;
    int active;
    int dead;
    char jwt[512];
};

struct tunnel_pool {
    struct lws_context *lwsc;
    struct tunnel_cfg tcfg;
    char server_host[256];
    int server_port;
    int pool_size;
    int ping_interval;
    struct pool_entry entries[MAX_POOL];
    struct uloop_timeout ping_timer;
    struct uloop_timeout reconnect_timer;
    int reconnecting;
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

static void pool_entry_on_connect(void *ctx);
static void pool_entry_on_data(void *ctx, const void *data, int len);
static void pool_entry_on_close(void *ctx);
static void pool_entry_on_local_close(void *ctx);
static void pool_entry_on_local_data(void *ctx, const void *data, int len);

static void pool_entry_connect(struct tunnel_pool *pool, int idx)
{
    struct pool_entry *e = &pool->entries[idx];
    if (e->ws) ws_client_destroy(e->ws);

    struct ws_client_ops ops = {
        .on_connect = pool_entry_on_connect,
        .on_data = pool_entry_on_data,
        .on_close = pool_entry_on_close,
        .ctx = e,
    };
    e->ws = ws_client_create(pool->lwsc, &ops);
    if (!e->ws) return;

    ws_client_connect(e->ws, pool->server_host, pool->server_port,
                      "/v1/events", e->jwt);
}

static void ping_cb(struct uloop_timeout *t)
{
    struct tunnel_pool *pool = container_of(t, struct tunnel_pool, ping_timer);
    for (int i = 0; i < pool->pool_size; i++) {
        if (pool->entries[i].ws)
            ws_client_ping(pool->entries[i].ws);
    }
    uloop_timeout_set(t, pool->ping_interval * 1000);
}

static void reconnect_cb(struct uloop_timeout *t)
{
    struct tunnel_pool *pool = container_of(t, struct tunnel_pool, reconnect_timer);
    pool->reconnecting = 0;
    for (int i = 0; i < pool->pool_size; i++) {
        if (pool->entries[i].dead || !pool->entries[i].ws) {
            pool->entries[i].dead = 0;
            pool_entry_connect(pool, i);
        }
    }
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
    uloop_timeout_cancel(&pool->reconnect_timer);
    for (int i = 0; i < pool->pool_size; i++) {
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
    (void)e;
}

static void pool_entry_on_data(void *ctx, const void *data, int len)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    struct tunnel_pool *pool = e->pool;

    for (int i = 0; i < pool->pool_size; i++) {
        if (pool->entries[i].ws != e->ws) continue;

        if (!pool->entries[i].local) {
            pool->entries[i].active = 1;
            struct local_tcp_ops lops = {
                .on_data = pool_entry_on_local_data,
                .on_close = pool_entry_on_local_close,
                .ctx = &pool->entries[i],
            };
            struct local_tcp *t = local_tcp_create(&lops);
            if (t) {
                pool->entries[i].local = t;
                local_tcp_connect(t, pool->tcfg.dest_host,
                                  pool->tcfg.dest_port);
                local_tcp_send(t, data, len);
            }
        } else {
            local_tcp_send(pool->entries[i].local, data, len);
        }
        return;
    }
}

static void pool_entry_on_close(void *ctx)
{
    struct pool_entry *e = (struct pool_entry *)ctx;
    e->dead = 1;

    struct tunnel_pool *pool = e->pool;
    if (!pool->reconnecting) {
        pool->reconnecting = 1;
        pool->reconnect_timer.cb = reconnect_cb;
        uloop_timeout_set(&pool->reconnect_timer, 1000);
    }
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
    if (e->ws)
        ws_client_enqueue(e->ws, data, len);
}
