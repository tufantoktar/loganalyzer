# Mac Kurulum Rehberi

`KURULUM.md` Ubuntu için yazıldı — sen Mac kullanıyorsan **bunu** takip et.
VPS tarafı için `VPS-KURULUM.md` ayrı duruyor, o Ubuntu ve doğru.

## Rollerin dağılımı

| Makine | Ne yapıyor |
|---|---|
| **Mac** (burası) | Kod yazma, test, GitHub'a push, Nexus'u öğrenme |
| **VPS** | Asıl iş — Polymarket loglarını her gün analiz etme |

Mac'te Ollama çalıştırman **şart değil** (VPS'te olacak), ama istersen çalıştırırsın —
Apple Silicon'da hızlı çalışır, hatta VPS'ten iyi.

**En acil iş:** kodu GitHub'a atmak (Adım 3). VPS oradan çekecek. Diğer adımlar öğrenme amaçlı.

---

## Adım 1 — Terminal ve temel araçlar

`Cmd` + `Boşluk` → "Terminal" yaz → Enter.

### 1.1 Xcode Command Line Tools

`git` ve `make` bununla geliyor:

```bash
xcode-select --install
```

Bir pencere açılırsa "Install" de, birkaç dakika sürer. "already installed"
derse zaten var, devam et.

Doğrula:

```bash
git --version && make --version | head -1 && python3 --version
```

Üçü de sürüm yazmalı. `python3` yoksa Adım 1.2'deki Homebrew ile kur.

### 1.2 Homebrew (opsiyonel ama işe yarar)

Mac'te paket kurmanın standart yolu:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Kurulum sonunda ekrana **iki komut** yazar (`eval "$(/opt/homebrew/bin/brew shellenv)"` gibi) —
onları da çalıştır, yoksa `brew` komutu bulunamaz.

---

## Adım 2 — Projeyi yerine koy

Claude'un oluşturduğu `loganalyzer` klasörünü düzgün bir yere taşı:

```bash
mkdir -p ~/projeler
# loganalyzer klasorunu Finder'dan ~/projeler icine surukle, sonra:
cd ~/projeler/loganalyzer
ls
```

`Dockerfile`, `Makefile`, `loganalyzer`, `scripts`, `tests` görmelisin.

> Terminalde bir klasörün yolunu öğrenmenin kolay yolu: `cd ` yazıp (boşlukla)
> klasörü Finder'dan terminale sürükle, yol kendiliğinden yazılır.

---

## Adım 3 — GitHub'a gönder (öncelikli adım)

### 3.1 Git'i tanıt

```bash
git config --global user.name "Adın Soyadın"
git config --global user.email "utkutoktar2016@gmail.com"
```

### 3.2 SSH bağlantısını doğrula

SSH anahtarın zaten kurulu. Çalıştığını teyit et:

```bash
ssh -T git@github.com
```

**Görmen gereken:** `Hi tufantoktar! You've successfully authenticated...`

Bu mesajı görüyorsan token'a, parolaya hiç gerek yok — SSH hallediyor.

> `Permission denied (publickey)` alırsan anahtar GitHub'a eklenmemiş demektir:
> `cat ~/.ssh/id_ed25519.pub` çıktısını GitHub → Settings → SSH and GPG keys →
> New SSH key altına yapıştır.

### 3.3 Push

```bash
cd ~/projeler/loganalyzer
git init
git add .
git commit -m "loganalyzer ilk surum"
git branch -M main
git remote add origin git@github.com:tufantoktar/loganalyzer.git
git push -u origin main
```

> Adresin `git@github.com:` ile başlaması önemli. `https://` ile başlarsa SSH
> değil HTTPS kullanır ve token ister. Yanlışlıkla https eklediysen düzelt:
> `git remote set-url origin git@github.com:tufantoktar/loganalyzer.git`

**Bu adım bitince VPS kurulumuna geçebilirsin** — `VPS-KURULUM.md` Adım 4.

---

## Adım 4 — Mac'te çalıştır (opsiyonel, öğrenmek için)

```bash
cd ~/projeler/loganalyzer
make venv
source .venv/bin/activate
make test
```

`57 passed` görmelisin.

```bash
make run
cat reports/report.md
```

Sentetik log üretip analiz eder. VPS'teki gerçek verinin küçük provası.

> **Not:** `scripts/gen_sample_logs.sh` içindeki `date -u -d` GNU sözdizimi;
> script macOS'un `date -u -r` biçimine otomatik düşüyor, çalışması gerek.
> Sorun çıkarsa `brew install coreutils` kurup `gdate` kullanabilirsin,
> ama bu script sadece test verisi üretiyor — VPS'te zaten gerçek log var.

---

