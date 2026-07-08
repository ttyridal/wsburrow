#ifndef WS_CLIENT_H
#define WS_CLIENT_H

#include <libwebsockets.h>

#ifdef __cplusplus
extern "C" {
#endif

struct ws_client;

struct ws_client_ops {
    void (*on_connect)(void *ctx);
    void (*on_data)(void *ctx, const void *data, int len);
    void (*on_close)(void *ctx);
    void (*on_pong)(void *ctx);
    void (*on_flush)(void *ctx);
    void *ctx;
};

struct ws_client *ws_client_create(struct lws_context *lwsc,
                                    const struct ws_client_ops *ops);
int ws_client_connect(struct ws_client *c, const char *host, int port,
                       const char *path, const char *jwt,
                       int use_tls, int insecure);
int ws_client_enqueue(struct ws_client *c, const void *data, int len);
int ws_client_ping(struct ws_client *c);
void ws_client_request_write(struct ws_client *c);
struct lws *ws_client_wsi(struct ws_client *c);
void ws_client_destroy(struct ws_client *c);

void ws_set_verbose(int v);

/* lws callback for wsburrow protocol */
int wsburrow_callback(struct lws *wsi, enum lws_callback_reasons reason,
                       void *user, void *in, size_t len);

#ifdef __cplusplus
}
#endif

#endif
