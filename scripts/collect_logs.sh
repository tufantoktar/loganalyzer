#!/usr/bin/env bash
#
# collect_logs.sh - dagitik log dosyalarini toplayip tek bir dosyada birlestirir.
#
# Neden bash? Bu is I/O ve dosya sistemi isi: find/gzip/tail burada
# Python'dan hem hizli hem az bagimlilikli. Python tarafi sadece parse eder.
#
# Kullanim:
#   ./collect_logs.sh -s /var/log/myapp -o /tmp/merged.log -H 24
#
set -Eeuo pipefail

SOURCE_DIR=""
OUTPUT="./collected.log"
HOURS=24
PATTERN="*.log*"
MAX_MB=50

usage() {
  cat <<EOF
Kullanim: $(basename "$0") -s <kaynak-dizin> [secenekler]

  -s DIR    Kaynak log dizini (zorunlu)
  -o FILE   Cikti dosyasi        (varsayilan: ${OUTPUT})
  -H SAAT   Son N saatlik loglar (varsayilan: ${HOURS})
  -p GLOB   Dosya deseni         (varsayilan: ${PATTERN})
  -m MB     Maksimum cikti boyutu(varsayilan: ${MAX_MB})
  -h        Bu yardim
EOF
}

log()  { printf '[collect] %s\n' "$*" >&2; }
die()  { printf '[collect][HATA] %s\n' "$*" >&2; exit 1; }

trap 'die "satir ${LINENO} basarisiz oldu"' ERR

while getopts ":s:o:H:p:m:h" opt; do
  case "${opt}" in
    s) SOURCE_DIR="${OPTARG}" ;;
    o) OUTPUT="${OPTARG}" ;;
    H) HOURS="${OPTARG}" ;;
    p) PATTERN="${OPTARG}" ;;
    m) MAX_MB="${OPTARG}" ;;
    h) usage; exit 0 ;;
    \?) die "bilinmeyen secenek: -${OPTARG}" ;;
    :)  die "-${OPTARG} bir deger bekliyor" ;;
  esac
done

[[ -n "${SOURCE_DIR}" ]] || { usage; die "-s zorunlu"; }
[[ -d "${SOURCE_DIR}" ]] || die "dizin yok: ${SOURCE_DIR}"
[[ "${HOURS}" =~ ^[0-9]+$ ]] || die "-H sayi olmali"

# Gecici dosyayi her durumda temizle.
TMP="$(mktemp)"
cleanup() { rm -f "${TMP}"; }
trap cleanup EXIT

MINUTES=$(( HOURS * 60 ))
log "kaynak=${SOURCE_DIR} desen=${PATTERN} son ${HOURS} saat"

file_count=0
# -print0 / read -d '' : bosluklu dosya adlarina karsi guvenli.
while IFS= read -r -d '' file; do
  case "${file}" in
    *.gz)  zcat  -- "${file}" >>"${TMP}" ;;
    *.bz2) bzcat -- "${file}" >>"${TMP}" ;;
    *)     cat   -- "${file}" >>"${TMP}" ;;
  esac
  file_count=$(( file_count + 1 ))
  log "  + ${file}"
done < <(find "${SOURCE_DIR}" -type f -name "${PATTERN}" -mmin "-${MINUTES}" -print0)

[[ "${file_count}" -gt 0 ]] || die "eslesme yok (dizin bos ya da dosyalar ${HOURS} saatten eski)"

# Cikti cok buyukse sondan kirp: son olaylar en degerlisi.
max_bytes=$(( MAX_MB * 1024 * 1024 ))
actual=$(wc -c <"${TMP}")
mkdir -p "$(dirname "${OUTPUT}")"

if [[ "${actual}" -gt "${max_bytes}" ]]; then
  log "cikti ${actual} bayt > ${max_bytes}, son kisim aliniyor"
  tail -c "${max_bytes}" "${TMP}" | tail -n +2 >"${OUTPUT}"   # yarim satiri at
else
  cp -- "${TMP}" "${OUTPUT}"
fi

lines=$(wc -l <"${OUTPUT}")
log "tamam: ${file_count} dosya -> ${OUTPUT} (${lines} satir)"
printf '%s\n' "${OUTPUT}"
