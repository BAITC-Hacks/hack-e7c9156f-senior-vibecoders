"""CLI: python -m ai.cli --before samples/before/*.docx --after samples/after/*.docx --out result.json"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from collections import Counter
from pathlib import Path

from .pipeline import run_analysis


def _expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:  # PowerShell не раскрывает маски — делаем сами
        out += [Path(x) for x in sorted(glob.glob(p))] or [Path(p)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="ИИ-агент анализа организационной структуры")
    ap.add_argument("--before", nargs="+", required=True, help="документы до реорганизации (.docx/.pdf/.xlsx)")
    ap.add_argument("--after", nargs="+", required=True, help="документы после реорганизации")
    ap.add_argument("--out", default="result.json")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    result = run_analysis(_expand(args.before), _expand(args.after),
                          on_progress=lambda s, p: print(f"[{p:4.0%}] {s}", flush=True))
    Path(args.out).write_text(result.model_dump_json(indent=2), encoding="utf-8")

    ev = [e for f in result.findings for e in f.evidence]
    print(f"\nГотово за {result.meta.duration_s} с → {args.out}")
    print(f"Единиц: {len(result.units)}, изменений: {dict(Counter(c.status for c in result.unit_changes))}")
    print(f"Выводы: {dict(Counter(f.type for f in result.findings))}, отклонено критиком: {len(result.rejected_findings)}")
    print(f"Проверенных ссылок: {sum(e.verified for e in ev)}/{len(ev)}")


if __name__ == "__main__":
    main()
