from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR, Settings
from app.main import create_app
from app.schemas import AnalysisResult


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


class ApiTest(TestCase):
    def setUp(self) -> None:
        storage = BACKEND_DIR / "storage"
        storage.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=storage)
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(storage.resolve()))
        config = Settings(_env_file=None, ai_mock=True, storage_dir=Path(self.temp.name))
        self.client = TestClient(create_app(config))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_demo_end_to_end(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        response = self.client.post("/api/analyses/demo")
        self.assertEqual(response.status_code, 200)
        analysis_id = response.json()["id"]

        status = self.client.get(f"/api/analyses/{analysis_id}")
        self.assertEqual(status.json()["status"], "done")
        self.assertEqual(status.json()["progress"], 1)

        result_response = self.client.get(f"/api/analyses/{analysis_id}/result")
        self.assertEqual(result_response.status_code, 200)
        result = AnalysisResult.model_validate(result_response.json())
        self.assertEqual(result.meta.provider, "mock")
        self.assertTrue(any(change.status == "created" for change in result.unit_changes))

        evidence_list = [e for item in result.units for e in item.evidence]
        evidence_list += [e for item in result.unit_changes for e in item.evidence]
        evidence_list += [e for item in result.findings for e in item.evidence]
        for evidence in evidence_list:
            clause = self.client.get(
                f"/api/analyses/{analysis_id}/documents/{evidence.doc_id}/clauses/{evidence.clause_id}"
            )
            self.assertEqual(clause.status_code, 200)
            self.assertIn(evidence.quote, clause.json()["text"])

        report = self.client.get(f"/api/analyses/{analysis_id}/report.docx")
        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.content.startswith(b"PK"))

    def test_upload_validation_and_pending_result(self) -> None:
        response = self.client.post(
            "/api/analyses",
            files=[
                ("before", ("before.docx", docx_bytes("3.4. Старый пункт"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                ("after", ("after.docx", docx_bytes("3.4. Новый пункт"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ],
        )
        self.assertEqual(response.status_code, 200)
        analysis_id = response.json()["id"]
        self.assertEqual(self.client.get(f"/api/analyses/{analysis_id}").json()["status"], "done")

        bad = self.client.post(
            "/api/analyses",
            files=[("before", ("bad.txt", b"bad")), ("after", ("ok.docx", b"ok"))],
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("error", bad.json())

        pending_id = self.client.app.state.store.create([
            ("before", "before.docx", docx_bytes("3.4. Старый пункт")),
            ("after", "after.docx", docx_bytes("3.4. Новый пункт")),
        ])
        pending = self.client.get(f"/api/analyses/{pending_id}/result")
        self.assertEqual(pending.status_code, 409)
        self.assertIn("error", pending.json())
        self.assertEqual(self.client.get(f"/api/analyses/{pending_id}/report.docx").status_code, 409)
        missing = self.client.get("/api/analyses/" + "0" * 32)
        self.assertEqual(missing.status_code, 404)

    def test_analysis_failure_is_exposed_as_status(self) -> None:
        config = Settings(_env_file=None, ai_mock=False, storage_dir=Path(self.temp.name))
        client = TestClient(create_app(config))
        with patch("app.services.analyses.run_analysis", side_effect=RuntimeError("secret diagnostics")):
            response = client.post(
                "/api/analyses",
                files=[
                    ("before", ("before.docx", docx_bytes("3.4. До"))),
                    ("after", ("after.docx", docx_bytes("3.4. После"))),
                ],
            )
        self.assertEqual(response.status_code, 200)
        status = client.get(f"/api/analyses/{response.json()['id']}").json()
        self.assertEqual(status["status"], "failed")
        self.assertNotIn("secret diagnostics", str(status))
        client.close()
