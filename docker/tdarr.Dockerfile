FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /logs /data && \
    chown -R appuser:appuser /logs /data

COPY requirements/base.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

RUN chown -R appuser:appuser /app

USER appuser

CMD ["python", "tdarr_sync.py"]
