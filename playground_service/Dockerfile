FROM node:22-slim

ENV NODE_ENV=production \
    PORT=8080

WORKDIR /app

COPY playground_service/package.json playground_service/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

COPY playground_service/server.js playground_service/patch-playground.js ./
RUN node patch-playground.js

USER node

EXPOSE 8080

CMD ["node", "server.js"]
