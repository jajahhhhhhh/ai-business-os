# syntax=docker/dockerfile:1
# AI Business OS — dashboard (Next.js standalone), multi-stage, non-root.
# Build context: apps/web

# ----- deps -----
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
# No lockfile committed yet — resolve from package.json ranges.
RUN npm install --no-audit --no-fund

# ----- build -----
FROM node:20-alpine AS builder
WORKDIR /app
# NEXT_PUBLIC_* values are baked into the client bundle AT BUILD TIME.
# Compose passes the public API URL (https://<domain>/api) as a build arg;
# building without it produces a bundle that only works against localhost.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ----- run -----
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
