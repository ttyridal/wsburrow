cmake_minimum_required(VERSION 3.16)
project(wsburrow C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# libwebsockets sources expect libubox/uloop.h etc with the libubox/ prefix
include_directories(BEFORE
    ${CMAKE_SOURCE_DIR}/vendor/include
)

option(BUILD_TESTS "Build tests" ON)

# Build vendored libubox (needed for uloop integration)
add_subdirectory(vendor/libubox)
# libubox itself uses -Werror, suppress so gcc13 implicit-decl warnings don't break
target_compile_options(ubox PRIVATE -Wno-error=implicit-function-declaration)
target_compile_options(ubox-static PRIVATE -Wno-error=implicit-function-declaration)

# Build vendored libwebsockets 4.5.8 with uloop support compiled in
set(LWS_WITH_ULOOP ON CACHE BOOL "" FORCE)
set(LWS_WITH_EVLIB_PLUGINS OFF CACHE BOOL "" FORCE)
set(LWS_WITHOUT_SERVER ON CACHE BOOL "" FORCE)
set(LWS_WITH_ZLIB OFF CACHE BOOL "" FORCE)
set(LWS_WITH_MINIZ OFF CACHE BOOL "" FORCE)
set(LWS_WITH_PLUGINS OFF CACHE BOOL "" FORCE)
set(LWS_WITH_LWSWS OFF CACHE BOOL "" FORCE)
set(LWS_WITH_SSL ON CACHE BOOL "" FORCE)
set(LWS_WITH_MINIMAL_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LWS_WITHOUT_TESTAPPS ON CACHE BOOL "" FORCE)
set(LWS_WITH_EXPORT_LWSTARGETS OFF CACHE BOOL "" FORCE)
set(CMAKE_INCLUDE_PATH "${CMAKE_SOURCE_DIR}/vendor/include")
add_subdirectory(vendor/libwebsockets-4.5.8 libwebsockets-build)

# lws 4.5.8 missing #include <assert.h> in many files with gcc13
target_compile_options(websockets_shared PRIVATE -include /usr/include/assert.h)
target_compile_options(websockets PRIVATE -include /usr/include/assert.h)
# Ensure libubox is linked into websockets_shared (for uloop builtin)
target_link_libraries(websockets_shared ubox)

# ---- our application ----
find_library(MBEDTLS_LIB mbedtls REQUIRED)
find_library(MBEDCRYPTO_LIB mbedcrypto REQUIRED)
find_path(MBEDTLS_INCLUDE_DIR mbedtls/base64.h)

add_library(wsburrow_lib STATIC
    src/config.c
    src/jwt.c
    src/tunnel.c
    src/ws_client.c
    src/local_tcp.c
)
target_include_directories(wsburrow_lib PUBLIC src)
target_include_directories(wsburrow_lib PRIVATE ${MBEDTLS_INCLUDE_DIR})
target_link_libraries(wsburrow_lib PUBLIC
    websockets_shared
    ${MBEDTLS_LIB}
    ${MBEDCRYPTO_LIB}
    ubox
)

add_executable(wsburrow src/main.c)
target_link_libraries(wsburrow PRIVATE wsburrow_lib)

if(BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
