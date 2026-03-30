cmake_minimum_required(VERSION 3.16)
project(SyntheticBull LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── Sources ──
set(SOURCES
    src/OrderBook.cpp
    src/MatchingEngine.cpp
    src/MarketSimulator.cpp
    src/CandleAggregator.cpp
    src/main.cpp
)

add_executable(SyntheticBull ${SOURCES})

# ── Include paths ──
target_include_directories(SyntheticBull PRIVATE
    ${CMAKE_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/deps/uWebSockets/src
    ${CMAKE_SOURCE_DIR}/deps/uWebSockets/uSockets/src
    ${CMAKE_SOURCE_DIR}/deps/json/include
)

# ── uSockets static library ──
target_link_libraries(SyntheticBull PRIVATE
    ${CMAKE_SOURCE_DIR}/deps/uWebSockets/uSockets/uSockets.a
)

# ── System libraries ──
find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(SQLite3 REQUIRED)

target_link_libraries(SyntheticBull PRIVATE
    Threads::Threads
    ZLIB::ZLIB
    OpenSSL::SSL
    OpenSSL::Crypto
    SQLite::SQLite3
)

# ── Compiler flags ──
target_compile_options(SyntheticBull PRIVATE
    -Wall -Wextra -O2
)
