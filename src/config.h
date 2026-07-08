#ifndef CONFIG_H
#define CONFIG_H

#include <stddef.h>

#define MAX_TUNNELS 16

struct tunnel_cfg {
    char bind_addr[64];
    int  bind_port;
    char dest_host[256];
    int  dest_port;
};

struct config {
    char server_host[256];
    int  server_port;
    int  use_tls;

    int  verbose;
    int  pool_size;
    int  ping_interval;
    int  insecure;

    int  num_tunnels;
    struct tunnel_cfg tunnels[MAX_TUNNELS];

    char client_cert[512];
    char client_key[512];
};

#ifdef __cplusplus
extern "C" {
#endif

int config_parse(struct config *cfg, int argc, char **argv);
void config_free(struct config *cfg);

#ifdef __cplusplus
}
#endif

#endif
