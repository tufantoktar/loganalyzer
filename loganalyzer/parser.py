"""Log satirlarini parse edip deterministik istatistik cikaran modul.

Tasarim notu: LLM'e ham log GONDERMIYORUZ. Once burada deterministik
bir ozet cikariyoruz (seviye dagilimi, imza gruplari, hata orani),
LLM sadece bu ozeti yorumluyor. Sebep:
  - token maliyeti ve context limiti
  - LLM'in sayi saymadaki guvenilmezligi
  - PII/secret sizintisini redact katmaninda kesebilmek
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime

LEVELS = ("TRACE", "DEBUG", "INFO", "NOTICE", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL")

# Desteklenen bicimler:
#   2026-08-17 10:32:11,123 ERROR [payment-svc] Connection refused
#   2026-08-17T10:32:11Z ERROR payment-svc - Connection refused
#   [2026-08-17T12:03:34.830Z] [INFO] Recorder tokens refreshed   <- PM2/node
PLAIN_RE = re.compile(
    # Zaman damgasi parantezli de olabilir: [2026-...] veya 2026-...
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)\]?"
    r"\s+\[?(?P<level>" + "|".join(LEVELS) + r")\]?"
    # Servis adi: ya [koseli parantez] icinde, ya da ardindan ayirici (- veya :)
    # gelen tek kelime. Ayirici sarti onemli: "[INFO] Recorder tokens refreshed"
    # satirinda "Recorder" mesajin ilk kelimesidir, servis adi degil.
    r"\s+(?:\[(?P<service>[^\]]+)\]|(?P<service2>[\w.\-]+)(?=\s*[-:]\s))?"
    r"\s*[-:]?\s*(?P<message>.*)$",
    re.IGNORECASE,
)

# Mesaj imzasi cikarirken degisken kisimlari maskeler.
NOISE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\S*"), "<ts>"),
    # Cok segmentli dosya yollari maskelenir (/root/app/src/x.js), tek segmentli
    # API endpoint'leri korunur (/book, /trades) -- onlar hatayi ayirt ediyor.
    (re.compile(r"(?:/[\w.\-]+){2,}"), "<path>"),
    # HTTP durum kodunu koru: 401 (yetki) ile 404 (bulunamadi) ayri sorunlardir,
    # ayni imzada birlesmemeli. 'HTTP401' yazip sonraki sayi kuralindan kacir.
    (re.compile(r"(?i)\b(failed|status|code|error|returned)\b(\s*[:=]?\s*)(\d{3})\b"), r"\1\2HTTP\3"),
    (re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|kb|mb|gb)?\b", re.I), "<n>"),
)

# Rapora/LLM'e gitmeden once maskelenecek hassas veriler.
SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(authorization|bearer|token|api[_-]?key|password|passwd|secret)\b\s*[=:]\s*\S+"),
        r"\1=***REDACTED***",
    ),
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}\b"), "***JWT***"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "***EMAIL***"),
)

TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def redact(text: str) -> str:
    """Hassas verileri maskele. LLM'e giden her sey buradan gecer."""
    for pattern, repl in SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _parse_ts(raw: str) -> datetime | None:
    cleaned = raw.replace(",", ".").rstrip("Z")
    cleaned = re.sub(r"[+-]\d{2}:?\d{2}$", "", cleaned)
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def signature(message: str, max_len: int = 120) -> str:
    """Degisken kisimlari maskeleyip hata imzasi uret.

    'Timeout after 3021ms for user 42' ve 'Timeout after 88ms for user 7'
    ayni imzaya duser -> gruplanabilir.
    """
    sig = message.strip()
    for pattern, repl in NOISE_PATTERNS:
        sig = pattern.sub(repl, sig)
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig[:max_len]


@dataclass
class LogEntry:
    raw: str
    level: str = "UNKNOWN"
    message: str = ""
    service: str | None = None
    timestamp: datetime | None = None

    @property
    def is_problem(self) -> bool:
        return self.level in ("ERROR", "FATAL", "CRITICAL")


