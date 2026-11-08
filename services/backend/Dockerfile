FROM node:24.13.0-bookworm-slim AS pi
RUN npm install --global pnpm@10.32.1
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY services/pi-runner/package.json services/pi-runner/package.json
RUN pnpm install --filter @paper/pi-runner... --prod --frozen-lockfile
COPY services/pi-runner/src services/pi-runner/src

FROM python:3.12.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY --from=pi /usr/local/bin/node /usr/local/bin/node
COPY --from=pi /app/node_modules /app/node_modules
COPY --from=pi /app/services/pi-runner /app/services/pi-runner
COPY services/backend /app/services/backend
RUN useradd --create-home app && chown -R app:app /app/services
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/services/backend
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
