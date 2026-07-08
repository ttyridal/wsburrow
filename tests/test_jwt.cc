#include <gtest/gtest.h>
#include <cstring>
extern "C" {
#include "jwt.h"
}

TEST(JwtTest, Base64urlEncode) {
    char out[64];
    int ret = base64url_encode((const unsigned char *)"f", 1, out, sizeof(out));
    ASSERT_EQ(ret, 0);
    ASSERT_STREQ(out, "Zg");
}

TEST(JwtTest, Base64urlEncodeNoPadding) {
    char out[64];
    base64url_encode((const unsigned char *)"foobar", 6, out, sizeof(out));
    ASSERT_STREQ(out, "Zm9vYmFy");
}

TEST(JwtTest, Base64urlReplacesChars) {
    char out[64];
    unsigned char in[] = {0xFF, 0xFB, 0xFF, 0x00};
    base64url_encode(in, 4, out, sizeof(out));
    ASSERT_EQ(strchr(out, '+'), nullptr);
    ASSERT_EQ(strchr(out, '/'), nullptr);
    ASSERT_EQ(strchr(out, '='), nullptr);
}

TEST(JwtTest, EncodesReverseTcpToken) {
    char jwt[512];
    int ret = jwt_encode_reverse_tcp("127.0.0.1", 9090, "testid01", jwt, sizeof(jwt));
    ASSERT_EQ(ret, 0);

    int dots = 0;
    for (const char *p = jwt; *p; p++)
        if (*p == '.') dots++;
    ASSERT_EQ(dots, 2);

    const char *dot1 = strchr(jwt, '.');
    ASSERT_TRUE(dot1 != nullptr);
    const char *dot2 = strchr(dot1 + 1, '.');
    ASSERT_TRUE(dot2 != nullptr);

    size_t payload_len = dot2 - dot1 - 1;
    ASSERT_GT(payload_len, 0);

    ASSERT_EQ(strchr(jwt, '='), nullptr);
}

TEST(JwtTest, EncodesDifferentBindAddr) {
    char jwt[512];
    jwt_encode_reverse_tcp("0.0.0.0", 9091, "testid02", jwt, sizeof(jwt));
    ASSERT_GT(strlen(jwt), 0);
}

TEST(JwtTest, FailsOnSmallBuffer) {
    char small[10];
    int ret = jwt_encode_reverse_tcp("127.0.0.1", 9090, "testid03", small, sizeof(small));
    ASSERT_NE(ret, 0);
}
