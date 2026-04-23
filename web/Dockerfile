# Web UI image — multi-stage build
#
# Stage 1 (build): installs node deps, runs Vite production build
# Stage 2 (serve): copies dist/ into nginx, serves as static SPA
#
# In Docker the web UI talks to the API via nginx reverse-proxy
# (same origin, no CORS needed). The proxy block in nginx.conf
# forwards /api/* and /ws/* to the `api` service on port 8765.

# -------- Stage 1: build --------
FROM node:22-alpine AS build

WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline
COPY . .
# Point API calls at the nginx proxy path (same origin)
ENV VITE_API_BASE=/api
RUN npm run build

# -------- Stage 2: serve --------
FROM nginx:alpine AS serve

# Remove default nginx site
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/specs-agent.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1
