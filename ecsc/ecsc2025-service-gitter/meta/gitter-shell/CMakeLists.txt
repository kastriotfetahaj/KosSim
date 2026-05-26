project(gitter-shell)
cmake_minimum_required(VERSION 3.28)
set(CMAKE_CXX_FLAGS "-Wall -Wextra -stdlib=libc++")

set(CPR_ENABLE_SSL OFF)
set(CPR_USE_SYSTEM_CURL ON)
set(CPR_BUILD_SHARED_LIBS OFF)

include(FetchContent)
FetchContent_Declare(cpr GIT_REPOSITORY https://github.com/libcpr/cpr.git
  GIT_TAG dec9422db3af470641f8b0d90e4b451c4daebf64)
FetchContent_MakeAvailable(cpr)

add_executable(gitter-shell src/main.cpp)
target_link_libraries(gitter-shell PRIVATE cpr::cpr crypto)
