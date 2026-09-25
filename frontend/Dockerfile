# Tres etapas para que la imagen final no contenga ni el codigo fuente ni las
# dependencias de compilacion, solo el servidor ya construido.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` exige lockfile; si aun no lo hay, `npm install` sirve igual. Cuando
# exista, se usa el determinista sin tocar este fichero.
RUN npm ci 2>/dev/null || npm install

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Mismo criterio que el Dockerfile de la API: nada corre como root.
RUN addgroup -g 10001 lonja && adduser -u 10001 -G lonja -D lonja

COPY --from=builder --chown=lonja:lonja /app/public ./public
COPY --from=builder --chown=lonja:lonja /app/.next/standalone ./
COPY --from=builder --chown=lonja:lonja /app/.next/static ./.next/static

USER lonja
EXPOSE 3000
CMD ["node", "server.js"]
