include $(TOPDIR)/rules.mk

PKG_NAME:=wsburrow
PKG_VERSION:=1.0
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/ttyridal/wsburrow
PKG_SOURCE_VERSION:=HEAD
PKG_MIRROR_HASH:=971b1f8f2cf0c05ac15f3b893317d5f8d55ad713

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

PKG_BUILD_PARALLEL:=1
PKG_INSTALL:=1

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

define Package/wsburrow
	SECTION:=net
	CATEGORY:=Network
	TITLE:=Wstunnel-compatible WebSocket reverse-tunnel client
	URL:=https://github.com/ttyridal/wsburrow
	DEPENDS:=+libubox +libblobmsg-json +libwebsockets
endef

define Package/wsburrow/description
	A stripped-down wstunnel-compatible C reverse-tunnel client for OpenWRT.
	Protocol-compatible with wstunnel v10.5.5 server.
endef

CMAKE_OPTIONS += -DWSBURROW_USE_SYSTEM_LIBS=ON
CMAKE_OPTIONS += -DBUILD_TESTS=OFF

define Package/wsburrow/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/bin/wsburrow $(1)/usr/bin/
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_DATA) ./files/etc/config/wsburrow $(1)/etc/config/
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/etc/init.d/wsburrow $(1)/etc/init.d/
endef

$(eval $(call BuildPackage,wsburrow))
