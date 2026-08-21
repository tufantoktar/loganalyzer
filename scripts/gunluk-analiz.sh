#!/usr/bin/env bash
#
# polymarket-engine icin gunluk analiz. Cron'dan calisir.
#
# Bu script UYGULAMAYA OZELDIR: /root/polymarket-engine yollarini ve
# "[collect] ... ticks=N books=N errors=N" kalp atisi bicimini bilir.
# loganalyzer paketi genel kalir; ozel bilgi burada durur.
#
set -Eeuo pipefail

# Cron cok dar bir PATH ile calisir (/usr/bin:/bin).
#
# DIKKAT: pm2'nin yolunu bulmak TEK BASINA YETMIYOR. pm2 bir node scriptidir;
# calisirken 'node'u PATH'te arar. Sadece pm2 yolunu cozersek
# "env: 'node': No such file or directory" alinir. Bu yuzden nvm'in bin
# dizinini komple PATH'e ekliyoruz -- node ve pm2 birlikte gelsin.
NODE_BIN="$(ls -d /root/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$NODE_BIN" ]; then
  export PATH="$NODE_BIN:$PATH"
fi
PM2_BIN="$(command -v pm2 2>/dev/null || true)"

PROJE=/opt/loganalyzer
RAPOR=/var/log/loganalyzer
ERRORS=/root/polymarket-engine/logs/errors.jsonl
PM2_OUT=/root/.pm2/logs/polymarket-collect-out.log
MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"
TARIH=$(date -u +%Y-%m-%d)

# ONEMLI: cron /root'tan baslatir; "python -m loganalyzer" paketi bulamaz.
cd "$PROJE"
mkdir -p "$RAPOR"

# ---------------------------------------------------------------------------
# 1) Son 24 saatin hata satirlarini suz
# ---------------------------------------------------------------------------
.venv/bin/python - "$ERRORS" /tmp/gunluk-errors.jsonl <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone

src, dst = sys.argv[1], sys.argv[2]
esik = datetime.now(timezone.utc) - timedelta(hours=24)
n = 0
with open(src, errors="replace") as f, open(dst, "w") as out:
    for line in f:
        try:
            ts = json.loads(line).get("ts", "")
            if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")) >= esik:
                out.write(line)
                n += 1
        except Exception:
            continue
print(f"[gunluk] son 24 saat: {n} hata satiri", file=sys.stderr)
PY

# ---------------------------------------------------------------------------
# 2) Hata raporu (Ollama yorumlu)
# ---------------------------------------------------------------------------
if [ -s /tmp/gunluk-errors.jsonl ]; then
  .venv/bin/python -m loganalyzer /tmp/gunluk-errors.jsonl \
    --model "$MODEL" -o "$RAPOR/hatalar-$TARIH.md"
else
  printf '# %s\n\nSon 24 saatte hata yok.\n' "$TARIH" > "$RAPOR/hatalar-$TARIH.md"
fi

# ---------------------------------------------------------------------------
# 3) Saglik raporu - kalp atisi sayaclarindan
#
# NOT: Onceki surumde PM2 stdout'una "--fail-over 0.05" uygulaniyordu.
# O dosyada seviye etiketi olmadigi icin hata orani HER ZAMAN %0 cikiyordu,
# yani esik hicbir zaman tetiklenmiyordu -- sahte guvence. Yerine
# "[collect] ... ticks/books/errors" sayaclarinin 24 saatlik deltasi kullanildi.
# ---------------------------------------------------------------------------
set +e
.venv/bin/python - "$PM2_OUT" > "$RAPOR/saglik-$TARIH.md" <<'PY'
import glob, os, re, sys, time

path = sys.argv[1]
pat = re.compile(r"\[collect\]\s+([\d.]+)min\s+.*?ticks=(\d+)\s+books=(\d+)\s+errors=(\d+)")

