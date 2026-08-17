"""loganalyzer CLI.

Exit kodlari (CI icin onemli):
  0 -> temiz
  1 -> calisma hatasi (dosya yok, Ollama patladi vs.)
  2 -> hata orani esigi asildi  (pipeline'i kirmak icin)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .ollama_client import OllamaClient, OllamaError, build_prompt, find_invented_numbers
from .parser import analyze, parse_lines
from .report import to_json, to_markdown

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_THRESHOLD = 2

log = logging.getLogger("loganalyzer")


def _iter_files(path: Path, pattern: str) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob(pattern) if p.is_file())
    return []


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="loganalyzer",
        description="Log dosyalarini analiz eder ve Ollama ile yorumlar.",
    )
    p.add_argument("path", type=Path, help="Log dosyasi veya klasoru")
    p.add_argument("--pattern", default="*.log", help="Klasor taramasi icin glob (varsayilan: *.log)")
    p.add_argument("-o", "--out", type=Path, help="Rapor cikti dosyasi (yoksa stdout)")
    p.add_argument("-f", "--format", choices=("md", "json"), default="md", help="Rapor formati")
    p.add_argument("--top", type=int, default=10, help="Kac hata imzasi gosterilsin")
    p.add_argument("--no-llm", action="store_true", help="Ollama'yi atla, sadece istatistik")
    p.add_argument("--model", default=None, help="Ollama modeli (env: OLLAMA_MODEL)")
    p.add_argument("--ollama-host", default=None, help="Ollama adresi (env: OLLAMA_HOST)")
    p.add_argument("--pull", action="store_true", help="Model yoksa otomatik pull et")
    p.add_argument(
        "--fail-over",
        type=float,
        default=None,
        metavar="RATE",
        help="Hata orani bu degeri asarsa exit 2 (ornek: 0.05)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"loganalyzer {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    files = _iter_files(args.path, args.pattern)
    if not files:
        log.error("Log dosyasi bulunamadi: %s (pattern=%s)", args.path, args.pattern)
        return EXIT_ERROR

    log.info("%d dosya analiz ediliyor", len(files))

    def line_stream():
        for file in files:
            log.debug("okunuyor: %s", file)
            with file.open("r", encoding="utf-8", errors="replace") as fh:
                yield from fh

    analysis = analyze(parse_lines(line_stream()), top_n=args.top)
    log.info("%d satir, hata orani %.2f%%", analysis.total_lines, analysis.error_rate * 100)

    verdict = None
    model_name = None
    invented: list[str] = []
    if not args.no_llm:
        client = OllamaClient(
            host=args.ollama_host or OllamaClient.host,
            model=args.model or OllamaClient.model,
        )
        model_name = client.model
        if not client.health():
            log.error("Ollama erisilemiyor: %s -- LLM adimi atlaniyor", client.host)
            model_name = None
        else:
            try:
                if args.pull:
                    client.ensure_model()
                verdict = client.chat(build_prompt(analysis.to_dict()))
                invented = find_invented_numbers(verdict, analysis.to_dict())
                if invented:
                    log.warning(
                        "Model ozette olmayan %d sayi uretti: %s -- rapora uyari eklendi",
                        len(invented),
                        ", ".join(invented[:5]),
                    )
            except OllamaError as exc:
                log.error("LLM analizi basarisiz: %s", exc)
                model_name = None

    source = str(args.path) if len(files) == 1 else f"{args.path} ({len(files)} dosya)"
    renderer = to_json if args.format == "json" else to_markdown
    report = renderer(
        analysis,
        llm_verdict=verdict,
        source=source,
        model=model_name,
        invented_numbers=invented,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        log.info("Rapor yazildi: %s", args.out)
    else:
        print(report)

    if args.fail_over is not None and analysis.error_rate > args.fail_over:
        log.error("Hata orani esigi asildi: %.4f > %.4f", analysis.error_rate, args.fail_over)
        return EXIT_THRESHOLD

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
