# Sıfırdan Kurulum Rehberi (Ubuntu + GitHub)

Hiç bilmiyorum diyene göre yazıldı. Her adımda **ne yazacağın** ve **ne görmen
gerektiği** ayrı ayrı var. Bir adım beklenen çıktıyı vermezse durup en alttaki
"Sorun Giderme" bölümüne bak, sonrakine geçme.

**Toplam süre:** ~1 saat (indirmeler dahil, çoğu bekleme)

---

## Yol haritası

Şu 9 adımı sırayla yapacağız. Her adımın sonunda çalışan bir şey olacak:

| # | Adım | Sonunda ne olacak |
|---|---|---|
| 1 | Terminal'i tanı | Komut yazabiliyorsun |
| 2 | Docker kur | `docker run hello-world` çalışıyor |
| 3 | Projeyi indir | Dosyalar bilgisayarında |
| 4 | Python ile çalıştır | İlk rapor üretildi (LLM yok) |
| 5 | Ollama kur | Rapora yapay zeka yorumu eklendi |
| 6 | Docker imajı yap | Proje bir konteynerde çalışıyor |
| 7 | Nexus kur | İmaj kendi depona yüklendi |
| 8 | GitHub'a yükle | Kod internette |
| 9 | GitHub Actions | Her push'ta testler otomatik koşuyor |

Sıkılırsan **4. adımdan sonra** dur — orası zaten çalışan bir proje. Gerisi
"profesyonel ortamda nasıl yapılıyor" kısmı.

---

## Adım 1 — Terminal

Ubuntu'da `Ctrl` + `Alt` + `T` tuşlarına bas. Siyah bir pencere açılır. Adı **terminal**.

Bundan sonra "şunu çalıştır" dediğim her şeyi buraya yazıp `Enter`'a basacaksın.

İlk denemen:

```bash
whoami
```

Kullanıcı adın yazmalı. Yazdıysa terminal çalışıyor demektir.

**Bilmen gereken 3 şey:**

- `sudo` ile başlayan komutlar yönetici yetkisi ister → **parolanı sorar, yazarken ekranda hiçbir şey görünmez.** Bu normal, bozuk değil. Yazıp Enter'a bas.
- Terminalde `Ctrl+C` = çalışan komutu durdur.
- Komutu kopyala-yapıştır yapabilirsin: `Ctrl+Shift+V` ile yapıştırılır (normal `Ctrl+V` değil).

---

## Adım 2 — Docker kurulumu

Docker, uygulamaları izole "kutu"larda (konteyner) çalıştıran araç. Nexus ve
Ollama'yı da bununla kuracağız, kendi bilgisayarını kirletmeden.

### 2.1 Docker'ın deposunu sisteme tanıt

Aşağıdakinin **tamamını** kopyalayıp terminale yapıştır, Enter'a bas:

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
```

> Bu blok Docker'ın resmi imza anahtarını indirip, paket kaynaklarına Docker'ın
> deposunu ekliyor. Ubuntu'nun kendi deposundaki Docker eski olduğu için bunu yapıyoruz.

### 2.2 Docker'ı kur

```bash
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Birkaç dakika sürer.

### 2.3 `sudo` yazmadan kullanabilmek için

```bash
sudo usermod -aG docker $USER
```

**Bu komuttan sonra oturumu kapatıp açman gerekiyor.** En kolayı bilgisayarı
yeniden başlat, ya da çıkış yapıp tekrar gir.

> Neden? Grup üyeliği sadece yeni oturumlarda geçerli olur. Yeniden başlatmazsan
> her docker komutunda "permission denied" alırsın.

### 2.4 Test et

Yeniden giriş yaptıktan sonra:

```bash
docker run hello-world
```

**Görmen gereken:**

```
Hello from Docker!
This message shows that your installation appears to be working correctly.
```

Bunu gördüysen Docker hazır. Görmediysen → Sorun Giderme #1.

---

## Adım 3 — Projeyi bilgisayarına al

Proje klasörünü (`loganalyzer`) Claude sana verdi. Onu ev dizinine taşı:

