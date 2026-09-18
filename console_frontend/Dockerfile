# Independent production image for console-v2 static assets.
# Default product path still bakes the same Vite build into Backoffice via
# agent_service/Dockerfile.backoffice (same-origin /console-v2 + /api).
FROM node:22-bookworm-slim AS console_build

WORKDIR /src/console_frontend
COPY console_frontend/package.json console_frontend/package-lock.json ./
RUN npm ci
COPY console_frontend/ ./
# Override Vite outDir so this image does not depend on agent_service paths.
RUN npm run build -- --outDir /out/console-v2 --emptyOutDir

FROM nginx:1.27-alpine

COPY console_frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=console_build /out/console-v2 /usr/share/nginx/html/console-v2

# Non-root: drop the default nginx user directive and write pid under /tmp.
RUN sed -i '/^user /d' /etc/nginx/nginx.conf \
    && sed -i 's@pid .*@pid /tmp/nginx.pid;@' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /usr/share/nginx/html \
    && chown -R nginx:nginx /var/cache/nginx \
    && chown -R nginx:nginx /var/log/nginx \
    && touch /tmp/nginx.pid \
    && chown nginx:nginx /tmp/nginx.pid

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
