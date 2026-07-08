#include "local_tcp.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/socket.h>
#include <libubox/usock.h>
#include <libubox/ustream.h>
#include <libubox/list.h>

struct local_tcp {
    struct local_tcp_ops ops;
    struct ustream_fd s_fd;
    struct uloop_fd connect_fd;
    int connecting;
    int closing;
    unsigned char pending[4096];
    int pending_len;
};

static void tcp_read_cb(struct ustream *s, int bytes)
{
    (void)bytes;
    struct ustream_fd *us_fd = container_of(s, struct ustream_fd, stream);
    struct local_tcp *t = container_of(us_fd, struct local_tcp, s_fd);
    if (!t || t->closing) return;

    int len;
    char *buf = ustream_get_read_buf(s, &len);
    if (buf && len > 0) {
        if (t->ops.on_data) {
            int consumed = t->ops.on_data(t->ops.ctx, buf, len);
            if (consumed > 0)
                ustream_consume(s, consumed);
        } else {
            ustream_consume(s, len);
        }
    }
}

static void tcp_state_cb(struct ustream *s)
{
    struct ustream_fd *us_fd = container_of(s, struct ustream_fd, stream);
    struct local_tcp *t = container_of(us_fd, struct local_tcp, s_fd);
    if (!t) return;

    if (s->eof || s->write_error) {
        local_tcp_drain(t);
        if (t->ops.on_close)
            t->ops.on_close(t->ops.ctx);
    }
}

static void conn_fd_cb(struct uloop_fd *fd, unsigned int events)
{
    struct local_tcp *t = container_of(fd, struct local_tcp, connect_fd);
    if (!t) return;

    uloop_fd_delete(fd);

    if (events & ULOOP_WRITE) {
        int err = 0;
        socklen_t elen = sizeof(err);
        if (getsockopt(fd->fd, SOL_SOCKET, SO_ERROR, &err, &elen) == 0
            && err == 0) {
            t->connecting = 0;
            ustream_fd_init(&t->s_fd, fd->fd);
            t->s_fd.stream.notify_read = tcp_read_cb;
            t->s_fd.stream.notify_state = tcp_state_cb;
            t->s_fd.stream.string_data = 1;
            if (t->pending_len > 0) {
                ustream_write(&t->s_fd.stream,
                              t->pending, t->pending_len, 0);
                t->pending_len = 0;
            }
            if (t->ops.on_connect)
                t->ops.on_connect(t->ops.ctx);
        } else {
            if (t->ops.on_close)
                t->ops.on_close(t->ops.ctx);
        }
    }
}

struct local_tcp *local_tcp_create(const struct local_tcp_ops *ops)
{
    struct local_tcp *t = calloc(1, sizeof(*t));
    if (!t) return NULL;
    t->ops = *ops;
    return t;
}

int local_tcp_connect(struct local_tcp *t, const char *host, int port)
{
    char port_str[16];
    snprintf(port_str, sizeof(port_str), "%d", port);

    int fd = usock(USOCK_TCP | USOCK_NONBLOCK, host, port_str);
    if (fd < 0) return -1;

    t->connecting = 1;
    t->connect_fd.fd = fd;
    t->connect_fd.cb = conn_fd_cb;
    uloop_fd_add(&t->connect_fd, ULOOP_WRITE);
    return 0;
}

int local_tcp_send(struct local_tcp *t, const void *data, int len)
{
    if (t->closing) return -1;
    if (t->connecting) {
        int space = sizeof(t->pending) - t->pending_len;
        if (len > space) len = space;
        memcpy(t->pending + t->pending_len, data, len);
        t->pending_len += len;
        return len;
    }
    return ustream_write(&t->s_fd.stream, data, len, 0);
}

void local_tcp_read_blocked(struct local_tcp *t, int blocked)
{
    if (t->closing || t->connecting) return;
    ustream_set_read_blocked(&t->s_fd.stream, blocked);
}

void local_tcp_drain(struct local_tcp *t)
{
    if (t->closing || t->connecting) return;
    struct ustream *s = &t->s_fd.stream;
    int len;
    char *buf;
    while ((buf = ustream_get_read_buf(s, &len)) && len > 0) {
        if (t->ops.on_data) {
            int consumed = t->ops.on_data(t->ops.ctx, buf, len);
            if (consumed > 0)
                ustream_consume(s, consumed);
            else
                break;
        } else {
            ustream_consume(s, len);
        }
    }
}

void local_tcp_destroy(struct local_tcp *t)
{
    if (!t) return;
    t->closing = 1;
    if (t->connecting) {
        uloop_fd_delete(&t->connect_fd);
        if (t->connect_fd.fd >= 0)
            close(t->connect_fd.fd);
    } else {
        int fd = t->s_fd.fd.fd;
        ustream_free(&t->s_fd.stream);
        if (fd >= 0)
            close(fd);
    }
    free(t);
}