## Adım 5 — Ollama (opsiyonel, Mac'te hızlı)

```bash
brew install ollama
brew services start ollama
ollama pull llama3.2:3b
```

Homebrew kullanmıyorsan ollama.com/download adresinden `.dmg` indir.

Mac'in belleği VPS'ten fazla olduğu için burada **3B model** kullanabilirsin
(VPS'te 1.5B'ye mecburuz):

```bash
make run-llm
cat reports/report.md
```

Apple Silicon'da GPU hızlandırma devrede, cevap birkaç saniyede gelir.

---

## Adım 6 — Docker ve Nexus (opsiyonel, öğrenmek için)

VPS'te Docker **kurmuyoruz** (gerek yok, RAM dar). Ama Docker ve Nexus'u
öğrenmek istersen yeri burası.

### 6.1 Docker Desktop

```bash
brew install --cask docker
```

Kurulum bitince **Applications'tan Docker'ı aç** — sadece kurmak yetmez,
uygulamanın çalışıyor olması gerekir. Üst menü çubuğunda balina ikonu belirir.

Doğrula:

```bash
docker run hello-world
```

### 6.2 İmajı build et

```bash
make build
```

> **Apple Silicon notu:** İmaj senin mimarinde (arm64) build olur. VPS'e
> göndereceksen `--platform linux/amd64` gerekir, yoksa "exec format error"
> alırsın. Ama VPS'te Docker kullanmadığımız için bu bizi ilgilendirmiyor.

### 6.3 Nexus

```bash
make up          # nexus konteynerini baslatir
make nexus-password
```

2-3 dakika bekle, sonra tarayıcıda **http://localhost:8081**

Kullanıcı `admin`, parola yukarıdaki komuttan çıkan metin.

Docker deposu oluşturma ve token realm adımları `KURULUM.md` Adım 7.3-7.4 ile
**aynı** (Nexus arayüzü işletim sisteminden bağımsız). Tek fark:

### 6.4 Insecure registry — Mac'te farklı

Ubuntu'da `/etc/docker/daemon.json` düzenleniyor. Mac'te dosyaya elle
dokunma, **Docker Desktop arayüzünden** yap:

Balina ikonu → **Settings** → **Docker Engine** → JSON'a ekle:

```json
{
  "insecure-registries": ["localhost:8082"]
}
```

**Apply & Restart**.

Sonra:

```bash
docker login localhost:8082
make push REGISTRY=localhost:8082 TAG=dev
```

> Nexus imajı amd64; Apple Silicon'da emülasyonla çalışır, biraz yavaştır ama
> sorun değil. RAM'i kısıtlıysa Docker Desktop → Settings → Resources'tan
> Docker'a en az 4 GB ver.

---

## Adım 7 — GitHub Actions

Depona git → **Settings** → **Actions** → **General** → altta
**Workflow permissions** → **Read and write permissions** → Save.

Sonra **Actions** sekmesinde pipeline'ın çalıştığını göreceksin: lint, test, build.

---

## Mac'e özel sorun giderme

### `command not found: brew`

Homebrew kurulumunun sonundaki `eval "$(/opt/homebrew/bin/brew shellenv)"`
satırını çalıştırmamışsın. Kalıcı yapmak için:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
source ~/.zprofile
```

### `xcrun: error: invalid active developer path`

macOS güncellemesi sonrası klasik hata:

```bash
xcode-select --install
```

### `docker: Cannot connect to the Docker daemon`

Docker Desktop uygulaması açık değil. Applications'tan başlat, menü çubuğunda
balina ikonunu bekle.

### `make: *** No rule to make target`

Yanlış klasördesin:

```bash
cd ~/projeler/loganalyzer && ls Makefile
```

### Git push'ta `Authentication failed`

Parola değil **token** girmen gerekiyor (Adım 3.3). Keychain'de yanlış kayıt
varsa temizle:

```bash
git credential-osxkeychain erase
host=github.com
protocol=https
```

(son satırdan sonra boş satır bırakıp `Ctrl+D`)

### `sed`/`date` komutları farklı davranıyor

macOS BSD araçlarını kullanır, Linux GNU. Fark yaşarsan:

```bash
brew install coreutils gnu-sed
```

`gdate`, `gsed` olarak kurulur. Bu projede sadece `gen_sample_logs.sh`
etkileniyor, o da test verisi üretiyor — kritik değil.

---

## Kopya kağıdı

```bash
cd ~/projeler/loganalyzer
source .venv/bin/activate

make test                    # testler
make run                     # rapor (AI yok)
make run-llm                 # rapor (AI'li)

git add . && git commit -m "ne yaptigin" && git push

ssh root@VPS_IP              # sunucuya baglan
```
