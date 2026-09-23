from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


class AiIntegrationTest(TestCase):
    def test_upload_runs_installed_ai_pipeline_and_preserves_document_names(self) -> None:
        from ai import pipeline
        from ai.schemas import AnalysisResult

        with TemporaryDirectory() as temp:
            config = Settings(_env_file=None, ai_mock=False, storage_dir=Path(temp))
            with TestClient(create_app(config)) as client:
                # Only LLM-dependent stages are stubbed; parsing, alignment,
                # orchestration and Pydantic serialization use the real AI package.
                with (
                    patch.object(pipeline, "extract_all_units", return_value=[]),
                    patch.object(pipeline, "match_units", return_value=[]),
                    patch.object(pipeline, "analyze_functions", return_value=SimpleNamespace(
                        mappings=[], findings=[], funcs=[], flows=[],
                    )),
                    patch.object(pipeline, "structure_findings", return_value=[]),
                    patch.object(pipeline, "conflict_findings", return_value=[]),
                    patch.object(pipeline, "run_critic", return_value=([], [])),
                    patch.object(pipeline, "write_conclusion", return_value="# Итог\n\nПроверено локально."),
                    patch.object(pipeline, "provider", return_value="openai"),
                    patch.object(pipeline, "model_name", return_value="offline-test"),
                ):
                    created = client.post("/api/analyses", files=[
                        ("before", ("Old Rules.docx", docx_bytes("3.4. Старая структура"))),
                        ("after", ("New Rules.docx", docx_bytes("3.4. Новая структура"))),
                    ])

                self.assertEqual(created.status_code, 200)
                analysis_id = created.json()["id"]
                status = client.get(f"/api/analyses/{analysis_id}").json()
                self.assertEqual(status["status"], "done", status)
                result = client.get(f"/api/analyses/{analysis_id}/result").json()
                AnalysisResult.model_validate(result)
                self.assertEqual(result["meta"]["provider"], "openai")
                self.assertEqual(
                    [(doc["doc_id"], doc["name"]) for doc in result["documents"]],
                    [("b1", "Old Rules.docx"), ("a1", "New Rules.docx")],
                )
                self.assertIn("Старая структура", client.get(
                    f"/api/analyses/{analysis_id}/documents/b1/clauses/3.4"
                ).json()["text"])
                self.assertEqual(
                    [document["name"] for document in client.get("/api/analyses").json()[0]["documents"]],
                    ["Old Rules.docx", "New Rules.docx"],
                )
                report = client.get(f"/api/analyses/{analysis_id}/report.docx")
                self.assertEqual(report.status_code, 200)
                self.assertTrue(report.content.startswith(b"PK"))
