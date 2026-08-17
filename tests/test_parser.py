from datetime import datetime

import pytest

from loganalyzer.parser import (
    LogEntry,
    analyze,
    parse_line,
    parse_lines,
    redact,
    signature,
)


class TestParseLine:
    def test_plain_bracketed_service(self):
        entry = parse_line("2026-08-17 10:32:11 ERROR [payment-svc] Connection refused")
        assert entry.level == "ERROR"
        assert entry.service == "payment-svc"
        assert entry.message == "Connection refused"
        assert entry.timestamp == datetime(2026, 8, 17, 10, 32, 11)
        assert entry.is_problem

    def test_iso_timestamp_with_millis(self):
        entry = parse_line("2026-08-17T10:32:11,123 WARN auth-svc - Slow query")
        assert entry.level == "WARN"
        assert entry.service == "auth-svc"
        assert entry.timestamp == datetime(2026, 8, 17, 10, 32, 11, 123000)
        assert not entry.is_problem

    def test_bracketed_timestamp_and_level(self):
        # PM2/node bicimi: [2026-...Z] [INFO] mesaj
        entry = parse_line('[2026-08-17T12:03:34.830Z] [INFO] Recorder tokens refreshed {"count":30}')
        assert entry.level == "INFO"
        assert entry.timestamp == datetime(2026, 8, 17, 12, 3, 34, 830000)
        # "Recorder" mesajin ilk kelimesi, servis adi degil
        assert entry.service is None
        assert entry.message.startswith("Recorder tokens refreshed")

    def test_bare_word_service_needs_separator(self):
        with_sep = parse_line("2026-08-17 10:00:00 ERROR api-gw - boom")
        without_sep = parse_line("2026-08-17 10:00:00 ERROR Something bad happened")
        assert with_sep.service == "api-gw"
        assert without_sep.service is None
        assert without_sep.message == "Something bad happened"

    def test_warning_normalized_to_warn(self):
        assert parse_line("2026-08-17 10:00:00 WARNING [x] y").level == "WARN"

    def test_json_line(self):
        entry = parse_line(
            '{"timestamp":"2026-08-17T10:32:11","level":"error","service":"order-svc","message":"boom"}'
        )
        assert entry.level == "ERROR"
        assert entry.service == "order-svc"
        assert entry.message == "boom"
        assert entry.is_problem

    def test_json_msg_used_as_service_label(self):
        # polymarket-engine formati: message=hata metni, msg=operasyon etiketi
        entry = parse_line(
            '{"ts":"2026-08-17T04:48:16.219Z","level":"error","msg":"recorder:book",'
            '"message":"CLOB /book failed: 404","status":404}'
        )
        assert entry.level == "ERROR"
        assert entry.service == "recorder:book"
        assert entry.message == "CLOB /book failed: 404"
        assert entry.timestamp == datetime(2026, 8, 17, 4, 48, 16, 219000)

    def test_json_msg_alone_is_the_message(self):
        # 'message' yoksa 'msg' hata metnidir, servis olarak kullanilmamali
        entry = parse_line('{"level":"error","msg":"something broke"}')
        assert entry.message == "something broke"
        assert entry.service is None

    def test_malformed_json_falls_back(self):
        entry = parse_line('{"level": broken')
        assert entry is not None
        assert entry.level == "UNKNOWN"

    def test_unmatched_line_is_kept_as_unknown(self):
        entry = parse_line("    at com.acme.Foo.bar(Foo.java:42)")
        assert entry.level == "UNKNOWN"
        assert "com.acme.Foo.bar" in entry.message

    @pytest.mark.parametrize("line", ["", "   ", "\n"])
    def test_blank_lines_dropped(self, line):
        assert parse_line(line) is None

    def test_parse_lines_skips_blanks(self):
        entries = list(parse_lines(["2026-08-17 10:00:00 INFO [a] ok", "", "  "]))
        assert len(entries) == 1


