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

HTTP DURUM KODLARI (yorumlarken bunlari kullan):
- 401 = kimlik dogrulama basarisiz; API anahtari eksik veya gecersiz
- 403 = kimlik dogru ama yetki yok
- 404 = istenen kaynak yok; yanlis kimlik veya henuz olusmamis kayit
- 429 = hiz siniri asildi; istek sikligi fazla
- 5xx = sunucu tarafinda hata; istemci kodu suclu degil

CIKTI FORMATI (tam olarak bu 3 bolum, baska hicbir sey yazma):

## Ozet
En fazla 3 cumle. En buyuk hata imzasi hangisi ve toplam kac kez gorulmus.

## Olasi Kok Nedenler
En fazla 3 madde. Her madde SU KALIBI kullansin:
- `<imza>` (<adet> kez): <durum koduna gore ne anlama geldigi>

## Onerilen Aksiyonlar
En fazla 3 madde. Her madde bir EYLEM fiiliyle bassin:
Kontrol et / Ekle / Dusur / Sinirla / Kaldir / Ayir
"""


class OllamaError(RuntimeError):
    pass


@dataclass
class OllamaClient:
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    timeout: int = 120
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
