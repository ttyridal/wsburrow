#include "config.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>

static int parse_url(struct config *cfg, const char *url)
{
    const char *scheme;

    if (strncmp(url, "ws://", 5) == 0) {
        scheme = url + 5;
        cfg->use_tls = 0;
    } else if (strncmp(url, "wss://", 6) == 0) {
        scheme = url + 6;
        cfg->use_tls = 1;
    } else {
        return -1;
    }

    const char *colon = strchr(scheme, ':');
    if (!colon) return -1;

    size_t hostlen = colon - scheme;
    if (hostlen >= sizeof(cfg->server_host)) return -1;
    memcpy(cfg->server_host, scheme, hostlen);
    cfg->server_host[hostlen] = '\0';

    cfg->server_port = atoi(colon + 1);
    if (cfg->server_port <= 0 || cfg->server_port > 65535) return -1;

    return 0;
}

static int is_ipv4(const char *s)
{
    int dots = 0;
    while (*s) {
        if (*s == '.') dots++;
        else if (!isdigit((unsigned char)*s)) return 0;
        s++;
    }
    return dots == 3;
}

static int parse_reverse_tunnel(struct config *cfg, const char *arg)
{
    if (cfg->num_tunnels >= MAX_TUNNELS) return -1;

    const char *p = arg;
    if (strncmp(p, "tcp://", 6) == 0) p += 6;

    char buf[512];
    strncpy(buf, p, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *parts[4];
    int n = 0;
    char *tok = buf;
    while (tok && n < 4) {
        parts[n++] = tok;
        tok = strchr(tok, ':');
        if (tok) *tok++ = '\0';
    }
    if (n < 3 || n > 4) return -1;

    struct tunnel_cfg *t = &cfg->tunnels[cfg->num_tunnels];

    if (n == 4) {
        strncpy(t->bind_addr, parts[0], sizeof(t->bind_addr) - 1);
        t->bind_port = atoi(parts[1]);
        strncpy(t->dest_host, parts[2], sizeof(t->dest_host) - 1);
        t->dest_port = atoi(parts[3]);
    } else {
        if (is_ipv4(parts[0])) {
            strncpy(t->bind_addr, parts[0], sizeof(t->bind_addr) - 1);
            t->bind_port = atoi(parts[1]);
            strncpy(t->dest_host, parts[2], sizeof(t->dest_host) - 1);
            t->dest_port = atoi(parts[2]);
        } else {
            strncpy(t->bind_addr, "127.0.0.1", sizeof(t->bind_addr) - 1);
            t->bind_port = atoi(parts[0]);
            strncpy(t->dest_host, parts[1], sizeof(t->dest_host) - 1);
            t->dest_port = atoi(parts[2]);
        }
    }

    if (t->bind_port <= 0 || t->bind_port > 65535) return -1;
    if (t->dest_port <= 0 || t->dest_port > 65535) return -1;

    cfg->num_tunnels++;
    return 0;
}

int config_parse(struct config *cfg, int argc, char **argv)
{
    memset(cfg, 0, sizeof(*cfg));
    cfg->pool_size = 3;
    cfg->ping_interval = 15;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-R") == 0) {
            i++;
            if (i >= argc || parse_reverse_tunnel(cfg, argv[i]) != 0)
                return -1;
        } else if (strcmp(argv[i], "--pool-size") == 0) {
            i++;
            if (i >= argc) return -1;
            cfg->pool_size = atoi(argv[i]);
            if (cfg->pool_size < 1) return -1;
        } else if (strcmp(argv[i], "--ping-interval") == 0) {
            i++;
            if (i >= argc) return -1;
            cfg->ping_interval = atoi(argv[i]);
            if (cfg->ping_interval < 1) return -1;
        } else if (argv[i][0] != '-') {
            if (parse_url(cfg, argv[i]) != 0) return -1;
        } else {
            return -1;
        }
    }

    if (cfg->server_port == 0) return -1;
    return 0;
}

void config_free(struct config *cfg)
{
    (void)cfg;
}
