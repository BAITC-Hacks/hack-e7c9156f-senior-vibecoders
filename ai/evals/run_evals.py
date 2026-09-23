"""Offline evaluation of a saved AnalysisResult; never runs the agent."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.schemas import AnalysisResult


DEFAULT_GOLDEN = Path(__file__).with_name("golden_r8_r9.json")
GROUP_NAMES = {"unit_changes": "Изменения подразделений", "alignments": "Выравнивания", "findings": "Выводы"}


def evaluate(result: AnalysisResult, golden: dict) -> dict:
    """Match golden facts and count stored verification flags, without rechecking quotes.

    Evidence metrics include findings' own evidence and critic counter-evidence;
    rejected findings and their references are excluded from those metrics.
    """
    units = {u.id: u for u in result.units}

    def unit_change_matches(fact):
        sides = [(side, fact[f"{side}_abbr"]) for side in ("before", "after")
                 if f"{side}_abbr" in fact]
        if not sides:
            return False
        allowed = {fact["status"]}
        if fact["status"] == "created" and "after_abbr" in fact:
            allowed.update({"split", "transformed", "merged"})
        return any(
            change.status in allowed and all(
                any(uid in units and units[uid].side == side and units[uid].abbr == abbr
                    for uid in getattr(change, f"{side}_unit_ids"))
                for side, abbr in sides
            ) for change in result.unit_changes
        )

    triples = {(a.before_clause_id, a.after_clause_id, a.status) for a in result.alignments}

    def finding_matches(fact):
        return any(
            finding.type == fact["type"]
            and set(fact["unit_abbrs"]) <= {units[uid].abbr for uid in finding.unit_ids if uid in units}
            and any(ev.clause_id == cid or ev.clause_id.startswith(cid + ".")
                    for ev in finding.evidence for cid in fact["evidence_clause_ids"])
            for finding in result.findings
        )

    matchers = {
        "unit_changes": unit_change_matches,
        "alignments": lambda fact: (fact.get("before_clause_id"), fact.get("after_clause_id"), fact["status"]) in triples,
        "findings": finding_matches,
    }
    groups = {}
    for name, matches in matchers.items():
        facts = golden.get(name, [])
        failed = [fact for fact in facts if not matches(fact)]
        groups[name] = dict(passed=len(facts) - len(failed), total=len(facts), failed=failed)
    evidence = [ev for f in result.findings
                for ev in f.evidence + (f.critic.counter_evidence if f.critic else [])]
    verified = sum(ev.verified for ev in evidence)
    return dict(
        groups=groups,
        passed=sum(g["passed"] for g in groups.values()),
        total=sum(g["total"] for g in groups.values()),
        evidence=dict(verified=verified, total=len(evidence), ratio=verified / len(evidence) if evidence else None),
        rejected_findings=len(result.rejected_findings),
        finding_types=dict(sorted(Counter(f.type for f in result.findings).items())),
    )


def print_report(metrics: dict) -> None:
    print(f"{'Группа':<28} {'Пройдено':>8} {'Всего':>6}")
    print("-" * 44)
    for name, group in metrics["groups"].items():
        print(f"{GROUP_NAMES[name]:<28} {group['passed']:>8} {group['total']:>6}")
    print(f"{'Итого golden-фактов':<28} {metrics['passed']:>8} {metrics['total']:>6}")
    ev = metrics["evidence"]
    fraction = f"{ev['ratio']:.1%}" if ev["ratio"] is not None else "нет ссылок"
    print(f"Проверенные ссылки в findings (включая контр-цитаты): {ev['verified']}/{ev['total']} ({fraction})")
    print(f"Отклонено выводов: {metrics['rejected_findings']}")
    print("Типы findings: " + (", ".join(f"{k}: {v}" for k, v in metrics["finding_types"].items()) or "нет"))
    for name, group in metrics["groups"].items():
        for fact in group["failed"]:
            print(f"НЕ ПРОЙДЕНО — {GROUP_NAMES[name]}: {json.dumps(fact, ensure_ascii=False)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Офлайн-проверка результата по golden-фактам")
    parser.add_argument("result", type=Path, help="Сохранённый result.json")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--strict", action="store_true", help="Код выхода 1 при непройденных golden-фактах")
    args = parser.parse_args(argv)
    try:
        result = AnalysisResult.model_validate_json(args.result.read_text(encoding="utf-8-sig"))
        golden = json.loads(args.golden.read_text(encoding="utf-8-sig"))
        metrics = evaluate(result, golden)
    except (OSError, ValueError, ValidationError, KeyError, TypeError, AttributeError) as exc:
        parser.error(f"Не удалось прочитать или проверить входные данные: {exc}")
    print_report(metrics)
    return int(args.strict and metrics["passed"] != metrics["total"])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
