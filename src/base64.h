#ifndef BASE64_H
#define BASE64_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int base64url_encode(const unsigned char *in, size_t in_len,
                     char *out, size_t out_size);

#ifdef __cplusplus
}
#endif

#endif
