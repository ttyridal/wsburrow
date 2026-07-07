include $(TOPDIR)/rules.mk

PKG_NAME:=wsburrow
PKG_VERSION:=1.0
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/yourorg/wsburrow
PKG_SOURCE_VERSION:=HEAD
PKG_MIRROR_HASH:=

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

PKG_BUILD_PARALLEL:=1
PKG_INSTALL:=1

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

define Package/wsburrow
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Wstunnel-compatible WebSocket reverse-tunnel client
  URL:=https://github.com/yourorg/wsburrow
  DEPENDS:=+libubox +libwebsockets
endef

define Package/wsburrow/description
  A stripped-down wstunnel-compatible C reverse-tunnel client for OpenWRT.
  Protocol-compatible with wstunnel v10.5.5 server.
endef

CMAKE_OPTIONS += -DWSBURROW_USE_SYSTEM_LIBS=ON
CMAKE_OPTIONS += -DBUILD_TESTS=OFF

define Build/InstallDev
  $(INSTALL_DIR) $(1)/usr/include
  $(CP) $(PKG_BUILD_DIR)/src/*.h $(1)/usr/include/
endef

define Package/wsburrow/install
  $(INSTALL_DIR) $(1)/usr/bin
  $(INSTALL_BIN) $(PKG_BUILD_DIR)/wsburrow $(1)/usr/bin/
endef

$(eval $(call BuildPackage,wsburrow))
