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
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/ || exit 1
