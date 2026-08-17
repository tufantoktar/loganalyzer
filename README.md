# loganalyzer

Log dosyalarini deterministik olarak analiz eden, sonucu **Ollama**'ya yorumlatan CLI.
Docker'da paketlenir, **GitLab CI**'da test edilir, **Nexus**'a push edilir.

Amac sadece "bir sey yapan kod" degil; **Docker → GitLab CI → Nexus → Python/Bash → Ollama**
zincirinin ucundan ucuna calistigi kucuk ama gercek bir ornek.

---

## Mimari

```
┌────────────┐   bash        ┌────────────┐   python      ┌────────────┐
│ log dosya- │ ─────────────>│ collect_   │ ─────────────>│  parser.py │
│ lari       │  find/zcat    │ logs.sh    │  merged.log   │  (regex)   │
└────────────┘               └────────────┘               └─────┬──────┘
                                                                │
                                          deterministik ozet (JSON, ~2KB)
                                                                │
                                                          ┌─────▼──────┐
                                                          │  Ollama    │
                                                          │ /api/chat  │
                                                          └─────┬──────┘
                                                                │
                                                          ┌─────▼──────┐
                                                          │ report.md  │
                                                          └────────────┘
```

**Onemli tasarim karari:** LLM'e ham log gitmez. Once Python tarafinda
deterministik ozet cikarilir (seviye dagilimi, hata imzalari, hata orani),
LLM sadece bu ozeti yorumlar. Sebep:

| Sorun | Cozum |
|---|---|
| 500K satir context'e sigmaz | ~2KB'lik ozet gonder |
| LLM sayi saymayi beceremez | Sayilar `Counter`'dan gelir, LLM'den degil |
| Loglarda parola/token/PII olabilir | `redact()` katmani ozeti maskeler |
| CI ciktisi her seferinde degisirse ise yaramaz | `temperature=0` |

Hata imzasi cikarma (`signature()`) sayesinde
`Timeout after 3021ms for user 42` ve `Timeout after 88ms for user 7`
ayni gruba duser — 85 satirlik gurultu 4 imzaya iner.

---

## Hizli baslangic

```bash
# 1) Bagimliliklar
make venv && source .venv/bin/activate

# 2) LLM'siz calistir (Ollama gerekmez)
make run
cat reports/report.md

# 3) Ollama ile
make up            # ollama + nexus ayaga kalkar
make pull-model    # llama3.2:3b indirir (~2GB)
make run-llm
```

### Docker ile

```bash
make build
make docker-run    # compose icinde ollama'ya baglanarak calisir
```

---

## CLI

```bash
python -m loganalyzer <path> [secenekler]
```

| Secenek | Aciklama |
|---|---|
| `path` | Log dosyasi veya klasor |
| `--pattern` | Klasor taramasi glob'u (varsayilan `*.log`) |
| `-o, --out` | Cikti dosyasi (yoksa stdout) |
| `-f, --format` | `md` \| `json` |
| `--no-llm` | Ollama'yi atla |
| `--model` | Ollama modeli (env `OLLAMA_MODEL`) |
| `--ollama-host` | Ollama adresi (env `OLLAMA_HOST`) |
| `--pull` | Model yoksa otomatik indir |
| `--fail-over RATE` | Hata orani asilirsa **exit 2** |

**Exit kodlari** — CI'da bunlar onemli:

| Kod | Anlam |
|---|---|
| 0 | Temiz |
| 1 | Calisma hatasi (dosya yok vs.) |
| 2 | Hata orani esigi asildi |

Ollama erisilemezse arac **patlamaz**: LLM bolumunu atlar, istatistik raporunu
yine uretir ve 0 doner. Bu bilincli — gozlemlenebilirlik araci, izlenen sistemden
daha kirilgan olmamali.

### Bash tarafi

```bash
./scripts/collect_logs.sh -s /var/log/myapp -o /tmp/merged.log -H 24
```

`.gz`/`.bz2` acar, son N saati filtreler, cikti 50MB'i asarsa sondan kirpar
(son olaylar en degerlisi). `set -Eeuo pipefail` + `trap` ile hata yutmaz.

---

## Nexus kurulumu

`make up` sonrasi `http://localhost:8081`:

```bash
make nexus-password     # ilk admin parolasi
```

### 1. Docker hosted repo

