FROM caddy:2.11.9-builder-alpine AS build
RUN xcaddy build v2.11.9 --with github.com/mholt/caddy-ratelimit@v0.1.0

FROM caddy:2.11.9-alpine
COPY --from=build /usr/bin/caddy /usr/bin/caddy
