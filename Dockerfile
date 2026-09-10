FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY obsdados/ ./obsdados/

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["obsdados"]
