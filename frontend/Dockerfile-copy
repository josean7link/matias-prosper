# ── Stage 1: install deps ────────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json yarn.lock* ./
RUN yarn install --frozen-lockfile

# ── Stage 2: build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# BACKEND_URL must be passed as a build arg so next.config.js rewrites resolve
# correctly at build time. In Render/Vercel it is injected via env vars.
ARG BACKEND_URL=http://localhost:8001
ENV BACKEND_URL=${BACKEND_URL}
RUN yarn build

# ── Stage 3: production runtime ──────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# Only copy the output needed to run the server
COPY --from=builder /app/public        ./public
COPY --from=builder /app/.next         ./.next
COPY --from=builder /app/node_modules  ./node_modules
COPY --from=builder /app/package.json  ./package.json
EXPOSE 3000
CMD ["yarn", "start"]
