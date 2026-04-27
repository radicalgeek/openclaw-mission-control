# syntax=docker/dockerfile:1

FROM node:20-alpine AS deps
WORKDIR /app

# Skip Cypress binary download — not needed for Next.js builds
ENV CYPRESS_INSTALL_BINARY=0
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . ./

# Allows configuring the API URL at build time.
# Write to .env.local so Turbopack reliably picks up the value during the build
# (process.env injection via Docker ENV is not consistently inlined by Turbopack).
# The default is a unique placeholder that is replaced at container startup by
# docker-entrypoint.sh, enabling one image to serve any deployment.
ARG NEXT_PUBLIC_API_URL=__NEXT_PUBLIC_API_URL__
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ARG NEXT_PUBLIC_AUTH_MODE=local
ENV NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE}
ARG NEXT_PUBLIC_APP_DESCRIPTION
ENV NEXT_PUBLIC_APP_DESCRIPTION=${NEXT_PUBLIC_APP_DESCRIPTION}
ARG NEXT_PUBLIC_ACCENT_COLOR
ENV NEXT_PUBLIC_ACCENT_COLOR=${NEXT_PUBLIC_ACCENT_COLOR}
ARG NEXT_PUBLIC_ACCENT_STRONG
ENV NEXT_PUBLIC_ACCENT_STRONG=${NEXT_PUBLIC_ACCENT_STRONG}
ARG NEXT_PUBLIC_ACCENT_SOFT
ENV NEXT_PUBLIC_ACCENT_SOFT=${NEXT_PUBLIC_ACCENT_SOFT}
ARG NEXT_PUBLIC_ACCENT_FOREGROUND
ENV NEXT_PUBLIC_ACCENT_FOREGROUND=${NEXT_PUBLIC_ACCENT_FOREGROUND}
ARG NEXT_PUBLIC_ACCENT_TEXT_ON_SOFT
ENV NEXT_PUBLIC_ACCENT_TEXT_ON_SOFT=${NEXT_PUBLIC_ACCENT_TEXT_ON_SOFT}
ARG NEXT_PUBLIC_SIDEBAR_BG
ENV NEXT_PUBLIC_SIDEBAR_BG=${NEXT_PUBLIC_SIDEBAR_BG}
ARG NEXT_PUBLIC_CARD_BG
ENV NEXT_PUBLIC_CARD_BG=${NEXT_PUBLIC_CARD_BG}

RUN printf 'NEXT_PUBLIC_API_URL=%s\nNEXT_PUBLIC_AUTH_MODE=%s\nNEXT_PUBLIC_APP_DESCRIPTION=%s\nNEXT_PUBLIC_ACCENT_COLOR=%s\nNEXT_PUBLIC_ACCENT_STRONG=%s\nNEXT_PUBLIC_ACCENT_SOFT=%s\nNEXT_PUBLIC_ACCENT_FOREGROUND=%s\nNEXT_PUBLIC_ACCENT_TEXT_ON_SOFT=%s\nNEXT_PUBLIC_SIDEBAR_BG=%s\nNEXT_PUBLIC_CARD_BG=%s\n' \
    "${NEXT_PUBLIC_API_URL}" "${NEXT_PUBLIC_AUTH_MODE:-local}" \
    "${NEXT_PUBLIC_APP_DESCRIPTION}" "${NEXT_PUBLIC_ACCENT_COLOR}" \
    "${NEXT_PUBLIC_ACCENT_STRONG}" "${NEXT_PUBLIC_ACCENT_SOFT}" \
    "${NEXT_PUBLIC_ACCENT_FOREGROUND}" "${NEXT_PUBLIC_ACCENT_TEXT_ON_SOFT}" \
    "${NEXT_PUBLIC_SIDEBAR_BG}" "${NEXT_PUBLIC_CARD_BG}" > .env.local

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ARG NEXT_PUBLIC_AUTH_MODE=local
ENV NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE}

# Create non-root user before COPY so --chown can reference it.
# Using COPY --chown avoids a slow recursive chown on overlay2 (docker/for-linux#388).
RUN addgroup -S appgroup && adduser -S -G appgroup appuser \
  && chown appuser:appgroup /app

COPY --from=builder --chown=appuser:appgroup /app/.next ./.next
COPY --from=builder --chown=appuser:appgroup /app/public ./public
COPY --from=builder --chown=appuser:appgroup /app/package.json ./package.json
COPY --from=builder --chown=appuser:appgroup /app/node_modules ./node_modules
COPY --from=builder --chown=appuser:appgroup /app/next.config.ts ./next.config.ts
COPY --chown=appuser:appgroup docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

USER appuser

EXPOSE 3000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["npm", "run", "start"]
