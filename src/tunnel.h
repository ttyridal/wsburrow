#ifndef TUNNEL_H
#define TUNNEL_H

#include "config.h"
#include <libwebsockets.h>
#include <libubox/uloop.h>

#ifdef __cplusplus
extern "C" {
#endif

struct tunnel_pool;

struct tunnel_pool *tunnel_pool_create(struct lws_context *lwsc,
                                        const struct config *cfg,
                                        const struct tunnel_cfg *tcfg);
void tunnel_pool_destroy(struct tunnel_pool *pool);
const struct lws_protocols *tunnel_get_protocols(void);

#ifdef __cplusplus
}
#endif

#endif
