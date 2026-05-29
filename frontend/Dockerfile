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
RUN npm run build

# ---------- runtime ----------
FROM nginx:1.27-alpine AS runtime

# nginx default config substitutes $BACKEND_URL via envsubst on container start
# so the same image is portable across environments. The ECS task definition
# sets BACKEND_URL to the backend service-discovery DNS name in the cluster.
ENV BACKEND_URL=http://backend:8000

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx official image runs as nginx (non-root) by default since 1.25.
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1