# pm2-logrotate gece yarisi logu dondurup dosyayi sifirliyor. Sadece guncel
# dosyaya bakarsak sabahki raporda 24 saatlik gecmis olmuyor. Dondurulmus
# dosyalari da (en yenisinden baslayarak) okuyoruz.
# Dosya adlari zaman damgali oldugu icin sirali okuma kronolojik olur.
klasor, ad = os.path.dirname(path), os.path.basename(path)
dondurulmus = sorted(glob.glob(os.path.join(klasor, ad.replace(".log", "") + "__*.log")))
kaynaklar = dondurulmus[-2:] + [path]  # en fazla son 2 arsiv + guncel

rows = []
for kaynak in kaynaklar:
    try:
        with open(kaynak, errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    g = m.groups()
                    rows.append((float(g[0]), int(g[1]), int(g[2]), int(g[3])))
    except OSError:
        continue

# Surec yeniden baslarsa "dakika" sayaci sifirlanir; sadece son kesintisiz
# artan diziyi tut, yoksa delta hesabi negatif cikar.
if rows:
    bas = 0
    for i in range(1, len(rows)):
        if rows[i][0] < rows[i - 1][0]:
            bas = i
    rows = rows[bas:]

print("# Saglik Raporu\n")
if not rows:
    print("**Kalp atisi satiri bulunamadi.** Log bicimi degismis olabilir;")
    print("`scripts/gunluk-analiz.sh` icindeki desen guncellenmeli.")
    sys.exit(1)

son = rows[-1]
# Satirlar ~1 dakikada bir yaziliyor -> 24 saat icin ~1440 satir geriye bak
onceki = rows[max(0, len(rows) - 1441)]
dk = son[0] - onceki[0]
d_tick, d_book, d_err = son[1] - onceki[1], son[2] - onceki[2], son[3] - onceki[3]

yas_dk = (time.time() - os.path.getmtime(path)) / 60
canli = yas_dk < 5

# Esik sabit degil: 24 saatlik hata hizini omur boyu ortalamayla kiyasla.
omur_hiz = son[3] / son[1] if son[1] else 0
pencere_hiz = d_err / d_tick if d_tick else 0
bozulma = omur_hiz > 0 and pencere_hiz > omur_hiz * 1.5

print(f"- **Durum:** {'CALISIYOR' if canli else f'DIKKAT - {yas_dk:.0f} dk’dir log yazilmiyor'}")
print(f"- **Calisma suresi:** {son[0] / 60:.1f} saat")
print(f"- **Olcum penceresi:** son {dk / 60:.1f} saat\n")

print("| Metrik | Pencere | Omur boyu |")
print("|---|---:|---:|")
print(f"| Tick | {d_tick} | {son[1]} |")
print(f"| Kitap | {d_book} | {son[2]} |")
print(f"| Hata | {d_err} | {son[3]} |")
print(f"| Tick basina hata | {pencere_hiz:.3f} | {omur_hiz:.3f} |")
if d_tick:
    print(f"| Tick basina kitap | {d_book / d_tick:.1f} | {son[2] / son[1]:.1f} |")

if not canli:
    print(f"\n> **UYARI:** {yas_dk:.0f} dakikadir yeni log yok. Surec takilmis olabilir.")
if bozulma:
    print(f"\n> **UYARI:** Hata hizi omur boyu ortalamanin {pencere_hiz / omur_hiz:.1f} katina cikti.")

sys.exit(2 if (not canli or bozulma) else 0)
PY
SAGLIK=$?
set -e

{ printf '\n## PM2 Durumu\n\n```\n'
  if [ -n "$PM2_BIN" ]; then
    "$PM2_BIN" list --no-color 2>/dev/null || echo "pm2 calistirilamadi"
  else
    echo "pm2 bulunamadi (PATH: $PATH)"
  fi
  printf '```\n'
} >> "$RAPOR/saglik-$TARIH.md"

# 30 gunden eski raporlari sil
find "$RAPOR" -name '*-20??-??-??.md' -mtime +30 -delete

if [ "$SAGLIK" -ne 0 ]; then
  echo "[gunluk] SAGLIK UYARISI -> $RAPOR/saglik-$TARIH.md"
fi
exit 0
