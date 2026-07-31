# Single-stage image, deliberately simple for now.
# TODO: replace with a multi-stage build (builder + slim runtime, non-root user, no build toolchain
# in the final layer) once the dependency set stabilises.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --upgrade pip && pip install -e .

EXPOSE 8000

CMD ["uvicorn", "medsafe.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
