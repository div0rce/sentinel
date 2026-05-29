# syntax=docker/dockerfile:1.7
# ---------- builder ----------
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps from the lockfile only first so a code change does not bust the
# dependency layer.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY . .

# Vite emits ./dist with hashed asset names. tsc -b runs as part of `npm run
# build` and fails the build on any type error.
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# ---------- runtime ----------
FROM nginx:1.27-alpine AS runtime

# nginx default config substitutes $BACKEND_URL via envsubst on container start
# so the same image is portable across environments. The ECS task definition
# sets BACKEND_URL to the backend service-discovery DNS name in the cluster.
ENV BACKEND_URL=http://backend:8000

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

RUN set -eux; \
    mkdir -p /var/cache/nginx/client_temp /var/cache/nginx/proxy_temp \
        /var/cache/nginx/fastcgi_temp /var/cache/nginx/uwsgi_temp \
        /var/cache/nginx/scgi_temp; \
    touch /run/nginx.pid; \
    chown -R nginx:nginx /usr/share/nginx/html /etc/nginx/conf.d \
        /var/cache/nginx /var/log/nginx /var/run /run/nginx.pid

EXPOSE 8080
USER nginx

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1:8080/ || exit 1