```bash
mkdir -p ~/projeler
# İndirdiğin loganalyzer klasörünü ~/projeler/ içine kopyala
cd ~/projeler/loganalyzer
ls
```

**Görmen gereken:** `Dockerfile`, `Makefile`, `README.md`, `loganalyzer`, `scripts`, `tests` gibi isimler.

> `cd` = "change directory", klasöre gir demek. `ls` = içindekileri listele.
> `~` işareti senin ev dizinin (`/home/kullaniciadin`) anlamına gelir.

**Önemli:** Bundan sonraki tüm komutlar bu klasörün içinde çalıştırılacak. Yeni bir
terminal açtığında ilk iş `cd ~/projeler/loganalyzer` yaz.

Bir de Python araçlarını kuralım:

```bash
sudo apt install -y python3 python3-pip python3-venv make git
```

---

## Adım 4 — İlk çalıştırma (yapay zeka olmadan)

Burası ilk gerçek başarı anın.

### 4.1 Sanal ortam kur

```bash
make venv
source .venv/bin/activate
```

**Görmen gereken:** Terminal satırının başına `(.venv)` eklenir.

> Sanal ortam = projenin Python paketlerini sistem geneline değil, proje klasörüne
> kuran bir kutu. Böylece farklı projeler birbirinin paketini bozmaz.
> `source .venv/bin/activate` = "bu kutuya gir" demek. Terminali kapatınca çıkarsın,
> tekrar girmen gerekir.

### 4.2 Testleri çalıştır

```bash
make test
```

**Görmen gereken:** En altta `52 passed` benzeri yeşil bir satır.

> Bu, kodun düzgün çalıştığının kanıtı. 52 küçük kontrol geçti demek.

### 4.3 Örnek log üret ve analiz et

```bash
make run
```

**Görmen gereken:**

```
INFO loganalyzer: 1 dosya analiz ediliyor
INFO loganalyzer: 500 satir, hata orani 17.00%
INFO loganalyzer: Rapor yazildi: reports/report.md
```

Raporu aç:

```bash
cat reports/report.md
```

Seviye dağılımı tablosu, servis listesi, en sık hata imzaları göreceksin.
**Tebrikler — proje çalışıyor.**

En altta "LLM analizi atlandı" yazıyor, çünkü henüz Ollama kurmadık. Sıradaki adım o.

---

## Adım 5 — Ollama (yapay zeka kısmı)

### 5.1 Kur

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

> Bu komut Ollama'nın resmi kurulum scriptini indirip çalıştırıyor. Kurulum
> bitince Ollama arka planda servis olarak çalışmaya başlar.

Kontrol et:

```bash
ollama --version
```

### 5.2 Model indir

```bash
ollama pull llama3.2:3b
```

**Yaklaşık 2 GB indirir**, internet hızına göre 5-15 dakika. Bir kahve al.

> `3b` = 3 milyar parametre. Küçük bir model, sıradan bir bilgisayarda çalışır.
> Daha güçlü sonuç istersen `llama3.1:8b` denersin ama ~5GB ve daha yavaş.

### 5.3 Ollama ayakta mı?

```bash
curl http://localhost:11434/api/tags
```

**Görmen gereken:** İçinde `llama3.2:3b` geçen bir JSON çıktısı.

### 5.4 Yapay zeka yorumlu rapor üret

```bash
make run-llm
cat reports/report.md
```

Bu sefer raporun sonunda **"LLM Değerlendirmesi"** bölümü dolu olacak: Özet,
Olası Kök Nedenler, Önerilen Aksiyonlar.

İlk çalıştırmada 30-60 saniye sürebilir, model belleğe yükleniyor. Sonrakiler hızlı.

> **Burada ne oldu?** Python 500 satırı okudu, saydı, hata imzalarını grupladı ve
> ~2 KB'lık bir özet çıkardı. Ollama'ya **ham log değil, sadece o özet** gitti.
> Model de onu yorumladı. Loglar bilgisayarından hiç çıkmadı — Ollama tamamen yerel.

---

## Adım 6 — Docker imajı

Şimdiye kadar projeyi kendi Python'unla çalıştırdın. Şimdi onu taşınabilir bir
"kutu"ya koyalım — başka bir makinede Python kurmadan çalışsın diye.

