#!/usr/bin/env bash
#
# Container entrypoint. Ollama hazir olana kadar bekler, sonra CLI'yi calistirir.
# Compose'da `depends_on` sadece container'in basladigini garantiler,
# servisin HAZIR oldugunu degil. O yuzden burada aktif bekleme yapiyoruz.
#
set -Eeuo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
WAIT_FOR_OLLAMA="${WAIT_FOR_OLLAMA:-true}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-90}"

log() { printf '[entrypoint] %s\n' "$*" >&2; }

if [[ "${WAIT_FOR_OLLAMA}" == "true" ]]; then
  log "Ollama bekleniyor: ${OLLAMA_HOST} (timeout ${WAIT_TIMEOUT}s)"
  deadline=$(( SECONDS + WAIT_TIMEOUT ))
  until curl -sf "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      log "UYARI: Ollama ${WAIT_TIMEOUT}s icinde hazir olmadi, LLM'siz devam ediliyor"
      break
    fi
    sleep 2
  done
fi

exec python -m loganalyzer "$@"
