FROM node:26-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:26-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN apk upgrade --no-cache && \
    apk add --no-cache su-exec && \
    mkdir -p /logs && \
    chown -R 1000:1000 /app /logs && \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

COPY --from=builder --chown=1000:1000 /app/.next/standalone ./
COPY --from=builder --chown=1000:1000 /app/.next/static ./.next/static
COPY --from=builder --chown=1000:1000 /app/public ./public
COPY --from=builder --chown=1000:1000 /app/scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/web-entrypoint.sh

RUN chmod +x /usr/local/bin/web-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/web-entrypoint.sh"]
EXPOSE 3000
CMD ["node", "scripts/start-with-log.js"]
