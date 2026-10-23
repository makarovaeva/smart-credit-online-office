# Версии зафиксированы: базовый образ - точный тег, зависимости - uv.lock
ARG PYTHON_IMAGE=python:3.12.15-slim

FROM ${PYTHON_IMAGE} AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# uv из PyPI, а не из ghcr.io: сборка не зависит от доступа к GitHub Container Registry
RUN pip install --no-cache-dir uv==0.13.5

WORKDIR /app
COPY pyproject.toml uv.lock ./
# --locked: сборка падает, если uv.lock отстал от pyproject.toml
RUN uv sync --locked --no-dev --no-install-project


FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

USER app
EXPOSE 8000

CMD ["sh", "scripts/entrypoint.sh"]
