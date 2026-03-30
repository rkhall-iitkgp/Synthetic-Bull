# ──────────────────────────────────────────────────────────────────────────────
# Synthetic-Bull  ·  Backend Dockerfile
# 3-stage: deps → build → runtime
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Fetch and build dependencies ─────────────────────────────────────
FROM ubuntu:22.04 AS deps

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    git \
    g++ \
    make \
    cmake \
    libssl-dev \
    zlib1g-dev \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /deps

# Clone uWebSockets + uSockets
RUN git clone --depth 1 https://github.com/uNetworking/uWebSockets.git && \
    cd uWebSockets && \
    git submodule update --init --depth 1

# Build uSockets static library
RUN cd uWebSockets/uSockets && \
    make -j$(nproc) WITH_OPENSSL=1

# Clone nlohmann/json (header-only)
RUN git clone --depth 1 --branch v3.11.3 https://github.com/nlohmann/json.git

# ── Stage 2: Build the project ────────────────────────────────────────────────
FROM deps AS build

WORKDIR /app

# Copy source code
COPY CMakeLists.txt .
COPY include/ include/
COPY src/ src/

# Symlink dependencies into the expected location
RUN mkdir -p deps && \
    ln -s /deps/uWebSockets deps/uWebSockets && \
    ln -s /deps/json deps/json

# Build
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build --parallel $(nproc)

# ── Stage 3: Minimal runtime image ────────────────────────────────────────────
FROM ubuntu:22.04 AS runtime

RUN apt-get update && apt-get install -y \
    libssl3 \
    zlib1g \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /app/build/SyntheticBull .

EXPOSE 9001

CMD ["./SyntheticBull"]
