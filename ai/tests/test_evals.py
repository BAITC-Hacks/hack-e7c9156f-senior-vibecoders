import json
from pathlib import Path
import subprocess
import sys

import pytest

from ai.schemas import AnalysisResult, Evidence, Finding, Unit, UnitChange
from evals.run_evals import DEFAULT_GOLDEN, evaluate, main


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def result():
    return AnalysisResult.model_validate_json((ROOT / "mocks/result.json").read_text(encoding="utf-8"))


def test_mock_passes_all_golden(result):
    metrics = evaluate(result, json.loads(DEFAULT_GOLDEN.read_text(encoding="utf-8")))
    assert metrics["passed"] == metrics["total"] == 14
    assert metrics["evidence"]["ratio"] == 1
    assert metrics["rejected_findings"] == 1


@pytest.fixture
def synthetic(result):
    return result.model_copy(update={
        "units": [Unit(id="new", name="ИТ-аудит", abbr="ДИТААД", side="after")],
        "unit_changes": [UnitChange(before_unit_ids=[], after_unit_ids=["new"], status="created", rationale="test")],
        "findings": [], "rejected_findings": [], "alignments": [],
    })


UNIT_GOLDEN = {"unit_changes": [{"after_abbr": "ДИТААД", "status": "created"}]}


def test_missing_unit_fails_even_with_dangling_change(synthetic):
    synthetic.units = []
    assert evaluate(synthetic, UNIT_GOLDEN)["passed"] == 0


@pytest.mark.parametrize("status", ["created", "split", "transformed", "merged"])
def test_created_equivalences(synthetic, status):
    synthetic.unit_changes[0].status = status
    assert evaluate(synthetic, UNIT_GOLDEN)["passed"] == 1


def test_preserved_is_not_renamed_and_side_matters(synthetic):
    synthetic.unit_changes[0].status = "renamed"
    assert evaluate(synthetic, {"unit_changes": [{"after_abbr": "ДИТААД", "status": "preserved"}]})["passed"] == 0
    synthetic.unit_changes[0].status = "created"
    synthetic.units[0].side = "before"
    assert evaluate(synthetic, UNIT_GOLDEN)["passed"] == 0
    synthetic.unit_changes[0].before_unit_ids = ["new"]
    synthetic.unit_changes[0].after_unit_ids = []
    synthetic.unit_changes[0].status = "abolished"
    assert evaluate(synthetic, {"unit_changes": [{"before_abbr": "ДИТААД", "status": "abolished"}]})["passed"] == 1


def evidence(cid="3.4.а", verified=True):
    return Evidence(doc_id="a1", doc_name="test", side="after", clause_id=cid, quote="цитата", verified=verified)


FINDING_GOLDEN = {"findings": [{"type": "structure_change", "unit_abbrs": ["ДИТААД"], "evidence_clause_ids": ["3.4"]}]}


@pytest.mark.parametrize(("cid", "passed"), [("3.4", 1), ("3.4.а", 1), ("3.40", 0), ("3", 0)])
def test_finding_clause_boundary(synthetic, cid, passed):
    synthetic.findings = [Finding(id="f", type="structure_change", severity="low", title="test", description="test",
                                 unit_ids=["new"], evidence=[evidence(cid)])]
    assert evaluate(synthetic, FINDING_GOLDEN)["passed"] == passed
    synthetic.rejected_findings = synthetic.findings
    synthetic.findings = []
    assert evaluate(synthetic, FINDING_GOLDEN)["passed"] == 0


def test_findings_require_all_units_and_own_evidence(synthetic):
    synthetic.findings = [Finding(id="f", type="structure_change", severity="low", title="test", description="test",
                                 unit_ids=["new"], evidence=[evidence()], critic=dict(
                                     verdict="uncertain", argument="test", counter_evidence=[evidence(verified=False)]))]
    golden = {"findings": [dict(FINDING_GOLDEN["findings"][0], unit_abbrs=["ДИТААД", "ДОА"])]}
    metrics = evaluate(synthetic, golden)
    assert metrics["passed"] == 0
    assert metrics["evidence"] == dict(verified=1, total=2, ratio=.5)
    assert metrics["finding_types"] == {"structure_change": 1}
    synthetic.findings[0].evidence = []
    assert evaluate(synthetic, FINDING_GOLDEN)["passed"] == 0
    synthetic.findings = []
    assert evaluate(synthetic, {})["evidence"]["ratio"] is None


def test_alignment_requires_status_and_both_ids(result):
    assert evaluate(result, {"alignments": [{"before_clause_id": "3.8", "after_clause_id": "3.9", "status": "moved"}]})["passed"] == 1
    for changed in ({"status": "unchanged"}, {"before_clause_id": None}, {"after_clause_id": "3.8"}):
        fact = dict(before_clause_id="3.8", after_clause_id="3.9", status="moved")
        fact.update(changed)
        assert evaluate(result, {"alignments": [fact]})["passed"] == 0


def test_cli_strict_exit_and_custom_golden(tmp_path, capsys):
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"unit_changes": [{"after_abbr": "MISSING", "status": "created"}]}), encoding="utf-8")
    args = [str(ROOT / "mocks/result.json"), "--golden", str(golden)]
    assert main(args) == 0
    assert main(args + ["--strict"]) == 1
    assert "НЕ ПРОЙДЕНО" in capsys.readouterr().out
    # Exercise the actual executable from a different cwd, including SystemExit.
    process = subprocess.run([sys.executable, str(ROOT / "ai/evals/run_evals.py"), *args, "--strict"],
                             cwd=tmp_path, capture_output=True)
    assert process.returncode == 1
    assert "НЕ ПРОЙДЕНО" in process.stdout.decode("utf-8")
    assert main([str(ROOT / "mocks/result.json"), "--strict"]) == 0


def test_invalid_result_is_an_input_error(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main([str(invalid)])
    assert error.value.code == 2
