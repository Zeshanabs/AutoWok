# syntax=docker/dockerfile:1
# Autowok web image.
#   target "runtime" (default) - production: standalone Next.js server, non-root.
#   target "dev"               - local development with docker-compose.yml (source is bind-mounted).

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Reproducible install from the lockfile; no lifecycle scripts from dependencies.
RUN npm ci --ignore-scripts

FROM node:22-alpine AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The API origin is compiled into the browser bundle and the Content-Security-Policy,
# so it is a build argument. It is a public URL, never a secret.
ARG NEXT_PUBLIC_API_BASE_URL
ARG CSP_EXTRA_IMG_SRC
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    CSP_EXTRA_IMG_SRC=${CSP_EXTRA_IMG_SRC} \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
RUN test -n "$NEXT_PUBLIC_API_BASE_URL" || (echo "NEXT_PUBLIC_API_BASE_URL build argument is required" && exit 1)
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
STOPSIGNAL SIGTERM
CMD ["node", "server.js"]
