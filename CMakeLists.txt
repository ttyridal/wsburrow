cmake_minimum_required(VERSION 3.16)
project(wsburrow C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

option(BUILD_TESTS "Build tests" ON)
option(WSBURROW_USE_SYSTEM_LIBS "Use system libraries (OpenWRT) instead of vendored" OFF)

if(NOT WSBURROW_USE_SYSTEM_LIBS)
  # libwebsockets sources expect libubox/uloop.h etc with the libubox/ prefix
  include_directories(BEFORE
      ${CMAKE_SOURCE_DIR}/vendor/include
  )
endif()

if(NOT WSBURROW_USE_SYSTEM_LIBS)
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
else()
  find_package(PkgConfig REQUIRED)
  find_path(LIBUBOX_INCLUDE_DIR NAMES libubox/uloop.h)
  find_library(LIBUBOX_LIBRARY NAMES ubox)
  find_library(LIBBLOBMSG_LIBRARY NAMES blobmsg_json)
  pkg_check_modules(LIBWEBSOCKETS REQUIRED libwebsockets)
endif()

# ---- our application ----
add_library(wsburrow_lib STATIC
    src/base64.c
    src/config.c
    src/jwt.c
    src/tunnel.c
    src/ws_client.c
    src/local_tcp.c
)
target_include_directories(wsburrow_lib PUBLIC src)
if(WSBURROW_USE_SYSTEM_LIBS)
  target_include_directories(wsburrow_lib PUBLIC
      ${LIBUBOX_INCLUDE_DIR}
      ${LIBWEBSOCKETS_INCLUDE_DIRS}
  )
  target_link_libraries(wsburrow_lib PUBLIC
      ${LIBWEBSOCKETS_LIBRARIES}
      ${LIBUBOX_LIBRARY}
      ${LIBBLOBMSG_LIBRARY}
  )
else()
  target_link_libraries(wsburrow_lib PUBLIC
      websockets_shared
      ubox
  )
endif()

add_executable(wsburrow src/main.c)
target_link_libraries(wsburrow PRIVATE wsburrow_lib)

set_target_properties(wsburrow PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

if(BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
