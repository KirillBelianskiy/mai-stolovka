FROM node:22.23.4-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
COPY apps/telegram-mini-app/package.json ./apps/telegram-mini-app/package.json
COPY apps/kitchen-app/package.json ./apps/kitchen-app/package.json
RUN --mount=type=cache,target=/root/.npm npm ci --no-fund --fetch-retries=3
COPY apps/telegram-mini-app ./apps/telegram-mini-app
# The shared DOM regression suite also exercises the staff session boundary.
COPY apps/kitchen-app/src ./apps/kitchen-app/src
RUN npm run build --workspace @mai/telegram-mini-app

FROM nginx:1.30.6-alpine
COPY infra/nginx/static.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/telegram-mini-app/out /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
