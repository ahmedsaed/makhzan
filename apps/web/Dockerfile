# Multi-stage build for the makhzan web app (Next.js standalone).
# Build context is apps/web (self-contained pnpm project — no monorepo path deps).

# --- deps: install node_modules from the lockfile --------------------------- #
FROM node:22-alpine AS deps
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- build: compile the standalone server ----------------------------------- #
FROM node:22-alpine AS build
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* is inlined at build time. Default is a same-origin relative path
# ("/api") that the reverse proxy maps to the API — host-independent. Override
# with --build-arg NEXT_PUBLIC_API_URL=https://api.example.com if you split hosts.
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
# Umami website id (stats.merope.dev). Unset means no analytics script.
ARG NEXT_PUBLIC_UMAMI_WEBSITE_ID=
ENV NEXT_PUBLIC_UMAMI_WEBSITE_ID=${NEXT_PUBLIC_UMAMI_WEBSITE_ID}
RUN pnpm build

# --- runtime: minimal image running the standalone server ------------------- #
FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root. The standalone output bundles a trimmed node_modules + server.js.
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

# Next's cache directory, mounted as a volume in production. Create it in the
# image, owned by the app user: a named volume mounted over a path that does not
# exist in the image is created owned by root, and the server — running as
# `nextjs` — then cannot write to it, silently losing every cached fetch.
RUN mkdir -p .next/cache && chown -R nextjs:nodejs .next

USER nextjs

EXPOSE 3000
CMD ["node", "server.js"]
