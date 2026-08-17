"""Ollama istemcisi testleri - gercek servise BAGLANMAZ, hepsi mock."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from loganalyzer.ollama_client import OllamaClient, OllamaError, build_prompt


def _response(payload, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


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
