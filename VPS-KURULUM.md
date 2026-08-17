# VPS Kurulumu (4 GB RAM, çalışan Polymarket motoru var)

Bu rehber **senin sunucun** için yazıldı: 3.7 GB RAM, swap yok, üzerinde çalışan
bir üretim servisi var. Buradaki her adım "mevcut servisi bozma" önceliğiyle
seçildi.

**Amaç:** Polymarket motorunun gerçek loglarını her gece analiz edip, hata oranı
yükseldiğinde raporu okuyabilmek.

---

## Önce karar: neyi nereye kuruyoruz

| Bileşen | VPS'e | Neden |
|---|---|---|
| loganalyzer (Python) | ✅ Evet | ~150 MB, hiçbir şeyi zorlamaz |
| Docker | ✅ Evet | Zaten kurulu olabilir |
| Ollama + `qwen2.5:1.5b` | ✅ Evet | ~1.5 GB, sadece analiz anında |
| **Nexus** | ❌ **Hayır** | ~2.5 GB ister, RAM'in bitirir |
| GitHub Actions | ✅ (GitHub'da) | Sunucunu hiç kullanmaz |

Nexus'u öğrenmek için kendi Ubuntu makinende çalıştır (`KURULUM.md` Adım 7).
Sunucuda imaj deposuna ihtiyacın olursa GitHub'ın `ghcr.io`'sunu kullanırız,
bedava ve RAM yemiyor.

---

## Adım 0 — Swap ekle (bunu atlama)

Şu an swap'ın **0**. Bu, RAM dolduğunda Linux'un çare olarak bir işlemi
öldürmesi demek — hangisini öldüreceğini sen seçmiyorsun. Polymarket motorun
olabilir, hem de sessizce.

Swap = disk üzerinde acil durum belleği. Yavaş ama "öldürmekten" iyi.

```bash
# 4 GB swap dosyası oluştur
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Yeniden başlatmada da açık kalsın
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Swap'a ancak gerçekten gerekince başvursun (RAM'i tercih et)
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
```

Kontrol:

```bash
free -h
```

**Görmen gereken:** `Swap:` satırında artık `4.0Gi` yazıyor.

> Bu adım 2 dakika sürdü ve sunucunun dayanıklılığını kalıcı olarak artırdı.
> Bu proje olmasaydı da yapman gereken bir şeydi.

---

## Adım 1 — Mevcut durumu gör

Neyin çalıştığını bilmeden bir şey kurma.

```bash
# En çok RAM yiyen 10 işlem
ps aux --sort=-%mem | head -11

# Docker kurulu mu, ne çalışıyor?
docker ps 2>/dev/null || echo "Docker kurulu degil"

# systemd servisleri
systemctl list-units --type=service --state=running | head -20

# Disk durumu
df -h /
```

**Bu çıktıyı bir yere kaydet.** Bir şey ters giderse "önce neydi" diye bakarsın.

Diskte en az **5 GB boş** olmalı (Docker imajları + Ollama modeli).

---

## Adım 2 — Log kaynakları (bu sunucuda tespit edildi)

Bot **PM2** ile yönetiliyor (`polymarket-collect`, fork modu, auto-restart açık).
Üç ayrı log kaynağı var ve her biri farklı soruyu cevaplıyor:

| Dosya | İçerik | Ne için kullanılır |
|---|---|---|
| `/root/polymarket-engine/logs/errors.jsonl` | Sadece hatalar, JSONL | **"Ne bozuluyor?"** — asıl analiz kaynağı |
| `~/.pm2/logs/polymarket-collect-out.log` | Tüm stdout | "Genel sağlık nasıl?" — hata oranı anlamlı |
| `~/.pm2/logs/polymarket-collect-error.log` | stderr | Çökme/stack trace |

> **Dikkat:** `errors.jsonl` **sadece** hata satırı içerir, yani hata oranı her
> zaman %100 çıkar — bu dosyada `--fail-over` kullanmak anlamsız. Oradaki değer
> *hata imzalarının gruplanmasında*: 31 bin satır, avuç dolusu gerçek soruna iner.
> Hata oranını ölçmek istiyorsan PM2'nin `-out.log` dosyasını kullan.

PM2'yi tanımak için faydalı komutlar (hiçbiri bir şey değiştirmez):

```bash
pm2 list                          # durum ve restart sayisi
pm2 logs polymarket-collect       # canli log (Ctrl+C ile cik)
pm2 describe polymarket-collect   # detay
```

---

## Adım 3 — Docker (kurulu değilse)

```bash
docker --version
```

Çıktı verdiyse bu adımı atla. Vermezse:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

---

## Adım 4 — Projeyi sunucuya al

Önce Mac'ten GitHub'a push etmiş olman lazım (`KURULUM-MAC.md` Adım 3).
Sonra sunucuda:

```bash
ssh -T git@github.com                      # SSH anahtari calisiyor mu
apt update && apt install -y python3-venv make
cd /opt && git clone git@github.com:tufantoktar/loganalyzer.git
cd /opt/loganalyzer
```

> `/opt` = Linux'ta "sisteme sonradan kurulan uygulamalar" dizini. Ev dizini
> yerine burayı kullanmak, servisin belirli bir kullanıcıya bağlı olmamasını sağlar.

Kur ve test et:

```bash
make venv
source .venv/bin/activate
make test
```

**Görmen gereken:** `52 passed`

Hemen gerçek bir şeyle dene — sistem loglarını analiz et:

```bash
sudo journalctl --since "24 hours ago" --no-pager > /tmp/sistem.log
python -m loganalyzer /tmp/sistem.log --no-llm -o /tmp/rapor.md
cat /tmp/rapor.md
```

**Bu, sunucunun son 24 saatteki gerçek durumu.** AI olmadan bile işe yarar bir çıktı.

---

## Adım 5 — Ollama (küçük model)

### 5.1 Kur

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 5.2 Güvenlik: dışarı açma

**Ollama'nın kimlik doğrulaması yoktur.** Portu internete açarsan, bulan herkes
senin sunucunda ücretsiz AI çalıştırır ve CPU'nu tüketir.

Varsayılan ayar zaten güvenli (`127.0.0.1`), sadece doğrula:

```bash
sudo ss -tlnp | grep 11434
```

**Görmen gereken:** `127.0.0.1:11434` — başında `0.0.0.0` veya `*` **olmamalı**.

`0.0.0.0` görüyorsan hemen düzelt:

```bash
sudo systemctl edit ollama
```

Açılan dosyaya ekle:

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### 5.3 Küçük model indir

```bash
ollama pull qwen2.5:1.5b
```

~1 GB indirir. **`llama3.2:3b` kullanma** — bu RAM'de sıkışır, swap'a düşer ve
analiz dakikalarca sürer.

### 5.4 Belleği boşa tutmasın

Ollama varsayılan olarak modeli 5 dakika bellekte tutar. Günde bir kez analiz
yapacaksak buna gerek yok:

```bash
sudo systemctl edit ollama
```

`[Service]` bloğuna ekle:

```ini
Environment="OLLAMA_KEEP_ALIVE=30s"
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

> Artık model analizden 30 saniye sonra bellekten düşer. Polymarket motoruna
> RAM kalır.

### 5.5 Dene

```bash
cd /opt/loganalyzer && source .venv/bin/activate
python -m loganalyzer /tmp/sistem.log --model qwen2.5:1.5b -o /tmp/rapor.md
cat /tmp/rapor.md
```

İlk çalıştırma 1-2 dakika sürebilir. Raporun sonunda AI yorumu olacak.

Bu sırada başka bir terminalden belleği izlemek istersen:

```bash
watch -n 2 free -h
```

`available` sütunu **500 MB'ın altına inmemeli**. İniyorsa daha küçük model
kullan veya AI'yı tamamen kapat (`--no-llm`) — istatistik raporu yine üretilir.

---

## Adım 6 — Her gece otomatik analiz

Asıl istediğimiz buydu: sabah kalkınca dünün raporu hazır olsun.

### 6.1 Analiz scripti

```bash
sudo tee /opt/loganalyzer/gunluk-analiz.sh > /dev/null <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

PROJE=/opt/loganalyzer
RAPOR_DIZIN=/var/log/loganalyzer
TARIH=$(date +%Y-%m-%d)

ERRORS=/root/polymarket-engine/logs/errors.jsonl
PM2_OUT=/root/.pm2/logs/polymarket-collect-out.log

mkdir -p "$RAPOR_DIZIN"
source "$PROJE/.venv/bin/activate"

# --- 1) Hata analizi: son 24 saatin errors.jsonl satirlari ---
# Dosya surekli buyuyor; sadece dunku satirlari suzuyoruz.
DUN=$(date -u -d '24 hours ago' +%Y-%m-%dT%H)
awk -v esik="$DUN" '{ if (substr($0, index($0,"\"ts\":\"")+6, 13) >= esik) print }' \
  "$ERRORS" > /tmp/gunluk-errors.jsonl || true

if [ -s /tmp/gunluk-errors.jsonl ]; then
  python -m loganalyzer /tmp/gunluk-errors.jsonl \
    --model qwen2.5:1.5b \
    -o "$RAPOR_DIZIN/hatalar-$TARIH.md"
else
  echo "Son 24 saatte hata yok" > "$RAPOR_DIZIN/hatalar-$TARIH.md"
fi

# --- 2) Genel saglik: PM2 stdout (hata orani burada anlamli) ---
tail -n 20000 "$PM2_OUT" > /tmp/gunluk-out.log
python -m loganalyzer /tmp/gunluk-out.log \
  --no-llm --fail-over 0.05 \
  -o "$RAPOR_DIZIN/saglik-$TARIH.md"
SONUC=$?

# --- 3) PM2 durumu raporun sonuna ---
{ echo; echo '## PM2 Durumu'; echo '```'; pm2 list --no-color 2>/dev/null; echo '```'; } \
  >> "$RAPOR_DIZIN/saglik-$TARIH.md"

# 30 günden eski raporları sil
find "$RAPOR_DIZIN" -name '*-20*.md' -mtime +30 -delete

if [ $SONUC -eq 2 ]; then
  echo "UYARI: hata orani esigi asildi -> $RAPOR_DIZIN/saglik-$TARIH.md"
fi
exit 0   # cron'a hata döndürme, rapor zaten yazıldı
EOF

sudo chmod +x /opt/loganalyzer/gunluk-analiz.sh
```

**`journalctl` satırını kendi log kaynağına göre değiştir** (Adım 2'de bulduğun).

Elle bir kez dene:

```bash
sudo /opt/loganalyzer/gunluk-analiz.sh
ls -la /var/log/loganalyzer/
```

### 6.2 Zamanlayıcıya ekle

```bash
sudo crontab -e
```

(İlk kez açıyorsan editör seçmeni ister — `1` yazıp Enter, nano açılır.)

En alta ekle:

```
0 6 * * * /opt/loganalyzer/gunluk-analiz.sh >> /var/log/loganalyzer/cron.log 2>&1
```

Kaydet: `Ctrl+O` → `Enter` → `Ctrl+X`

> `0 6 * * *` = her gün saat 06:00. Sırasıyla: dakika, saat, ayın günü, ay,
> haftanın günü. `*` = "her". Saat 03:00 istersen `0 3 * * *`.

Artık her sabah `/var/log/loganalyzer/rapor-TARIH.md` hazır olacak:

```bash
cat /var/log/loganalyzer/rapor-$(date +%Y-%m-%d).md
```

---

## Adım 7 — Nexus yerine ghcr.io

Nexus'u sunucuya kurmuyoruz ama imaj deposu mantığını yine de kullanabilirsin.
GitHub Actions zaten her push'ta imajı `ghcr.io`'ya yüklüyor.

Sunucuda çekmek için:

```bash
# GitHub token'ın ile giriş (KURULUM.md Adım 8.3'teki token, write:packages yetkili)
echo "GHP_TOKENIN" | docker login ghcr.io -u KULLANICI_ADIN --password-stdin

docker pull ghcr.io/KULLANICI_ADIN/loganalyzer:latest
```

Çalıştır:

```bash
docker run --rm --network host \
  -e OLLAMA_HOST=http://localhost:11434 \
  -e OLLAMA_MODEL=qwen2.5:1.5b \
  -v /tmp:/data \
  -v /var/log/loganalyzer:/reports \
  ghcr.io/KULLANICI_ADIN/loganalyzer:latest /data/gunluk.log -o /reports/rapor.md
```

> **Kavram aynı:** Nexus da ghcr.io da "artifact repository" — imajları
> saklayan depo. Nexus'u şirketler kendi sunucularında çalıştırır (veri dışarı
> çıkmasın diye), ghcr.io bulutta. Öğrendiğin mantık ikisinde de geçerli.

---

## Güvenlik notları

Bu bir üretim sunucusu ve `root` olarak bağlanıyorsun. Birkaç şey:

**1. Yeni port açma.** Bu kurulum hiçbir portu dışarı açmıyor — Ollama sadece
`127.0.0.1`'de. Böyle kalsın.

**2. Firewall'u kontrol et:**

```bash
sudo ufw status
```

Aktifse ve sadece SSH (22) açıksa iyi. Kapalıysa bu ayrı bir konu, ama Nexus'u
kurmadığımız için acil değil.

**3. Loglarda sırlar var.** `parser.py` içindeki `redact()` fonksiyonu parola,
token, JWT ve e-posta maskeliyor. Polymarket loglarında **cüzdan adresi veya
private key** geçiyorsa bunu da ekle:

```python
# loganalyzer/parser.py -> SECRET_PATTERNS içine
(re.compile(r"\b0x[a-fA-F0-9]{40}\b"), "***ADDRESS***"),
(re.compile(r"\b0x[a-fA-F0-9]{64}\b"), "***PRIVKEY***"),
```

> Ollama yerel çalıştığı için veri sunucudan çıkmıyor, ama rapor dosyasını
> birine gönderirsen sızabilir. Maskeleme her durumda iyi fikir.

**4. Root yerine ayrı kullanıcı** (opsiyonel, iyi alışkanlık):

```bash
adduser deploy
usermod -aG sudo,docker deploy
```

---

## İzleme ve sorun giderme

### Bellek durumu

```bash
free -h                          # anlık
watch -n 2 free -h               # canlı takip (Ctrl+C ile çık)
ps aux --sort=-%mem | head -6    # en çok yiyen 5 işlem
```

### Bir şey öldürüldü mü?

```bash
sudo dmesg -T | grep -i "killed process"
```

Çıktı varsa OOM killer devreye girmiş demektir. Swap eklediysen bu olmamalı.

### Ollama çok yavaş / takılıyor

```bash
systemctl status ollama
sudo systemctl restart ollama
```

Devam ederse AI'yı kapat, istatistik raporu yeter:

```bash
python -m loganalyzer /tmp/gunluk.log --no-llm -o /tmp/rapor.md
```

### Cron çalışmadı

```bash
cat /var/log/loganalyzer/cron.log     # scriptin çıktısı
grep CRON /var/log/syslog | tail -20  # cron tetikledi mi
sudo crontab -l                       # kayıt duruyor mu
```

En sık sebep: cron'un `PATH`'i dar olur. Script içinde tam yol kullandık, o yüzden
sorun çıkmamalı.

### Disk doldu

```bash
df -h /
docker system df                 # docker ne kadar yer kaplıyor
docker system prune -a           # kullanılmayan imajları sil (dikkatli)
sudo journalctl --vacuum-time=7d # eski journald loglarını temizle
```

### Her şeyi geri al

```bash
sudo crontab -e                  # cron satırını sil
sudo systemctl stop ollama && sudo systemctl disable ollama
sudo rm -rf /opt/loganalyzer /var/log/loganalyzer
```

Swap'ı bırak, o zaten faydalı.

---

## Kopya kağıdı

```bash
# Rapor oku
cat /var/log/loganalyzer/rapor-$(date +%Y-%m-%d).md

# Elle analiz çalıştır
sudo /opt/loganalyzer/gunluk-analiz.sh

# Hızlı bakış (AI yok, 2 saniye)
cd /opt/loganalyzer && source .venv/bin/activate
sudo journalctl --since "1 hour ago" --no-pager > /tmp/son.log
python -m loganalyzer /tmp/son.log --no-llm

# Sağlık kontrolü
free -h && df -h / && systemctl status ollama --no-pager
```