class TestSignature:
    def test_variable_parts_collapse(self):
        a = signature("Timeout after 3021ms waiting for user 42")
        b = signature("Timeout after 88ms waiting for user 7")
        assert a == b

    def test_ip_and_uuid_masked(self):
        sig = signature("Connection refused to 10.0.3.12:5432 for 3f2a1b4c-1111-2222-3333-444455556666")
        assert "<ip>" in sig
        assert "<uuid>" in sig

    def test_truncated(self):
        assert len(signature("x" * 500)) <= 120

    def test_distinct_errors_stay_distinct(self):
        assert signature("Connection refused") != signature("Permission denied")

    def test_http_status_codes_not_merged(self):
        # 401 (yetki) ile 404 (bulunamadi) farkli sorunlar, ayni imzaya dusmemeli
        assert signature("CLOB /book failed: 401") != signature("CLOB /book failed: 404")

    def test_api_endpoint_preserved(self):
        # /book ve /trades hatayi ayirt eder, maskelenmemeli
        sig = signature("CLOB /trades failed: 401")
        assert "/trades" in sig
        assert "401" in sig

    def test_filesystem_path_still_masked(self):
        sig = signature("Cannot read /root/polymarket-engine/src/live/client.js")
        assert "<path>" in sig
        assert "polymarket-engine" not in sig


class TestRedact:
    def test_password_masked(self):
        assert "hunter2" not in redact("login failed password=hunter2")

    def test_jwt_masked(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        assert token not in redact(f"Authorization header {token}")

    def test_email_masked(self):
        assert "utku@example.com" not in redact("user utku@example.com failed")

    def test_clean_text_untouched(self):
        assert redact("Connection refused") == "Connection refused"


class TestAnalyze:
    @pytest.fixture
    def sample(self):
        return [
            "2026-08-17 10:00:00 INFO [gw] Request handled in 12ms",
            "2026-08-17 10:00:01 INFO [gw] Request handled in 15ms",
            "2026-08-17 10:00:02 WARN [db] Pool at 85%",
            "2026-08-17 10:00:03 ERROR [db] Timeout after 3021ms for order 12",
            "2026-08-17 10:00:04 ERROR [db] Timeout after 90ms for order 99",
            "2026-08-17 10:05:00 FATAL [gw] Unrecoverable state",
        ]

    def test_counts(self, sample):
        result = analyze(parse_lines(sample))
        assert result.total_lines == 6
        assert result.level_counts["INFO"] == 2
        assert result.level_counts["ERROR"] == 2
        assert result.level_counts["FATAL"] == 1

    def test_error_rate_includes_fatal(self, sample):
        # 2 ERROR + 1 FATAL = 3 / 6
        assert analyze(parse_lines(sample)).error_rate == 0.5

    def test_similar_errors_grouped(self, sample):
        top = analyze(parse_lines(sample)).top_errors
        assert top[0]["count"] == 2
        assert "<n>" in top[0]["signature"]

    def test_time_range(self, sample):
        result = analyze(parse_lines(sample))
        assert result.first_timestamp.startswith("2026-08-17T10:00:00")
        assert result.last_timestamp.startswith("2026-08-17T10:05:00")

    def test_busiest_minute(self, sample):
        assert analyze(parse_lines(sample)).busiest_minute == "2026-08-17 10:00"

    def test_services_counted(self, sample):
        assert analyze(parse_lines(sample)).services["db"] == 3

    def test_empty_input(self):
        result = analyze([])
        assert result.total_lines == 0
        assert result.error_rate == 0.0
        assert result.top_errors == []

    def test_top_n_respected(self):
        entries = [
            LogEntry(raw="", level="ERROR", message=f"unique failure kind {chr(97 + i)}") for i in range(20)
        ]
        assert len(analyze(entries, top_n=5).top_errors) == 5

    def test_secrets_not_leaked_into_report(self):
        entries = parse_lines(["2026-08-17 10:00:00 ERROR [auth] login failed password=hunter2"])
        result = analyze(entries)
        assert "hunter2" not in str(result.to_dict())

    def test_to_dict_is_json_ready(self, sample):
        import json

        json.dumps(analyze(parse_lines(sample)).to_dict())