def parse_line(line: str) -> LogEntry | None:
    """Tek satiri parse et. JSON satirlari da destekli. Bos satir -> None."""
    line = line.rstrip("\n")
    if not line.strip():
        return None

    stripped = line.lstrip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            level = str(obj.get("level") or obj.get("severity") or "UNKNOWN").upper()
            ts_raw = obj.get("timestamp") or obj.get("time") or obj.get("ts") or ""
            service = (
                obj.get("service")
                or obj.get("logger")
                or obj.get("component")
                or obj.get("module")
                or obj.get("name")
            )
            # Bazi uygulamalar 'message' alanini hata metni, 'msg' alanini
            # operasyon etiketi olarak kullanir (ornek: msg="recorder:book",
            # message="CLOB /book failed: 404"). Ikisi de varsa 'msg' servistir.
            if service is None and obj.get("message") and obj.get("msg"):
                service = str(obj["msg"])
            return LogEntry(
                raw=line,
                level="WARN" if level == "WARNING" else level,
                message=str(obj.get("message") or obj.get("msg") or ""),
                service=service,
                timestamp=_parse_ts(str(ts_raw)) if ts_raw else None,
            )

    match = PLAIN_RE.match(line)
    if not match:
        # Stack trace devami gibi eslesmeyen satirlar: kaybetme, UNKNOWN yaz.
        return LogEntry(raw=line, message=line.strip())

    groups = match.groupdict()
    level = (groups["level"] or "UNKNOWN").upper()
    return LogEntry(
        raw=line,
        level="WARN" if level == "WARNING" else level,
        message=(groups["message"] or "").strip(),
        service=groups["service"] or groups["service2"],
        timestamp=_parse_ts(groups["ts"]) if groups["ts"] else None,
    )


def parse_lines(lines: Iterable[str]) -> Iterator[LogEntry]:
    for line in lines:
        entry = parse_line(line)
        if entry is not None:
            yield entry


@dataclass
class Analysis:
    total_lines: int = 0
    parsed_lines: int = 0
    level_counts: dict[str, int] = field(default_factory=dict)
    services: dict[str, int] = field(default_factory=dict)
    top_errors: list[dict] = field(default_factory=list)
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    error_rate: float = 0.0
    busiest_minute: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(entries: Iterable[LogEntry], top_n: int = 10) -> Analysis:
    """Deterministik analiz. Sayilar buradan cikar, LLM'den degil."""
    levels: Counter[str] = Counter()
    services: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    per_minute: Counter[str] = Counter()
    examples: dict[str, str] = {}

    total = 0
    parsed = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    for entry in entries:
        total += 1
        if entry.level != "UNKNOWN":
            parsed += 1
        levels[entry.level] += 1
        if entry.service:
            services[entry.service] += 1
        if entry.timestamp:
            first_ts = entry.timestamp if first_ts is None else min(first_ts, entry.timestamp)
            last_ts = entry.timestamp if last_ts is None else max(last_ts, entry.timestamp)
            if entry.is_problem:
                per_minute[entry.timestamp.strftime("%Y-%m-%d %H:%M")] += 1
        if entry.is_problem and entry.message:
            sig = signature(entry.message)
            signatures[sig] += 1
            examples.setdefault(sig, entry.message.strip())

    problem_count = sum(levels[lvl] for lvl in ("ERROR", "FATAL", "CRITICAL"))

    return Analysis(
        total_lines=total,
        parsed_lines=parsed,
        level_counts=dict(levels.most_common()),
        services=dict(services.most_common()),
        top_errors=[
            {"signature": redact(sig), "count": cnt, "example": redact(examples.get(sig, "")[:300])}
            for sig, cnt in signatures.most_common(top_n)
        ],
        first_timestamp=first_ts.isoformat() if first_ts else None,
        last_timestamp=last_ts.isoformat() if last_ts else None,
        error_rate=round(problem_count / total, 4) if total else 0.0,
        busiest_minute=per_minute.most_common(1)[0][0] if per_minute else None,
    )
