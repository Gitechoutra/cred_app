# ──────────────────────────────────────────────────────────────────────────────
# CashU — React + Vite + Tailwind frontend
#
# Build:  docker build -t cashu-frontend .
# Serves the production bundle from nginx on :80 (mapped to :3000 in compose).
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: build the bundle ─────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY package*.json ./
RUN npm ci

COPY . .

# Vite inlines env vars at build time, so the API base URL has to be present
# now — it cannot be injected when the container starts.
ARG VITE_API_BASE_URL=http://localhost:5050/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build


# ── Stage 2: serve ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# CashU is a single-page app: nginx must fall back to index.html so a deep link
# like /rewards survives a hard refresh instead of 404ing.
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