### 6.1 Build et

```bash
make build
```

İlk seferde 2-3 dakika sürer. **Görmen gereken:** En sonda `naming to docker.io/library/loganalyzer:dev` benzeri bir satır.

### 6.2 İmajı gör

```bash
docker images | grep loganalyzer
```

### 6.3 Konteyner içinde çalıştır

```bash
make docker-run
cat reports/report.md
```

> `make docker-run` şunu yapıyor: Ollama'yı ve uygulamayı aynı sanal ağda
> başlatıp, örnek logları konteynere bağlayıp analizi konteyner içinde çalıştırıyor.
> Rapor yine senin `reports/` klasörüne düşüyor.

---

## Adım 7 — Nexus (kendi imaj deponu kur)

Nexus, şirketlerin Docker imajlarını ve paketlerini sakladığı depo yazılımı.
Docker Hub'ın şirket içi versiyonu diye düşün.

**Uyarı:** Nexus yaklaşık 2 GB RAM kullanır. Bilgisayarın 8 GB altındaysa
Ollama'yı kapatıp öyle dene.

### 7.1 Başlat

```bash
docker compose up -d nexus
```

> `-d` = arka planda çalıştır. Terminal sana geri döner.

**İlk açılış 2-3 dakika sürer.** Sabırlı ol. Durumu izlemek için:

```bash
docker compose logs -f nexus
```

