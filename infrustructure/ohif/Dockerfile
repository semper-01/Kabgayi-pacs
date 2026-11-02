# syntax=docker/dockerfile:1.7-labs
FROM node:24.15.0-slim@sha256:152aceace5c03e2597988763165ee33e3fd3633636db0fc983cd2e126b02cfde AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates git python3 \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global pnpm@12.8.1

RUN git clone --depth 1 --branch v3.13.12 https://github.com/OHIF/Viewers.git /usr/src/app \
    && test "$(git -C /usr/src/app rev-parse HEAD)" = "e844561fa487dc8f572643b6aa6584fd806e60d3"

WORKDIR /usr/src/app
COPY patches/ ./patches/kabgayi/
COPY scripts/prepare-source.mjs /tmp/prepare-source.mjs
COPY tests/verify-hotfixes.mjs /tmp/verify-hotfixes.mjs

RUN node /tmp/prepare-source.mjs /usr/src/app \
    && pnpm install --no-frozen-lockfile

ENV QUICK_BUILD=true \
    PUBLIC_URL=/ \
    NODE_OPTIONS=--max-old-space-size=24576

RUN pnpm run build \
    && node /tmp/verify-hotfixes.mjs /usr/src/app \
    && chmod u+x .docker/compressDist.sh \
    && ./.docker/compressDist.sh

FROM ohif/app:v3.13.12@sha256:2710da0c2893692f43bae6a70992623065a0edd849ae20412fc862e0f2b30aa5 AS runtime

USER root
RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder --chown=nginx:nginx /usr/src/app/platform/app/dist/ /usr/share/nginx/html/
USER nginx
