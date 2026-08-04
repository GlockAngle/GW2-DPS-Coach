cmake_minimum_required(VERSION 3.12)

project(gw2combat LANGUAGES C CXX)

include_directories(src include)

###
# Dependencies
###
include(FetchContent)

FetchContent_Declare(
    Boost
    GIT_REPOSITORY https://github.com/boostorg/boost.git
    GIT_TAG boost-1.83.0
)

FetchContent_MakeAvailable(Boost)

set(nlohmann-json_IMPLICIT_CONVERSIONS OFF)

###
# Compiler configuration
###
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
    add_compile_options(
        /W4
        /permissive-
        /bigobj
    )

    add_compile_definitions(
        _WIN32_WINNT=0x0A00
        WIN32_LEAN_AND_MEAN
        NOMINMAX
    )
else()
    add_compile_options(
        -Wall
        -Wextra
        -Wpedantic
        -Wno-deprecated
    )

    set(CMAKE_CXX_FLAGS_DEBUG
        "${CMAKE_CXX_FLAGS_DEBUG} -g3 -fno-omit-frame-pointer"
    )

    set(CMAKE_CXX_FLAGS_RELEASE
        "${CMAKE_CXX_FLAGS_RELEASE} -O3"
    )
endif()

###
# Tests
###
enable_testing()

add_test(
    NAME gw2combat_test_build
    COMMAND "${CMAKE_COMMAND}"
        --build "${CMAKE_BINARY_DIR}"
        --config Release
        --target gw2combat_test
)

add_test(
    NAME gw2combat_test_run
    COMMAND gw2combat_test
)

set_tests_properties(
    gw2combat_test_run
    PROPERTIES DEPENDS gw2combat_test_build
)

###
# Targets
###
file(
    GLOB gw2combat_src
    CONFIGURE_DEPENDS
    "src/main.cpp"
    "src/combat_loop.cpp"
    "src/server_tcp.cpp"
    "src/*/*.cpp"
    "src/*.hpp"
    "src/*/*.hpp"
)

file(
    GLOB gw2combat_http_src
    CONFIGURE_DEPENDS
    "src/main_http.cpp"
    "src/combat_loop.cpp"
    "src/server_http.cpp"
    "src/*/*.cpp"
    "src/*.hpp"
    "src/*/*.hpp"
)

add_executable(gw2combat ${gw2combat_src})
add_executable(gw2combat_http ${gw2combat_http_src})

target_link_libraries(
    gw2combat_http
    PRIVATE
    Boost::beast
    Boost::url
)

if(WIN32)
    target_link_libraries(
        gw2combat
        PRIVATE
        ws2_32
    )

    target_link_libraries(
        gw2combat_http
        PRIVATE
        ws2_32
    )
elseif(NOT APPLE)
    target_link_options(gw2combat PRIVATE -static)
    target_link_options(gw2combat_http PRIVATE -static)
endif()