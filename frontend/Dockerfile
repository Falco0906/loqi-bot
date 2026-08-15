# syntax=docker/dockerfile:1
# Loqi frontend production image (PR10.1).
#
# Multi-stage: full-dependency build stage runs `next build`, runtime stage
# ships only production dependencies + the compiled `.next` output and runs
# `next start` (never `next dev`).
#
# NEXT_PUBLIC_LOQI_API_BASE_URL is baked at build time (Next.js inlines
# NEXT_PUBLIC_* vars); pass it as a build ARG so the browser/server reach the
# backend service inside the compose network.
FROM node:24-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG NEXT_PUBLIC_LOQI_API_BASE_URL=http://backend:10000
ENV NEXT_PUBLIC_LOQI_API_BASE_URL=$NEXT_PUBLIC_LOQI_API_BASE_URL
RUN npm run build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=build /app/.next ./.next

# Non-root runtime user.
RUN addgroup -S appuser && adduser -S -G appuser appuser
USER appuser

EXPOSE 3000

CMD ["npm", "run", "start"]
