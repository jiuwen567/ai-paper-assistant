FROM node:24.13.0-alpine
RUN npm install --global pnpm@10.32.1
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/miniapp/package.json apps/miniapp/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
RUN chown -R node:node /app
USER node
EXPOSE 5173
CMD ["pnpm", "--filter", "@paper/web", "dev", "--host", "0.0.0.0"]
