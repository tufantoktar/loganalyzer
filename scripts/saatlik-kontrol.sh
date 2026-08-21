#!/usr/bin/env bash
#
# Saatlik erken uyari. Gunluk rapor egilim icindir; bu script OLAY yakalar.
#
# Iki sey denetlenir:
#   1) Son 1 saatteki hata sayisi esigi asti mi
#   2) Surec hala kalp atisi yaziyor mu  (hata saymak tek basina yetmez:
#      olmus bir surec hic hata uretmez, sadece susar)
#
# Normalde SESSIZ calisir, hicbir sey yazmaz. Sadece bir esik asilirsa
# uyarilar.log'a satir dusurur ve ayrintili rapor uretir.
#
set -Eeuo pipefail

# Cron dar PATH ile calisir; pm2/node icin nvm dizinini ekle.
NODE_BIN="$(ls -d /root/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
[ -n "$NODE_BIN" ] && export PATH="$NODE_BIN:$PATH"

PROJE=/opt/loganalyzer
RAPOR=/var/log/loganalyzer
ERRORS=/root/polymarket-engine/logs/errors.jsonl
PM2_OUT=/root/.pm2/logs/polymarket-collect-out.log
MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

# Esikler. Normal gunlerde saatlik hata 0-2; bugunku olayda ~217 idi.
ESIK="${ESIK:-20}"
SESSIZLIK_DK="${SESSIZLIK_DK:-5}"

cd "$PROJE"
mkdir -p "$RAPOR"

DURUM=$(.venv/bin/python - "$ERRORS" "$PM2_OUT" /tmp/saatlik-errors.jsonl "$SESSIZLIK_DK" <<'PY'
import json, os, sys, time
from datetime import datetime, timedelta, timezone

errors_yolu, pm2_yolu, cikti, sessizlik_dk = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])

# Dosya 30 MB'a ulasabiliyor; son 1 saat icin tamamini okumak gereksiz.
# Sondan sabit bir pencere okuyup yarim kalan ilk satiri atiyoruz.
PENCERE = 4 * 1024 * 1024
try:
    boyut = os.path.getsize(errors_yolu)
    with open(errors_yolu, "rb") as f:
        if boyut > PENCERE:
            f.seek(boyut - PENCERE)
            f.readline()
        ham = f.read().decode("utf-8", "replace")
except OSError:
    print("HATA_OKUNAMADI 0 0")
    sys.exit(0)

esik_zaman = datetime.now(timezone.utc) - timedelta(hours=1)
sayi = 0
with open(cikti, "w") as out:
    for satir in ham.splitlines():
        try:
            ts = json.loads(satir).get("ts", "")
            if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")) >= esik_zaman:
                out.write(satir + "\n")
                sayi += 1
        except Exception:
            continue

try:
    sessizlik = (time.time() - os.path.getmtime(pm2_yolu)) / 60
except OSError:
    sessizlik = 9999

# tek satir: <durum> <hata_sayisi> <sessizlik_dakika>
durum = "SESSIZ" if sessizlik > sessizlik_dk else "CANLI"
print(f"{durum} {sayi} {sessizlik:.1f}")
PY
)

read -r CANLILIK HATA SESSIZLIK <<<"$DURUM"
SIMDI=$(date -u +%Y-%m-%dT%H:%M:%SZ)
UYARI=""

if [ "$CANLILIK" = "SESSIZ" ]; then
  UYARI="SUREC SUSTU: ${SESSIZLIK} dk'dir kalp atisi yok"
elif [ "$HATA" -ge "$ESIK" ]; then
  UYARI="HATA ARTISI: son 1 saatte ${HATA} hata (esik ${ESIK})"
fi

if [ -z "$UYARI" ]; then
  exit 0   # her sey yolunda -- sessiz cik, hicbir sey yazma
fi

echo "$SIMDI  $UYARI" | tee -a "$RAPOR/uyarilar.log"

# Uyari varsa ayrintili rapor uret. Ancak analiz edilecek satir varsa
# LLM'i cagir; surec sustuysa ortada hata olmayabilir.
CIKTI="$RAPOR/uyari-$(date -u +%Y-%m-%dT%H%M).md"
if [ -s /tmp/saatlik-errors.jsonl ]; then
  .venv/bin/python -m loganalyzer /tmp/saatlik-errors.jsonl \
    --model "$MODEL" -o "$CIKTI" >/dev/null 2>&1 || true
else
  printf '# Uyari %s\n\n%s\n\nSon 1 saatte hata kaydi yok.\n' "$SIMDI" "$UYARI" > "$CIKTI"
fi

{ printf '\n## Uyari\n\n- %s\n- Kalp atisi: %s dk once\n\n## PM2 Durumu\n\n```\n' "$UYARI" "$SESSIZLIK"
  pm2 list --no-color 2>/dev/null || echo "pm2 calistirilamadi"
  printf '```\n'
} >> "$CIKTI"

# 14 gunden eski uyari raporlarini sil
find "$RAPOR" -name 'uyari-*.md' -mtime +14 -delete

echo "[saatlik] ayrintili rapor -> $CIKTI"
exit 2
