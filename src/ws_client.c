#include "ws_client.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define PENDING_MAX 4096

struct ws_client {
    struct lws_context *lwsc;
    struct lws *wsi;
    struct ws_client_ops ops;
    char jwt[512];
    char host[256];
    int port;
    char path[128];
    unsigned char pending[LWS_PRE + PENDING_MAX];
    int pending_len;
    int closing;
    int need_ping;
};

struct ws_client *ws_client_create(struct lws_context *lwsc,
                                    const struct ws_client_ops *ops)
{
    struct ws_client *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->lwsc = lwsc;
    c->ops = *ops;
    return c;
}

int ws_client_connect(struct ws_client *c, const char *host, int port,
                       const char *path, const char *jwt,
                       int use_tls, int insecure)
{
    strncpy(c->host, host, sizeof(c->host) - 1);
    c->port = port;
    strncpy(c->path, path, sizeof(c->path) - 1);
    strncpy(c->jwt, jwt, sizeof(c->jwt) - 1);

    char proto[640];
    int n = snprintf(proto, sizeof(proto),
        "v1, authorization.bearer.%s", c->jwt);
    if (n <= 0 || n >= (int)sizeof(proto))
        return -1;

    struct lws_client_connect_info ci = { 0 };
    ci.context = c->lwsc;
    ci.address = c->host;
    ci.port = c->port;
    ci.path = c->path;
    ci.host = c->host;
    ci.origin = c->host;
    ci.protocol = proto;
    ci.ietf_version_or_minus_one = -1;
    ci.opaque_user_data = c;
    if (use_tls) {
        ci.ssl_connection = LCCSCF_USE_SSL;
        if (insecure)
            ci.ssl_connection |= LCCSCF_ALLOW_SELFSIGNED |
                                 LCCSCF_SKIP_SERVER_CERT_HOSTNAME_CHECK |
                                 LCCSCF_ALLOW_EXPIRED |
                                 LCCSCF_ALLOW_INSECURE;
    }

    c->wsi = lws_client_connect_via_info(&ci);
    return c->wsi ? 0 : -1;
}

int ws_client_enqueue(struct ws_client *c, const void *data, int len)
{
    if (c->closing || !c->wsi) return -1;
    int space = PENDING_MAX - c->pending_len;
    if (len > space) len = space;
    memcpy(c->pending + LWS_PRE + c->pending_len, data, len);
    c->pending_len += len;
    lws_callback_on_writable(c->wsi);
    return len;
}

int ws_client_ping(struct ws_client *c)
{
    if (!c->wsi || c->closing) {
        fprintf(stderr, "debug: ping aborted (wsi=%p closing=%d)\n",
                (void *)c->wsi, c->closing);
        return -1;
    }
    c->need_ping = 1;
    lws_callback_on_writable(c->wsi);
    return 0;
}

void ws_client_request_write(struct ws_client *c)
{
    if (c->wsi) lws_callback_on_writable(c->wsi);
}

struct lws *ws_client_wsi(struct ws_client *c)
{
    return c->wsi;
}

void ws_client_destroy(struct ws_client *c)
{
    if (!c) return;
    if (c->wsi) {
        c->closing = 1;
        lws_set_opaque_user_data(c->wsi, NULL);
        lws_wsi_close(c->wsi, LWS_TO_KILL_ASYNC);
    }
    free(c);
}

int wsburrow_callback(struct lws *wsi, enum lws_callback_reasons reason,
                       void *user, void *in, size_t len)
{
    struct ws_client *c = (struct ws_client *)lws_get_opaque_user_data(wsi);
    (void)user;

    switch (reason) {
    case LWS_CALLBACK_CLIENT_ESTABLISHED:
    case LWS_CALLBACK_ESTABLISHED_CLIENT_HTTP:
        if (c) {
            if (c->ops.on_connect)
                c->ops.on_connect(c->ops.ctx);
        }
        break;

    case LWS_CALLBACK_CLIENT_RECEIVE:
    case LWS_CALLBACK_RECEIVE_CLIENT_HTTP:
        if (c && c->ops.on_data)
            c->ops.on_data(c->ops.ctx, in, len);
        break;

    case LWS_CALLBACK_CLIENT_WRITEABLE:
    case LWS_CALLBACK_CLIENT_HTTP_WRITEABLE: {
        struct ws_client *c2 = (struct ws_client *)lws_get_opaque_user_data(wsi);
        if (!c2) break;
        if (c2->need_ping) {
            c2->need_ping = 0;
            unsigned char ping[LWS_PRE];
            lws_write(wsi, ping + LWS_PRE, 0, LWS_WRITE_PING);
        }
        if (c2->pending_len > 0) {
            int n = lws_write(wsi, c2->pending + LWS_PRE,
                              c2->pending_len, LWS_WRITE_BINARY);
            if (n > 0) {
                int rem = c2->pending_len - n;
                if (rem > 0)
                    memmove(c2->pending + LWS_PRE,
                            c2->pending + LWS_PRE + n, rem);
                c2->pending_len = rem;
            }
            if (c2->pending_len > 0) {
                lws_callback_on_writable(wsi);
            } else if (c2->ops.on_flush) {
                c2->ops.on_flush(c2->ops.ctx);
            }
        }
        break;
    }

    case LWS_CALLBACK_CLIENT_CLOSED:
    case LWS_CALLBACK_CLOSED_CLIENT_HTTP:
        if (c) {
            c->wsi = NULL;
            if (c->ops.on_close)
                c->ops.on_close(c->ops.ctx);
        }
        break;

    case LWS_CALLBACK_CLIENT_CONNECTION_ERROR:
        if (c) {
            c->wsi = NULL;
            if (c->ops.on_close)
                c->ops.on_close(c->ops.ctx);
        }
        break;

    case LWS_CALLBACK_WS_CLIENT_BIND_PROTOCOL:
        break;

    case LWS_CALLBACK_CLIENT_FILTER_PRE_ESTABLISH:
        break;

    case LWS_CALLBACK_CLIENT_RECEIVE_PONG:
        fprintf(stderr, "debug: received ws pong\n");
        if (c && c->ops.on_pong)
            c->ops.on_pong(c->ops.ctx);
        break;

    default:
        break;
    }
    return 0;
}
