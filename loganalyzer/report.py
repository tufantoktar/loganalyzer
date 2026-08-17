"""Analiz sonucunu markdown / json rapora cevirir."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .parser import Analysis


def _bar(count: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return ""
    filled = max(1, round(count / total * width)) if count else 0
    return "#" * filled


def to_markdown(
    analysis: Analysis,
    llm_verdict: str | None = None,
    source: str = "-",
    model: str | None = None,
) -> str:
    a = analysis
    total = a.total_lines or 1
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    out: list[str] = [
        "# Log Analiz Raporu",
        "",
        f"- **Kaynak:** `{source}`",
        f"- **Uretim zamani:** {generated}",
        f"- **Satir sayisi:** {a.total_lines} (parse edilen: {a.parsed_lines})",
        f"- **Zaman araligi:** {a.first_timestamp or '-'} -> {a.last_timestamp or '-'}",
        f"- **Hata orani:** {a.error_rate:.2%}",
    ]
    if a.busiest_minute:
        out.append(f"- **En yogun hata dakikasi:** {a.busiest_minute}")
    out += ["", "## Seviye Dagilimi", "", "| Seviye | Adet | % | |", "|---|---:|---:|---|"]
    for level, count in a.level_counts.items():
        out.append(f"| {level} | {count} | {count / total:.1%} | `{_bar(count, total)}` |")

    if a.services:
        out += ["", "## Servisler", "", "| Servis | Satir |", "|---|---:|"]
        for service, count in list(a.services.items())[:15]:
            out.append(f"| {service} | {count} |")

    out += ["", "## En Sik Hata Imzalari", ""]
    if a.top_errors:
        out += ["| # | Adet | Imza |", "|---:|---:|---|"]
        for i, err in enumerate(a.top_errors, 1):
            sig = err["signature"].replace("|", "\\|")
            out.append(f"| {i} | {err['count']} | `{sig}` |")
        out += ["", "<details><summary>Ornek satirlar</summary>", ""]
        for i, err in enumerate(a.top_errors, 1):
            out.append(f"{i}. `{err['example']}`")
        out += ["", "</details>"]
    else:
        out.append("_Hata bulunamadi._")

    out += ["", "## LLM Degerlendirmesi", ""]
    if llm_verdict:
        if model:
            out.append(f"_Model: `{model}` (temperature=0)_")
            out.append("")
        out.append(llm_verdict)
    else:
        out.append("_LLM analizi atlandi (`--no-llm` veya Ollama erisilemedi)._")

    out += ["", "---", "_loganalyzer tarafindan uretildi._", ""]
    return "\n".join(out)


def to_json(
    analysis: Analysis,
    llm_verdict: str | None = None,
    source: str = "-",
    model: str | None = None,
) -> str:
    payload = {
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "analysis": analysis.to_dict(),
        "llm_verdict": llm_verdict,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
