#ifndef LOCAL_TCP_H
#define LOCAL_TCP_H

#ifdef __cplusplus
extern "C" {
#endif

struct local_tcp;

struct local_tcp_ops {
    void (*on_connect)(void *ctx);
    void (*on_data)(void *ctx, const void *data, int len);
    void (*on_close)(void *ctx);
    void *ctx;
};

struct local_tcp *local_tcp_create(const struct local_tcp_ops *ops);
int local_tcp_connect(struct local_tcp *t, const char *host, int port);
int local_tcp_send(struct local_tcp *t, const void *data, int len);
void local_tcp_destroy(struct local_tcp *t);

#ifdef __cplusplus
}
#endif

#endif
