# AI Quant Dashboard — React/Vite build → nginx static + API/WS proxy
# Build:  docker build -t ai-quant-dashboard ./apps/dashboard
# Run:    docker run -p 5173:80 ai-quant-dashboard   (expects API reachable as "api" host)
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
# Official image templates/ ko env se render karke conf.d/default.conf banata hai.
# API_UPSTREAM = backend host:port (compose: api:8000; Railway: private network host:port).
ENV API_UPSTREAM=api:8000 \
    PORT=80
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:${PORT}/ || exit 1
