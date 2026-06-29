#include <gtest/gtest.h>
extern "C" {
#include "config.h"
}

TEST(ConfigTest, ParsesWsUrl) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "-R", "tcp://9090:127.0.0.1:8080",
                          "ws://example.com:8080", nullptr};
    int ret = config_parse(&cfg, 4, (char **)argv);
    ASSERT_EQ(ret, 0);
    ASSERT_STREQ(cfg.server_host, "example.com");
    ASSERT_EQ(cfg.server_port, 8080);
    ASSERT_EQ(cfg.use_tls, 0);
    config_free(&cfg);
}

TEST(ConfigTest, ParsesWssUrl) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "wss://tunnel.example.com:443", nullptr};
    int ret = config_parse(&cfg, 2, (char **)argv);
    ASSERT_EQ(ret, 0);
    ASSERT_STREQ(cfg.server_host, "tunnel.example.com");
    ASSERT_EQ(cfg.server_port, 443);
    ASSERT_EQ(cfg.use_tls, 1);
    config_free(&cfg);
}

TEST(ConfigTest, ParsesReverseTunnel) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "-R", "tcp://9090:127.0.0.1:8080",
                          "ws://s:1", nullptr};
    config_parse(&cfg, 4, (char **)argv);
    ASSERT_EQ(cfg.num_tunnels, 1);
    ASSERT_STREQ(cfg.tunnels[0].bind_addr, "127.0.0.1");
    ASSERT_EQ(cfg.tunnels[0].bind_port, 9090);
    ASSERT_STREQ(cfg.tunnels[0].dest_host, "127.0.0.1");
    ASSERT_EQ(cfg.tunnels[0].dest_port, 8080);
    config_free(&cfg);
}

TEST(ConfigTest, ParsesReverseTunnelWithBindAddr) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "-R",
                          "tcp://0.0.0.0:9090:10.0.0.5:3000",
                          "ws://s:1", nullptr};
    config_parse(&cfg, 4, (char **)argv);
    ASSERT_EQ(cfg.num_tunnels, 1);
    ASSERT_STREQ(cfg.tunnels[0].bind_addr, "0.0.0.0");
    ASSERT_EQ(cfg.tunnels[0].bind_port, 9090);
    ASSERT_STREQ(cfg.tunnels[0].dest_host, "10.0.0.5");
    ASSERT_EQ(cfg.tunnels[0].dest_port, 3000);
    config_free(&cfg);
}

TEST(ConfigTest, ParsesMultipleReverseTunnels) {
    struct config cfg;
    const char *argv[] = {"wsburrow",
        "-R", "tcp://9090:127.0.0.1:8080",
        "-R", "tcp://9091:192.168.1.100:3000",
        "ws://s:1", nullptr};
    config_parse(&cfg, 6, (char **)argv);
    ASSERT_EQ(cfg.num_tunnels, 2);
    ASSERT_EQ(cfg.tunnels[0].bind_port, 9090);
    ASSERT_EQ(cfg.tunnels[1].bind_port, 9091);
    config_free(&cfg);
}

TEST(ConfigTest, ParsesPoolSize) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "--pool-size", "5", "ws://s:1", nullptr};
    config_parse(&cfg, 4, (char **)argv);
    ASSERT_EQ(cfg.pool_size, 5);
    config_free(&cfg);
}

TEST(ConfigTest, ParsesPingInterval) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "--ping-interval", "30",
                          "ws://s:1", nullptr};
    config_parse(&cfg, 4, (char **)argv);
    ASSERT_EQ(cfg.ping_interval, 30);
    config_free(&cfg);
}

TEST(ConfigTest, ReturnsErrorOnMissingUrl) {
    struct config cfg;
    const char *argv[] = {"wsburrow", nullptr};
    int ret = config_parse(&cfg, 1, (char **)argv);
    ASSERT_NE(ret, 0);
}

TEST(ConfigTest, ReturnsErrorOnBadUrl) {
    struct config cfg;
    const char *argv[] = {"wsburrow", "not-a-url", nullptr};
    int ret = config_parse(&cfg, 2, (char **)argv);
    ASSERT_NE(ret, 0);
}
