FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 emailagent \
    && mkdir -p /app/data \
    && chown -R emailagent:emailagent /app
USER emailagent

CMD ["uv", "run", "--no-sync", "python", "-m", "email_agent.main"]
