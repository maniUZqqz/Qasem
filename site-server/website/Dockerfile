# Marketing site. Next.js standalone output, so the runtime image carries the
# server and its traced dependencies rather than the whole node_modules tree.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# These are inlined into the bundle at build time, not read at runtime, so the
# public URLs have to be known here.
ARG NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_PANEL_URL
ARG NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_PANEL_URL=$NEXT_PUBLIC_PANEL_URL \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3001

RUN addgroup -g 10002 -S web && adduser -u 10002 -S web -G web

COPY --from=build --chown=web:web /app/.next/standalone ./
COPY --from=build --chown=web:web /app/.next/static ./.next/static
COPY --from=build --chown=web:web /app/public ./public

USER web
EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3001/ >/dev/null || exit 1

CMD ["node", "server.js"]
