"""Ollama HTTP istemcisi.

Ollama'yi bilerek /api/chat uzerinden, stream kapali kullaniyoruz:
CI icinde deterministik ve tek seferlik bir cikti istiyoruz.
temperature=0 -> ayni ozet ayni yorumu uretsin (buildler karsilastirilabilir olsun).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

SYSTEM_PROMPT = """Sen bir SRE asistanisin. Sana bir log dosyasinin ISTATISTIKSEL OZETI verilecek.
Ham log verilmiyor; sadece sayilar ve hata imzalari var.

Kurallar:
- Sana verilmeyen hicbir sayiyi uydurma. Sadece ozetteki verilere dayan.
- Kesin konusma; "muhtemelen", "isaret ediyor" gibi ifadeler kullan.
- Cevabi tam olarak su 3 bolumde ver:

## Ozet
2-3 cumle. Sistemin genel sagligi.

## Olasi Kok Nedenler
En fazla 3 madde. Her madde: hangi hata imzasina dayandigini belirt.

## Onerilen Aksiyonlar
En fazla 3 madde. Somut, uygulanabilir. Log/metrik/config seviyesinde.
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
