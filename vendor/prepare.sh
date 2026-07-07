#!/bin/sh
curl -o libwebsockets-4.5.8.zip  https://github.com/warmcat/libwebsockets/archive/refs/tags/v4.5.8.zip
unzip libwebsockets-4.5.8.zip -d ./libwebsockets-4.5.8


git init libubox
cd libubox
git remote add origin https://github.com/openwrt/libubox.git
git fetch --depth 1 origin 1fe93d2fefb213ec987763e7e94ce5eaa757bfc3
patch -p1 < ../01-libublox-build-convenience.patch


