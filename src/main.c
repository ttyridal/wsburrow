#include "config.h"
#include "tunnel.h"
#include <libwebsockets.h>
#include <libubox/uloop.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>

static struct lws_context *lwsc;
static struct tunnel_pool **pools;
static int num_pools;

static void sigint_cb(int sig)
{
    (void)sig;
    uloop_end();
}

int main(int argc, char **argv)
{
    struct config cfg;
    int ret = 1;

    if (config_parse(&cfg, argc, argv) != 0) {
        fprintf(stderr, "Usage: wsburrow [options] ws[s]://server:port\n");
        return 1;
    }

    uloop_init();

    signal(SIGINT, sigint_cb);
    signal(SIGTERM, sigint_cb);

    struct lws_context_creation_info info = { 0 };
    info.port = CONTEXT_PORT_NO_LISTEN;
    info.protocols = tunnel_get_protocols();
    info.options = LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT |
                   LWS_SERVER_OPTION_ULOOP;
    info.client_ssl_cert_filepath = cfg.client_cert[0] ? cfg.client_cert : NULL;
    info.client_ssl_private_key_filepath = cfg.client_key[0] ? cfg.client_key : NULL;

    lwsc = lws_create_context(&info);
    if (!lwsc) {
        fprintf(stderr, "Failed to create lws context\n");
        goto cleanup;
    }

    pools = calloc(cfg.num_tunnels, sizeof(*pools));
    if (!pools) goto cleanup;

    for (int i = 0; i < cfg.num_tunnels; i++) {
        pools[i] = tunnel_pool_create(lwsc, &cfg, &cfg.tunnels[i]);
        if (!pools[i])
            fprintf(stderr, "Warning: failed to create tunnel %d\n", i);
        else
            num_pools++;
    }

    if (num_pools == 0) {
        fprintf(stderr, "No tunnels created\n");
        goto cleanup;
    }

    uloop_run();
    ret = 0;

cleanup:
    for (int i = 0; i < num_pools; i++)
        tunnel_pool_destroy(pools[i]);
    free(pools);
    if (lwsc) lws_context_destroy(lwsc);
    uloop_done();
    config_free(&cfg);

    return ret;
}
