# syntax=docker/dockerfile:1.7
#
# Multi-stage: bagimliliklari builder'da wheel'e cevirip runtime'a kopyaliyoruz.
# Boylece runtime imajinda ne pip cache'i ne de build-essential kaliyor.

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

# Nexus PyPI proxy kullanacaksan CI'dan --build-arg ile gecebilirsin.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=pypi.org
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Once sadece requirements: kod degisince bu layer cache'ten gelsin.
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="loganalyzer" \
      org.opencontainers.image.description="Log analiz CLI + Ollama yorumlama" \
      org.opencontainers.image.source="https://gitlab.example.com/devops/loganalyzer"

# entrypoint.sh curl kullaniyor (Ollama health check); bash da lazim.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OLLAMA_HOST=http://ollama:11434 \
    OLLAMA_MODEL=llama3.2:3b

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

COPY loganalyzer/ ./loganalyzer/
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/*.sh

# Root olarak calistirma. UID sabit ki mount edilen volume izinleri tahmin edilebilir olsun.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data /reports \
 && chown -R appuser:appuser /app /data /reports
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import loganalyzer; print(loganalyzer.__version__)" || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["--help"]
