"""Ollama HTTP istemcisi.

Ollama'yi bilerek /api/chat uzerinden, stream kapali kullaniyoruz:
CI icinde deterministik ve tek seferlik bir cikti istiyoruz.
temperature=0 -> ayni ozet ayni yorumu uretsin (buildler karsilastirilabilir olsun).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

SYSTEM_PROMPT = """Sen bir SRE asistanisin. Sana bir log dosyasinin ISTATISTIKSEL OZETI (JSON)
verilecek. Ham log YOK; elinde sadece sayilar ve hata imzalari var.

MUTLAK KURALLAR:
1. SADECE ozette yazan sayilari kullan. Carpma, toplama, oran hesaplama, tahmin etme.
   Ozette olmayan bir sayi yazarsan cevap gecersizdir.
2. Bilmedigin kisaltmayi ACMA, oldugu gibi birak. Ornek: "CLOB" -> "CLOB" yaz,
   ne anlama geldigini uydurma.
3. Her maddeyi FARKLI yaz. Ayni cumleyi tekrarlama. Tekrar edeceksen madde yazma.
4. Ozetten cikmayan bir sey soruluyorsa "ozetten anlasilmiyor" de.

HTTP DURUM KODLARI (her satir kendi basina gecerlidir, birini digerine karistirma):
- 401 = kimlik dogrulama basarisiz. API anahtari eksik veya gecersiz.
- 403 = kimlik dogru ama bu kaynaga yetki yok.
- 404 = istenen kaynak bulunamadi. Kayit hic yok ya da henuz olusmamis.
        DIKKAT: 404 bir SUNUCU hatasi DEGILDIR. "Sunucu tarafi hata" DEME.
- 429 = hiz siniri asildi. Istek sikligi fazla.
- 500, 502, 503, 504 = SADECE bunlar sunucu tarafi hatadir; istemci suclu degil.

SAYI KULLANIMI:
- "toplam N hata satiri" derken N olarak ozetteki "total_lines" degerini kullan.
- Bir imzanin adedi icin o imzanin kendi "count" degerini kullan.
- Bu ikisini birbirine karistirma.

Cevabin 3 bolumden olussun: "## Ozet", "## Olasi Kok Nedenler", "## Onerilen Aksiyonlar".
Asagida ornek bir soru-cevap var; ayni bicimde, ama KENDI verinle cevap ver.
Ornekteki sayilari ASLA kopyalama.
"""

# --- Few-shot ornegi -------------------------------------------------------
# Kucuk modeller soyut format tarifini "icerik" sanip aynen kopyaliyor
# (qwen2.5:1.5b bunu yapti). Doldurulmus bir ornek gostermek tek etkili cozum.
# Ornek veri gercek veriden BILEREK cok farkli: sayilari kopyalarsa fark edilir.
FEWSHOT_USER = """Log ozeti (JSON):
```json
{
  "total_lines": 8000,
  "level_counts": {"INFO": 7160, "WARN": 600, "ERROR": 240},
  "services": {"api-gateway": 4100, "order-svc": 2400},
  "top_errors": [
    {"signature": "GET /orders failed: HTTP503", "count": 180},
    {"signature": "Query timeout after <n>", "count": 55},
    {"signature": "Redis connection refused", "count": 5}
  ],
  "error_rate": 0.03
}
```

Bu ozeti yukaridaki 3 bolumlu formatta degerlendir."""

FEWSHOT_ASSISTANT = """## Ozet
En buyuk hata imzasi `GET /orders failed: HTTP503`, 180 kez gorulmus.
Toplam 240 hata satirinin buyuk bolumunu tek basina olusturuyor.
Diger iki imza dusuk hacimli.

## Olasi Kok Nedenler
- `GET /orders failed: HTTP503` (180 kez): 503 sunucu tarafi hatadir; ustteki
  servis gecici olarak istekleri karsilayamiyor olabilir.
- `Query timeout after <n>` (55 kez): sorgular sure sinirini asiyor; veritabani
  yavaslamis ya da sorgu plani bozulmus olabilir.
- `Redis connection refused` (5 kez): hacmi dusuk; onbellek servisine erisim
  kisa sureli kesilmis olabilir.

