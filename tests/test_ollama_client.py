"""Ollama istemcisi testleri - gercek servise BAGLANMAZ, hepsi mock."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from loganalyzer.ollama_client import (
    OllamaClient,
    OllamaError,
    build_prompt,
    find_invented_numbers,
    find_wrong_claims,
)

# qwen2.5:1.5b'nin gercekte urettigi hatali cikti - regresyon icin sabit tutuluyor
ANALYSIS = {
    "total_lines": 31527,
    "level_counts": {"ERROR": 31527},
    "services": {"recorder:book": 15757},
    "top_errors": [
        {"signature": "CLOB /book failed: HTTP404", "count": 30314},
        {"signature": "CLOB /trades failed: HTTP401", "count": 1200},
    ],
    "error_rate": 1.0,
}


class TestFindInventedNumbers:
    def test_catches_real_hallucination(self):
        # Model 31527'yi 100 ile carpip "3.152.700 defa" yazmisti
        verdict = "Bu hata 3.152.700 defa gerceklesmistir."
        assert find_invented_numbers(verdict, ANALYSIS) == ["3.152.700"]

    def test_accepts_numbers_from_summary(self):
        verdict = "30314 kez HTTP404, 1200 kez HTTP401 gorulmus. Toplam 31527 satir."
        assert find_invented_numbers(verdict, ANALYSIS) == []

    def test_turkish_thousand_separator_accepted(self):
        assert find_invented_numbers("Toplam 31.527 satir var.", ANALYSIS) == []

    def test_small_numbers_ignored(self):
        # madde numarasi, yuzde, durum kodu -- yanlis alarm vermemeli
        verdict = "1. HTTP 404 hatasi %96 oraninda. 2. HTTP 401 hatasi."
        assert find_invented_numbers(verdict, ANALYSIS) == []

    def test_empty_verdict(self):
        assert find_invented_numbers("", ANALYSIS) == []

    def test_multiple_inventions_deduplicated(self):
        verdict = "999999 kez ve yine 999999 kez, ayrica 888888 kez."
        assert find_invented_numbers(verdict, ANALYSIS) == ["888888", "999999"]

    def test_output_is_deterministic(self):
        # set() iterasyonu sizmamali; rapor her calistirmada ayni olmali
        verdict = "777777, 555555, 666666, 12345678 sayilari."
        runs = [find_invented_numbers(verdict, ANALYSIS) for _ in range(5)]
        assert all(r == runs[0] for r in runs)
        assert runs[0] == ["12345678", "555555", "666666", "777777"]


def _response(payload, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


class TestFindWrongClaims:
    def test_catches_4xx_labelled_server_error(self):
        # qwen2.5:3b'nin gercekte urettigi cikti
        verdict = "- `CLOB /book failed: HTTP404` (204 kez): 404 sunucu tarafi hatadir; clob servis istekleri cikmamis olabilir."
        assert find_wrong_claims(verdict)

    def test_5xx_as_server_error_is_correct(self):
        verdict = (
            "- `CLOB /book failed: HTTP502` (5 kez): 502 sunucu tarafinda hata; saglik durumunu kontrol et."
        )
        assert find_wrong_claims(verdict) == []

    def test_correct_404_explanation_passes(self):
        verdict = "404 kaynak bulunamadi; kayit henuz olusmamis olabilir."
        assert find_wrong_claims(verdict) == []

    def test_correct_401_explanation_passes(self):
        verdict = "401 kimlik dogrulama basarisiz; API anahtari eksik veya gecersiz."
        assert find_wrong_claims(verdict) == []

    def test_glossary_line_not_flagged(self):
        assert find_wrong_claims("500, 502, 503, 504 sunucu tarafi hatadir.") == []

    def test_empty_verdict(self):
        assert find_wrong_claims("") == []


class TestChat:
    @patch("loganalyzer.ollama_client.requests.post")
    def test_returns_content(self, post):
        post.return_value = _response({"message": {"content": "## Ozet\nHersey yolunda."}})
        assert OllamaClient().chat("selam").startswith("## Ozet")

    @patch("loganalyzer.ollama_client.requests.post")
    def test_deterministic_options_sent(self, post):
        post.return_value = _response({"message": {"content": "ok"}})
        OllamaClient(model="llama3.2:3b").chat("selam")
        payload = post.call_args.kwargs["json"]
        assert payload["options"]["temperature"] == 0
        assert payload["stream"] is False
        assert payload["model"] == "llama3.2:3b"
        assert payload["messages"][0]["role"] == "system"

    @patch("loganalyzer.ollama_client.requests.post")
    def test_fewshot_example_included(self, post):
        post.return_value = _response({"message": {"content": "ok"}})
        OllamaClient().chat("gercek ozet")
        roles = [m["role"] for m in post.call_args.kwargs["json"]["messages"]]
        # system -> ornek soru -> ornek cevap -> gercek soru
        assert roles == ["system", "user", "assistant", "user"]

    @patch("loganalyzer.ollama_client.requests.post")
    def test_fewshot_numbers_absent_from_real_data(self, post):
        # Ornek sayilar gercek veride bulunmamali; model ornegi kopyalarsa
        # find_invented_numbers yakalasin diye bilerek boyle secildi.
        from loganalyzer.ollama_client import FEWSHOT_ASSISTANT

        assert find_invented_numbers(FEWSHOT_ASSISTANT, ANALYSIS)

    @patch("loganalyzer.ollama_client.requests.post")
    def test_empty_response_raises(self, post):
        post.return_value = _response({"message": {"content": "   "}})
        with pytest.raises(OllamaError, match="bos cevap"):
            OllamaClient().chat("selam")


class TestRetry:
    @patch("loganalyzer.ollama_client.time.sleep")
    @patch("loganalyzer.ollama_client.requests.post")
    def test_retries_then_succeeds(self, post, sleep):
        post.side_effect = [
            requests.ConnectionError("down"),
            _response({"message": {"content": "ok"}}),
        ]
        assert OllamaClient(retries=3).chat("x") == "ok"
        assert post.call_count == 2

    @patch("loganalyzer.ollama_client.time.sleep")
    @patch("loganalyzer.ollama_client.requests.post")
    def test_gives_up_after_max_retries(self, post, sleep):
        post.side_effect = requests.ConnectionError("down")
        with pytest.raises(OllamaError, match="3 denemede"):
            OllamaClient(retries=3).chat("x")
        assert post.call_count == 3

    @patch("loganalyzer.ollama_client.time.sleep")
    @patch("loganalyzer.ollama_client.requests.post")
    def test_exponential_backoff(self, post, sleep):
        post.side_effect = requests.ConnectionError("down")
        with pytest.raises(OllamaError):
            OllamaClient(retries=3).chat("x")
        assert [c.args[0] for c in sleep.call_args_list] == [1, 2]


class TestHealth:
    @patch("loganalyzer.ollama_client.requests.get")
    def test_healthy(self, get):
        get.return_value = _response({"models": []})
        assert OllamaClient().health() is True

    @patch("loganalyzer.ollama_client.requests.get")
    def test_unreachable_returns_false_not_raise(self, get):
        get.side_effect = requests.ConnectionError("no route")
        assert OllamaClient().health() is False

    @patch("loganalyzer.ollama_client.requests.get")
    def test_available_models(self, get):
        get.return_value = _response({"models": [{"name": "llama3.2:3b"}, {"name": "qwen2.5:7b"}]})
        assert OllamaClient().available_models() == ["llama3.2:3b", "qwen2.5:7b"]


class TestEnsureModel:
    @patch("loganalyzer.ollama_client.requests.post")
    @patch("loganalyzer.ollama_client.requests.get")
    def test_skips_pull_when_present(self, get, post):
        get.return_value = _response({"models": [{"name": "llama3.2:3b"}]})
        OllamaClient(model="llama3.2:3b").ensure_model()
        post.assert_not_called()

    @patch("loganalyzer.ollama_client.requests.post")
    @patch("loganalyzer.ollama_client.requests.get")
    def test_pulls_when_missing(self, get, post):
        get.return_value = _response({"models": [{"name": "qwen2.5:7b"}]})
        post.return_value = _response({"status": "success"})
        OllamaClient(model="llama3.2:3b").ensure_model()
        assert post.call_args.kwargs["json"]["model"] == "llama3.2:3b"


class TestBuildPrompt:
    def test_contains_valid_json(self):
        prompt = build_prompt({"total_lines": 10, "error_rate": 0.2})
        body = prompt.split("```json")[1].split("```")[0]
        assert json.loads(body)["total_lines"] == 10

    def test_host_trailing_slash_normalized(self):
        with patch("loganalyzer.ollama_client.requests.post") as post:
            post.return_value = _response({"message": {"content": "ok"}})
            OllamaClient(host="http://ollama:11434/").chat("x")
            assert post.call_args.args[0] == "http://ollama:11434/api/chat"
