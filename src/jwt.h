#ifndef JWT_H
#define JWT_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int jwt_encode_reverse_tcp(const char *bind_addr, int bind_port,
                           const char *id, char *out, size_t out_size);

int base64url_encode(const unsigned char *in, size_t in_len,
                     char *out, size_t out_size);

#ifdef __cplusplus
}
#endif

#endif