`Started Sonatype Nexus OSS` satırını görünce `Ctrl+C` ile log izlemeden çık
(bu Nexus'u durdurmaz, sadece log akışını kapatır).

### 7.2 Giriş yap

Tarayıcıda aç: **http://localhost:8081**

Parolayı öğren:

```bash
make nexus-password
```

Sağ üstten **Sign in**:

- Kullanıcı: `admin`
- Parola: yukarıdaki komuttan çıkan uzun metin

İlk girişte yeni parola belirlemeni ister. **Belirlediğin parolayı bir yere yaz**,
birazdan lazım olacak. Anonymous access sorusuna "Enable" diyebilirsin.

### 7.3 Docker deposu oluştur

Üstteki **dişli ikonu** (Settings) → sol menüden **Repositories** → **Create repository**

Listeden **`docker (hosted)`** seç. Sonra:

| Alan | Değer |
|---|---|
| Name | `docker-hosted` |
| HTTP | ☑ **işaretle**, port kutusuna **`8082`** yaz |
| Allow anonymous docker pull | işaretlemene gerek yok |

En altta **Create repository**.

### 7.4 Token realm'i aç (BU ADIMI ATLAMA)

Settings → sol menüde **Security** → **Realms**

Soldaki "Available" listesinden **`Docker Bearer Token Realm`** bul, sağ tarafa
(Active) taşı, **Save**.

> **Bu adım atlanırsa `docker login` her seferinde hata verir.** Nexus'ta en çok
> takılınan yer burası. Docker'ın kimlik doğrulama yöntemi normal kullanıcı
> adı/parolasından farklı, o yüzden ayrıca açılması gerekiyor.

### 7.5 Docker'a "bu depo şifresiz, sorun değil" de

Nexus'u localde HTTPS sertifikası olmadan kurduk. Docker varsayılan olarak
sertifikasız depolara bağlanmayı reddeder. İzin verelim:

```bash
sudo nano /etc/docker/daemon.json
```

Açılan editöre şunu yaz (dosya boşsa tamamını, doluysa dikkatlice birleştir):

```json
{
  "insecure-registries": ["localhost:8082"]
}
```

Kaydet: `Ctrl+O` → `Enter` → çık: `Ctrl+X`

Docker'ı yeniden başlat:

```bash
sudo systemctl restart docker
```

> Gerçek bir şirket ortamında bunu yapmazsın — orada Nexus'un düzgün bir TLS
> sertifikası olur. Bu sadece lokal deneme için.

### 7.6 Giriş yap ve push et

```bash
docker login localhost:8082
```

Kullanıcı `admin`, parola 7.2'de belirlediğin yeni parola.

**Görmen gereken:** `Login Succeeded`

Şimdi imajı gönder:

```bash
make push REGISTRY=localhost:8082 TAG=dev
```

### 7.7 Doğrula

Tarayıcıda Nexus → sol menü **Browse** → `docker-hosted` → içinde
`loganalyzer` ve `dev` etiketini göreceksin.

**Bu noktada kendi özel imaj depona sahipsin.** Başka bir makineden
`docker pull localhost:8082/loganalyzer:dev` ile çekebilirsin.

---

## Adım 8 — GitHub'a yükle

### 8.1 Git'i tanıt

```bash
git config --global user.name "Adın Soyadın"
git config --global user.email "utkutoktar2016@gmail.com"
```

### 8.2 GitHub'da boş depo aç

github.com → sağ üstte **+** → **New repository**

- Repository name: `loganalyzer`
- Public ya da Private, fark etmez
- **Add a README file'ı İŞARETLEME** (bizde zaten var, çakışır)

**Create repository**.

### 8.3 Kimlik doğrulama için token al

GitHub artık parola kabul etmiyor, token istiyor.

github.com → sağ üst profil → **Settings** → en altta **Developer settings** →
**Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**

- Note: `loganalyzer`
- Expiration: 90 days
- Kutulardan **`repo`** ve **`write:packages`** işaretle

**Generate token** → çıkan `ghp_...` ile başlayan metni **hemen kopyala ve bir
yere kaydet.** Sayfayı kapatınca bir daha göremezsin.

### 8.4 Kodu gönder

```bash
cd ~/projeler/loganalyzer
git init
git add .
git commit -m "İlk commit: loganalyzer"
git branch -M main
git remote add origin https://github.com/KULLANICI_ADIN/loganalyzer.git
git push -u origin main
```

`KULLANICI_ADIN` yerine kendi GitHub kullanıcı adını yaz.

Kullanıcı adı sorduğunda GitHub kullanıcı adını, **parola sorduğunda 8.3'teki
token'ı** yapıştır.

**Görmen gereken:** `Branch 'main' set up to track 'origin/main'.`

Tarayıcıda depona bak — dosyalar orada olmalı.

> `git init` = bu klasörü git ile takip etmeye başla.
> `git add .` = tüm dosyaları gönderilecekler listesine ekle.
> `git commit` = bir "kayıt noktası" oluştur.
> `git push` = kayıtları GitHub'a yolla.

---

## Adım 9 — GitHub Actions

En güzel kısım: artık her kod gönderdiğinde testler otomatik çalışacak.

### 9.1 İzinleri aç

GitHub'da depona git → **Settings** (deponun kendi ayarları, hesap ayarları değil)
→ sol menüde **Actions** → **General** → sayfanın altında **Workflow permissions**
→ **Read and write permissions** seç → **Save**

> Bu, pipeline'ın ürettiği Docker imajını GitHub'ın kendi imaj deposuna
> (ghcr.io) yükleyebilmesi için gerekli.

### 9.2 Çalıştığını gör

Zaten 8.4'te push yaptığın için pipeline muhtemelen çoktan başladı.
Depona git → üstten **Actions** sekmesi.

Sarı nokta = çalışıyor, yeşil tik = başarılı, kırmızı çarpı = hata.

İçine tıklayınca 3 iş göreceksin:

| İş | Ne yapıyor |
|---|---|
| `lint` | Python, bash ve Dockerfile'ı kural denetimine sokuyor |
| `test` | 52 testi koşuyor + CLI'yi uçtan uca deniyor |
| `build` | Docker imajını yapıp güvenlik taramasından geçiriyor, sonra ghcr.io'ya yüklüyor |

Her adımın yanındaki oka tıklayarak logları okuyabilirsin.

### 9.3 Kendin dene

Bir dosyada ufak bir değişiklik yap:

```bash
echo "" >> README.md
git add .
git commit -m "test: pipeline denemesi"
git push
```

Actions sekmesine dön — yeni bir çalışma başladığını göreceksin.

**İşte CI/CD bu.** Her değişiklikte kimse elle bir şey yapmadan testler koşuyor,
imaj üretiliyor, güvenlik taraması yapılıyor.

---

## Bitti — ne kurmuş olduk?

```
  Sen kod yazıyorsun
        │
        ▼  git push
   GitHub deposu
        │
        ▼  otomatik
  GitHub Actions ──► lint ──► test ──► docker build ──► ghcr.io
        
  Lokalde:
  loglar ──► collect_logs.sh (bash) ──► parser.py (python)
                                             │
                                     deterministik özet
                                             │
                                             ▼
                                       Ollama (yerel AI)
                                             │
                                             ▼
                                        report.md
                                             
  Docker imajı ──► Nexus (kendi deponuz)
```

Öğrendiğin şeyler: konteynerleştirme, CI/CD pipeline, artifact repository,
bash+python iş bölümü, yerel LLM entegrasyonu. Bunlar bir DevOps ilanındaki
maddelerin çoğu.

---

## Sorun Giderme

### #1 — `docker: permission denied`

Grup değişikliği için oturumu kapatıp açmadın. Bilgisayarı yeniden başlat.
Acele işin varsa geçici çözüm:

```bash
newgrp docker
```

### #2 — `Cannot connect to the Docker daemon`

Docker servisi çalışmıyor:

```bash
sudo systemctl start docker
sudo systemctl enable docker   # açılışta otomatik başlasın
```

### #3 — `make: command not found`

```bash
sudo apt install -y make
```

### #4 — `docker login` 401 / unauthorized veriyor

Adım 7.4'ü atlamışsın. Nexus → Settings → Security → Realms →
**Docker Bearer Token Realm**'i aktif listeye taşı, Save.

### #5 — `http: server gave HTTP response to HTTPS client`

Adım 7.5'i atlamışsın ya da Docker'ı yeniden başlatmamışsın:

```bash
sudo systemctl restart docker
```

### #6 — Nexus açılmıyor, tarayıcı bağlanamıyor diyor

Henüz başlamamıştır, ilk açılış uzun sürer:

```bash
docker compose logs --tail 20 nexus
```

`Started Sonatype Nexus` görene kadar bekle. 5 dakikadan uzun sürüyorsa RAM
yetmiyor olabilir — Ollama'yı durdurup dene: `sudo systemctl stop ollama`

### #7 — Ollama'ya bağlanamıyor

```bash
systemctl status ollama      # çalışıyor mu?
sudo systemctl start ollama  # başlat
curl http://localhost:11434/api/tags
```

Konteyner içinden bağlanıyorsan `localhost` **değil** `http://ollama:11434`
kullanılmalı — konteyner içinde `localhost` konteynerin kendisi demektir.

### #8 — `make run-llm` çok yavaş / takılı kaldı

Normal. İlk çağrıda model belleğe yükleniyor, 1 dakikayı bulabilir.
Devam ederse daha küçük bir model dene:

```bash
ollama pull qwen2.5:1.5b
make run-llm MODEL=qwen2.5:1.5b
```

### #9 — GitHub push'ta `Authentication failed`

Parola yerine token kullanman gerekiyor (Adım 8.3). Token'ı kaybettiysen yenisini
üret. Sürekli sormasın istiyorsan:

```bash
git config --global credential.helper store
```

(Bir sonraki push'ta girdiğin token diske kaydedilir — sadece kendi bilgisayarında yap.)

### #10 — GitHub Actions kırmızı çarpı verdi

Actions sekmesinde kırmızı olan işe tıkla, kırmızı adımı aç, logun **en altına**
bak. Genelde hangi testin neden patladığını açıkça yazar. Hata mesajını bana
gönderirsen bakarım.

### #11 — Her şeyi sıfırlamak istiyorum

```bash
docker compose down -v    # konteynerleri ve verileri sil
make clean                # üretilen dosyaları sil
```

---

## Günlük kullanım kopya kağıdı

```bash
cd ~/projeler/loganalyzer     # projeye gir
source .venv/bin/activate     # python ortamına gir

make test                     # testleri koş
make run                      # rapor üret (hızlı, AI yok)
make run-llm                  # rapor üret (AI yorumlu)
make build                    # docker imajı yap

docker compose up -d nexus    # nexus'u başlat
docker compose down           # her şeyi durdur

git add . && git commit -m "ne yaptığın" && git push   # GitHub'a gönder
```
