FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

WORKDIR /km_bot

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

CMD ["uv", "run", "--no-sync", "python", "km_bot.py"]