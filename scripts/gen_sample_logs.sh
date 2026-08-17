#!/usr/bin/env bash
# Test icin sentetik log uretir. Gercek bir sisteme benzesin diye
# INFO agirlikli, aralarda hata patlamasi olan bir dagilim kullaniyoruz.
set -Eeuo pipefail

OUT="${1:-sample_logs/app.log}"
COUNT="${2:-500}"
mkdir -p "$(dirname "${OUT}")"
: >"${OUT}"

services=(payment-svc auth-svc order-svc gateway inventory-svc)
info_msgs=(
  "Request handled in 42ms"
  "Cache hit for key user:1042"
  "Health check passed"
  "Order 88123 accepted"
)
warn_msgs=(
  "Connection pool at 85% capacity"
  "Retrying upstream call attempt 2"
  "Slow query took 1200ms"
)
error_msgs=(
  "Connection refused to 10.0.3.12:5432"
  "Timeout after 3021ms waiting for inventory-svc"
  "NullPointerException at com.acme.OrderService.total"
  "Failed to commit transaction tx-9f2b1c8a"
)

base_epoch=$(date -u +%s)

for (( i = 0; i < COUNT; i++ )); do
  ts=$(date -u -d "@$(( base_epoch - (COUNT - i) * 7 ))" '+%Y-%m-%d %H:%M:%S' 2>/dev/null \
     || date -u -r "$(( base_epoch - (COUNT - i) * 7 ))" '+%Y-%m-%d %H:%M:%S')
  svc="${services[$(( RANDOM % ${#services[@]} ))]}"
  roll=$(( RANDOM % 100 ))

  # 300-360 arasi bilincli bir hata patlamasi (incident simulasyonu)
  if (( i > 300 && i < 360 )); then roll=$(( roll % 30 )); fi

  if   (( roll < 12 )); then lvl=ERROR; msg="${error_msgs[$(( RANDOM % ${#error_msgs[@]} ))]}"
  elif (( roll < 28 )); then lvl=WARN;  msg="${warn_msgs[$(( RANDOM % ${#warn_msgs[@]} ))]}"
  else                       lvl=INFO;  msg="${info_msgs[$(( RANDOM % ${#info_msgs[@]} ))]}"
  fi

  printf '%s %s [%s] %s\n' "${ts}" "${lvl}" "${svc}" "${msg}" >>"${OUT}"
done

printf '[gen] %s satir yazildi -> %s\n' "${COUNT}" "${OUT}" >&2
