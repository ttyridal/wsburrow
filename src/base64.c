#include "base64.h"

static const char b64url[64] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

int base64url_encode(const unsigned char *in, size_t in_len,
                     char *out, size_t out_size)
{
    size_t olen = (in_len + 2) / 3 * 4;
    if (out_size < olen + 1)
        return -1;

    size_t i, j;
    for (i = 0, j = 0; i < in_len; i += 3) {
        unsigned int a = in[i];
        unsigned int b = i + 1 < in_len ? in[i + 1] : 0;
        unsigned int c = i + 2 < in_len ? in[i + 2] : 0;
        unsigned int triple = (a << 16) | (b << 8) | c;

        out[j++] = b64url[(triple >> 18) & 0x3F];
        out[j++] = b64url[(triple >> 12) & 0x3F];
        out[j++] = i + 1 < in_len ? b64url[(triple >> 6) & 0x3F] : '\0';
        out[j++] = i + 2 < in_len ? b64url[triple & 0x3F] : '\0';
    }
    out[olen] = '\0';
    while (olen > 0 && out[olen - 1] == '\0')
        out[--olen] = '\0';

    return 0;
}
