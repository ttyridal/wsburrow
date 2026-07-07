#include "jwt.h"
#include "base64.h"
#include <string.h>
#include <stdio.h>

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