`Settings > Repositories > Create repository > docker (hosted)`

- Name: `docker-hosted`
- **HTTP port: `8082`** (compose'da bu port zaten expose edilmis)
- "Allow anonymous docker pull" -> ihtiyaca gore

Sonra `Settings > Security > Realms` -> **Docker Bearer Token Realm**'i aktif et.
Bu adim atlanirsa `docker login` calismaz; en sik takilinan yer burasi.

### 2. Insecure registry (lokal, TLS yok)

Docker Desktop > Settings > Docker Engine:

```json
{ "insecure-registries": ["localhost:8082"] }
```

### 3. Push

```bash
docker login localhost:8082
make push REGISTRY=localhost:8082 TAG=dev
```

### 4. (Opsiyonel) PyPI proxy

`Create repository > pypi (proxy)`, remote: `https://pypi.org/`
Sonra build'de:

```bash
docker build --build-arg PIP_INDEX_URL=http://nexus:8081/repository/pypi-proxy/simple .
```

---

## GitLab CI

`.gitlab-ci.yml` stage'leri:

| Stage | Job | Ne yapar |
|---|---|---|
| lint | `ruff`, `shellcheck`, `hadolint` | Python / bash / Dockerfile lint |
| test | `pytest` | 52 test, coverage + junit raporu |
| test | `smoke` | CLI'yi uctan uca calistirir, ciktiyi dogrular |
| build | `build-image` | Imaji build eder, `--version` ile dogrular |
| scan | `trivy` | CVE taramasi |
| publish | `push-nexus` | `:<sha>` ve `:<branch>` tag'leriyle Nexus'a push |
| release | `release-latest` | Git tag'inde `:latest` + `:vX.Y.Z` |
| release | `nightly-analysis` | Schedule'da gercek loglari Ollama ile analiz eder |

### Gerekli CI/CD degiskenleri

`Settings > CI/CD > Variables`:

| Degisken | Ornek | Not |
|---|---|---|
| `NEXUS_DOCKER_REGISTRY` | `nexus.sirket.local:8082` | protected |
| `NEXUS_USER` | `ci-publisher` | masked |
| `NEXUS_PASSWORD` | `...` | masked + protected |
| `NEXUS_PYPI_INDEX` | `http://nexus:8081/repository/pypi-proxy/simple` | opsiyonel |

Imaj **iki** tag'le itilir: `:<commit-sha>` (izlenebilirlik, hangi commit
production'da bilinsin) ve `:<branch>` (kullanim + build cache kaynagi).

`build-image` push'tan once `docker run ... --version` calistirir — bozuk imaj
Nexus'a girmez.

---

## Test

```bash
make test
```

52 test: parser (format cesitleri, imza gruplama, redaction), Ollama istemcisi
(retry/backoff, health, mock'lu — gercek servise baglanmaz), CLI (exit kodlari,
Ollama yokken graceful degradation).

---

## Dosya yapisi

```
loganalyzer/
├── loganalyzer/
│   ├── cli.py             # argparse, exit kodlari, orkestrasyon
│   ├── parser.py          # regex parse + deterministik analiz + redaction
│   ├── ollama_client.py   # HTTP istemci, retry, model pull
│   └── report.py          # markdown / json render
├── scripts/
│   ├── collect_logs.sh    # log toplama (find/zcat/tail)
│   ├── entrypoint.sh      # Ollama hazir olana kadar bekler
│   └── gen_sample_logs.sh # sentetik test logu
├── tests/                 # pytest, tamami mock'lu
├── Dockerfile             # multi-stage, non-root, healthcheck
├── docker-compose.yml     # ollama + nexus + analyzer
├── .gitlab-ci.yml         # 6 stage
└── Makefile
```

---

## Sik karsilasilan sorunlar

| Belirti | Sebep |
|---|---|
| `docker login` 401 veriyor | Nexus'ta Docker Bearer Token Realm kapali |
| `http: server gave HTTP response to HTTPS client` | `insecure-registries`'e registry eklenmemis |
| Ollama'ya baglanamiyor (compose) | `localhost` degil `http://ollama:11434` kullan |
| Nexus ilk acilista 503 | Normal, 2-3 dk surer (`start_period: 120s`) |
| CI'da imaj build cache'i tutmuyor | `--cache-from` icin once `docker pull` gerekir |