## Onerilen Aksiyonlar
- Kontrol et: ustteki servisin saglik durumunu ve 503 donen zaman araligini.
- Sinirla: zaman asimina ugrayan sorgular icin sure ve eszamanlilik limitini.
- Ekle: Redis baglantisina yeniden deneme ve devre kesici."""


class OllamaError(RuntimeError):
    pass


@dataclass
class OllamaClient:
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    # GPU'suz bir VPS'te 3B model ~2-3 dk surebiliyor. 120 sn cok kisaydi:
    # ilk cagri zaman asimina ugrayip bosa uretim yapiyor, retry ile toplam
    # sure ikiye katlaniyordu. Gunde bir calisan bir is icin 300 sn makul.
    timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "300"))
    retries: int = 3

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.host.rstrip('/')}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, json.JSONDecodeError) as exc:
                last_error = exc
                backoff = 2 ** (attempt - 1)
                log.warning("Ollama cagrisi basarisiz (%s/%s): %s", attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(backoff)
        raise OllamaError(f"{url} cagrisi {self.retries} denemede basarisiz: {last_error}")

    def health(self) -> bool:
        """Servis ayakta mi? CI'da fail-fast icin."""
        try:
            response = requests.get(f"{self.host.rstrip('/')}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def available_models(self) -> list[str]:
        try:
            response = requests.get(f"{self.host.rstrip('/')}/api/tags", timeout=10)
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]
        except requests.RequestException as exc:
            raise OllamaError(f"Model listesi alinamadi: {exc}") from exc

    def ensure_model(self) -> None:
        """Model yoksa pull et. Ilk calistirmada isini gorur."""
        models = self.available_models()
        if any(m == self.model or m.startswith(f"{self.model}:") for m in models):
            return
        log.info("Model '%s' bulunamadi, pull ediliyor...", self.model)
        response = requests.post(
            f"{self.host.rstrip('/')}/api/pull",
            json={"model": self.model, "stream": False},
            timeout=1800,
        )
        response.raise_for_status()

    def chat(self, user_prompt: str, system: str = SYSTEM_PROMPT) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                # Few-shot: modele format tarif etmek yerine doldurulmus
                # bir ornek gosteriyoruz. Kucuk modellerde fark buyuk.
                {"role": "user", "content": FEWSHOT_USER},
                {"role": "assistant", "content": FEWSHOT_ASSISTANT},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0, "num_predict": 700},
        }
        data = self._post("/api/chat", payload)
        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise OllamaError(f"Model bos cevap dondu: {data}")
        return content


def find_invented_numbers(verdict: str, analysis_dict: dict) -> list[str]:
    """Modelin ozette olmayan sayi uydurup uydurmadigini denetler.

    Kucuk modeller "sayi uydurma" talimatini duzenli olarak cigniyor
    (ornek: 31527'yi 100 ile carpip 3.152.700 yazmak). Rapordaki sayilar
    karar vermek icin kullanilacagi icin bu sessizce gecilemez.

    Donen liste bostan farkliysa rapora uyari basilir.
    """
    allowed = set(re.findall(r"\d+", json.dumps(analysis_dict)))

    invented: list[str] = []
    for raw in re.findall(r"\d[\d.,]*\d|\d", verdict):
        digits = raw.replace(".", "").replace(",", "")
        if not digits.isdigit():
            continue
        # 100 ve altini serbest birak: madde numarasi, yuzde, durum kodu olabilir.
        if int(digits) <= 100:
            continue
        if digits in allowed:
            continue
        invented.append(raw)

    # Deterministik sirala: uzundan kisaya, esitlikte alfabetik.
    # set() iterasyon sirasi calistirmaya gore degisir, rapor sabit olmali.
    return sorted(set(invented), key=lambda s: (-len(s), s))


# Kucuk modellerin tekrarlayan, kanitlanmis hatalari.
# Prompt'ta acikca yasaklamak yetmiyor: ayni prompt ve temperature=0 ile bile
# model girdiye gore kurali cignedi. Duzeltmeye calismak yerine yakaliyoruz.
WRONG_CLAIM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        # "404 sunucu tarafi hatadir" -> 4xx istek hatasidir, sunucu hatasi degil
        re.compile(r"(?<!\d)(4\d{2})(?!\d)[^.\n]{0,70}?sunucu\s*(?:taraf|hata)", re.I),
        "4xx durum kodu 'sunucu tarafi hata' diye tanimlanmis. "
        "4xx istek/istemci hatasidir; sunucu hatasi 5xx'tir.",
    ),
)


def find_wrong_claims(verdict: str) -> list[str]:
    """Modelin bilinen yanlis iddialarini yakala.

    find_invented_numbers sayilari denetler; bu da anlam duzeyinde
    kanitlanmis hata kaliplarini denetler.
    """
    return [aciklama for pattern, aciklama in WRONG_CLAIM_PATTERNS if pattern.search(verdict)]


def build_prompt(analysis_dict: dict) -> str:
    """Analiz sozlugunu kompakt bir prompt'a cevir."""
    lines = [
        "Log ozeti (JSON):",
        "```json",
        json.dumps(analysis_dict, indent=2, ensure_ascii=False),
        "```",
        "",
        "Bu ozeti yukaridaki 3 bolumlu formatta degerlendir.",
    ]
    return "\n".join(lines)
