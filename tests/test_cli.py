import json
from unittest.mock import patch

import pytest

from loganalyzer.cli import EXIT_ERROR, EXIT_OK, EXIT_THRESHOLD, main

LOG = """\
2026-08-17 10:00:00 INFO [gw] Request handled in 12ms
2026-08-17 10:00:01 INFO [gw] Request handled in 15ms
2026-08-17 10:00:02 WARN [db] Pool at 85%
2026-08-17 10:00:03 ERROR [db] Timeout after 3021ms
"""


@pytest.fixture
def logfile(tmp_path):
    path = tmp_path / "app.log"
    path.write_text(LOG, encoding="utf-8")
    return path


def test_missing_path_returns_error(tmp_path):
    assert main([str(tmp_path / "yok.log"), "--no-llm"]) == EXIT_ERROR


def test_markdown_report_written(logfile, tmp_path):
    out = tmp_path / "r.md"
    assert main([str(logfile), "--no-llm", "-o", str(out)]) == EXIT_OK
    text = out.read_text()
    assert "# Log Analiz Raporu" in text
    assert "LLM analizi atlandi" in text


def test_json_report_shape(logfile, tmp_path):
    out = tmp_path / "r.json"
    main([str(logfile), "--no-llm", "-f", "json", "-o", str(out)])
    data = json.loads(out.read_text())
    assert data["analysis"]["total_lines"] == 4
    assert data["analysis"]["level_counts"]["INFO"] == 2
    assert data["llm_verdict"] is None


def test_directory_scan(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.log").write_text(LOG)
    (tmp_path / "sub" / "b.log").write_text(LOG)
    (tmp_path / "ignore.txt").write_text(LOG)
    out = tmp_path / "r.json"
    main([str(tmp_path), "--no-llm", "-f", "json", "-o", str(out)])
    # sadece *.log -> 2 dosya x 4 satir
    assert json.loads(out.read_text())["analysis"]["total_lines"] == 8


def test_fail_over_threshold_breached(logfile, tmp_path):
    # 1/4 = 0.25 > 0.10
    code = main([str(logfile), "--no-llm", "--fail-over", "0.10", "-o", str(tmp_path / "r.md")])
    assert code == EXIT_THRESHOLD


def test_fail_over_threshold_ok(logfile, tmp_path):
    code = main([str(logfile), "--no-llm", "--fail-over", "0.90", "-o", str(tmp_path / "r.md")])
    assert code == EXIT_OK


def test_report_written_even_when_threshold_fails(logfile, tmp_path):
    out = tmp_path / "r.md"
    main([str(logfile), "--no-llm", "--fail-over", "0.01", "-o", str(out)])
    assert out.exists(), "esik asilsa bile rapor yazilmali"


@patch("loganalyzer.cli.OllamaClient")
def test_llm_verdict_included(mock_cls, logfile, tmp_path):
    client = mock_cls.return_value
    client.health.return_value = True
    client.model = "llama3.2:3b"
    client.chat.return_value = "## Ozet\nDB baglanti sorunu var."
    out = tmp_path / "r.md"
    assert main([str(logfile), "-o", str(out)]) == EXIT_OK
    assert "DB baglanti sorunu var." in out.read_text()


@patch("loganalyzer.cli.OllamaClient")
def test_unhealthy_ollama_degrades_gracefully(mock_cls, logfile, tmp_path):
    mock_cls.return_value.health.return_value = False
    out = tmp_path / "r.md"
    # Ollama yoksa bile rapor uretilmeli, exit 0 olmali.
    assert main([str(logfile), "-o", str(out)]) == EXIT_OK
    assert "LLM analizi atlandi" in out.read_text()


@patch("loganalyzer.cli.OllamaClient")
def test_llm_error_degrades_gracefully(mock_cls, logfile, tmp_path):
    from loganalyzer.ollama_client import OllamaError

    client = mock_cls.return_value
    client.health.return_value = True
    client.chat.side_effect = OllamaError("patladi")
    out = tmp_path / "r.md"
    assert main([str(logfile), "-o", str(out)]) == EXIT_OK
    assert "LLM analizi atlandi" in out.read_text()


def test_stdout_when_no_out_flag(logfile, capsys):
    main([str(logfile), "--no-llm"])
    assert "# Log Analiz Raporu" in capsys.readouterr().out
