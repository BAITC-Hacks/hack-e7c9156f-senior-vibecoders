import sys
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.clients.ai import rebuild_conclusion, run_analysis


def fake_ai_modules(**children: ModuleType) -> dict[str, ModuleType]:
    package = ModuleType("ai")
    package.__path__ = []
    return {"ai": package, **{f"ai.{name}": module for name, module in children.items()}}


class AiClientTest(TestCase):
    def test_mock_returns_fixture_and_reports_progress(self) -> None:
        progress = []
        result = run_analysis([], [], lambda step, value: progress.append((step, value)), mock=True)

        self.assertEqual(result["meta"]["provider"], "mock")
        self.assertIn("rejected_findings", result)
        self.assertEqual(progress, [("parsing", 0.2), ("report", 0.95)])

    def test_real_pipeline_serializes_full_ai_model(self) -> None:
        pipeline = ModuleType("ai.pipeline")
        model = MagicMock()
        expected = {"findings": [], "alignments": [{"status": "moved"}], "custom_field": 42}
        model.model_dump.return_value = expected
        pipeline.run_analysis = MagicMock(return_value=model)
        callback = MagicMock()
        before, after = [Path("before.docx")], [Path("after.docx")]

        with patch.dict(sys.modules, fake_ai_modules(pipeline=pipeline)):
            self.assertIs(run_analysis(before, after, callback, mock=False), expected)

        pipeline.run_analysis.assert_called_once_with(before, after, callback)
        model.model_dump.assert_called_once_with(mode="json")

    def test_real_rebuild_passes_ai_schema_to_report(self) -> None:
        report = ModuleType("ai.report")
        schemas = ModuleType("ai.schemas")
        parsed = object()
        schemas.AnalysisResult = MagicMock()
        schemas.AnalysisResult.model_validate.return_value = parsed
        report.rebuild_conclusion = MagicMock(return_value="Обновлённое заключение")
        result = {"findings": [], "rejected_findings": []}

        with patch.dict(sys.modules, fake_ai_modules(report=report, schemas=schemas)):
            self.assertEqual(rebuild_conclusion(result, mock=False), "Обновлённое заключение")

        schemas.AnalysisResult.model_validate.assert_called_once_with(result)
        report.rebuild_conclusion.assert_called_once_with(parsed)

    def test_rebuild_fallback_respects_reviews_critic_and_verified_evidence(self) -> None:
        def finding(title: str, *, reviewed: str | None = None, critic: str | None = None,
                    verified: bool = True) -> dict:
            return {
                "title": title, "description": "Описание", "evidence": [{"verified": verified}],
                "review": {"status": reviewed} if reviewed else None,
                "critic": {"verdict": critic} if critic else None,
            }

        result = {
            "findings": [
                finding("Обычный вывод"), finding("Отклонён человеком", reviewed="rejected"),
                finding("Без подтверждения", reviewed="accepted", verified=False),
            ],
            "rejected_findings": [
                finding("Принят человеком", reviewed="accepted", critic="refuted"),
                finding("Опровергнут критиком", critic="refuted"),
            ],
        }

        text = rebuild_conclusion(result, mock=True)
        self.assertIn("Обычный вывод", text)
        self.assertIn("Принят человеком", text)
        for title in ("Отклонён человеком", "Без подтверждения", "Опровергнут критиком"):
            self.assertNotIn(title, text)

        report = ModuleType("ai.report")
        report.rebuild_conclusion = MagicMock(side_effect=RuntimeError("LLM unavailable"))
        schemas = ModuleType("ai.schemas")
        schemas.AnalysisResult = MagicMock()
        with patch.dict(sys.modules, fake_ai_modules(report=report, schemas=schemas)):
            with patch("app.clients.ai.logging.exception") as logged:
                self.assertEqual(rebuild_conclusion(result, mock=False), text)
        logged.assert_called_once()

    def test_empty_fallback_conclusion(self) -> None:
        self.assertIn(
            "Выводов для включения в заключение нет",
            rebuild_conclusion({"findings": [], "rejected_findings": []}, mock=True),
        )
