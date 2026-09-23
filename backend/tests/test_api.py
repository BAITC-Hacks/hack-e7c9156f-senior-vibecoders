from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
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


class ApiTest(TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
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
        result = result_response.json()
        self.assertEqual(result["meta"]["provider"], "mock")
        self.assertTrue(any(change["status"] == "created" for change in result["unit_changes"]))
        self.assertIn("documents", result)
        self.assertIn("alignments", result)
        self.assertIn("flows", result)
        self.assertIn("categories", result)
        self.assertIn("rejected_findings", result)

        evidence_list = [e for item in result["units"] for e in item["evidence"]]
        evidence_list += [e for item in result["unit_changes"] for e in item["evidence"]]
        evidence_list += [e for item in result["findings"] for e in item["evidence"]]
        for evidence in evidence_list:
            clause = self.client.get(
                f"/api/analyses/{analysis_id}/documents/{evidence['doc_id']}/clauses/{evidence['clause_id']}"
            )
            self.assertEqual(clause.status_code, 200)
            self.assertIn(evidence["quote"], clause.json()["text"])

        report = self.client.get(f"/api/analyses/{analysis_id}/report.docx")
        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.content.startswith(b"PK"))
        self.assertIn(f"zaklyuchenie_{analysis_id}.docx", report.headers["content-disposition"])

    def test_review_history_and_report(self) -> None:
        first_id = self.client.post("/api/analyses/demo").json()["id"]
        second_id = self.client.post("/api/analyses/demo").json()["id"]
        history = self.client.get("/api/analyses").json()
        self.assertEqual([row["id"] for row in history], [second_id, first_id])
        self.assertEqual(history[0]["counts"], {"findings": 1, "rejected": 1, "high": 0})
        self.assertEqual([d["side"] for d in history[0]["documents"]], ["before", "after"])
        self.assertIn("created_at", self.client.get(f"/api/analyses/{first_id}").json())
        self.assertEqual(self.client.get(f"/api/analyses/{first_id}/report.docx").status_code, 200)

        accepted = self.client.patch(
            f"/api/analyses/{first_id}/findings/f2",
            json={"status": "accepted", "comment": "Проверено"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("Возможная утрата должностей", accepted.json()["conclusion_md"])
        self.assertEqual(accepted.json()["rejected_findings"][0]["review"]["status"], "accepted")
        self.assertIn("reviewed_at", accepted.json()["rejected_findings"][0]["review"])

        rejected = self.client.patch(
            f"/api/analyses/{first_id}/findings/f1", json={"status": "rejected"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertNotIn("Созданы ДИТААД", rejected.json()["conclusion_md"])
        self.assertEqual(self.client.get(f"/api/analyses/{first_id}/result").json(), rejected.json())
        self.assertEqual(self.client.patch(
            f"/api/analyses/{first_id}/findings/absent", json={"status": "accepted"},
        ).status_code, 404)

        report = self.client.get(f"/api/analyses/{first_id}/report.docx")
        document = Document(BytesIO(report.content))
        self.assertIn("Служебная записка", [p.text for p in document.paragraphs])
        self.assertTrue(any("После: demo_after.docx" in p.text for p in document.paragraphs))
        self.assertTrue(any("Принято" in cell.text for row in document.tables[0].rows for cell in row.cells))

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
        self.assertEqual(bad.status_code, 415)
        self.assertIn("error", bad.json())
        oversized = self.client.post("/api/analyses", files=[
            ("before", ("large.pdf", b"x" * (20 * 1024 * 1024 + 1))),
            ("after", ("after.docx", docx_bytes("3.4. Новый пункт"))),
        ])
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.client.post("/api/analyses", files=[
            ("before", ("before.docx", docx_bytes("3.4. Старый пункт"))),
        ]).status_code, 400)

        pending_id = self.client.app.state.store.create([
            ("before", "before.docx", docx_bytes("3.4. Старый пункт")),
            ("after", "after.docx", docx_bytes("3.4. Новый пункт")),
        ])
        pending = self.client.get(f"/api/analyses/{pending_id}/result")
        self.assertEqual(pending.status_code, 409)
        self.assertIn("error", pending.json())
        self.assertEqual(self.client.get(f"/api/analyses/{pending_id}/report.docx").status_code, 409)
        self.assertEqual(self.client.patch(
            f"/api/analyses/{pending_id}/findings/f1", json={"status": "accepted"},
        ).status_code, 409)
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
