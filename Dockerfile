# Alternative deployment (VPS / any Docker host): long polling + periodic jobs in one container.
# The primary deployment is Phusion Passenger with a webhook - see DEPLOYMENT.md.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /km_bot

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

COPY km_bot ./km_bot
COPY assets ./assets

VOLUME ["/km_bot/data"]

# Refresh the data on start and every 6 hours in the background, then poll Telegram.
CMD ["sh", "-c", "uv run --no-sync python -m km_bot refresh-data; (while sleep 21600; do uv run --no-sync python -m km_bot refresh-data; done) & exec uv run --no-sync python -m km_bot poll"]
