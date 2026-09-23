import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.config import BACKEND_DIR, Settings
from app.services.analyses import AnalysisStore


def fixture_result() -> dict:
    return json.loads((BACKEND_DIR / "mocks" / "result.json").read_text(encoding="utf-8"))


class AnalysisStoreTest(TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.store = AnalysisStore(Settings(_env_file=None, ai_mock=True, storage_dir=self.folder))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create(self) -> tuple[str, Path]:
        analysis_id = self.store.create([
            ("before", "old.docx", b"old"), ("after", "new.pdf", b"new"),
        ])
        return analysis_id, self.store.directory(analysis_id)

    def test_create_persists_files_metadata_and_queued_status(self) -> None:
        analysis_id, folder = self.create()
        self.assertEqual(len(analysis_id), 32)
        self.assertEqual((folder / "before-1" / "old.docx").read_bytes(), b"old")
        self.assertEqual((folder / "after-1" / "new.pdf").read_bytes(), b"new")
        self.assertEqual([d["doc_id"] for d in self.store.documents(folder)], ["before-1", "after-1"])
        self.assertEqual([d["path"] for d in self.store.documents(folder)], ["before-1/old.docx", "after-1/new.pdf"])
        status = self.store.status(folder)
        self.assertEqual((status.status, status.progress), ("queued", 0))
        datetime.fromisoformat(status.created_at)

    def test_directory_rejects_invalid_or_traversal_ids(self) -> None:
        analysis_id, folder = self.create()
        self.assertEqual(self.store.directory(analysis_id), folder)
        for invalid in ("../storage", "../../ai", "A" * 32, "0" * 32, ""):
            self.assertIsNone(self.store.directory(invalid))

    def test_same_filename_is_kept_for_each_document(self) -> None:
        analysis_id = self.store.create([
            ("before", "policy.docx", b"first"),
            ("before", "policy.docx", b"second"),
            ("after", "policy.docx", b"third"),
        ])
        folder = self.store.directory(analysis_id)
        documents = self.store.documents(folder)
        self.assertEqual([d["name"] for d in documents], ["policy.docx"] * 3)
        self.assertEqual([d["path"] for d in documents], [
            "before-1/policy.docx", "before-2/policy.docx", "after-1/policy.docx",
        ])
        self.assertEqual([(folder / d["path"]).read_bytes() for d in documents], [
            b"first", b"second", b"third",
        ])

    def test_windows_reserved_filename_is_safe_to_store(self) -> None:
        analysis_id = self.store.create([
            ("before", "CON.docx", b"old"), ("after", "Plan?.pdf", b"new"),
        ])
        folder = self.store.directory(analysis_id)
        paths = [d["path"] for d in self.store.documents(folder)]
        self.assertEqual(paths, ["before-1/_CON.docx", "after-1/Plan_.pdf"])
        self.assertTrue(all((folder / path).exists() for path in paths))

    def test_run_progress_preserves_created_at_and_all_result_fields(self) -> None:
        analysis_id, folder = self.create()
        created_at = self.store.status(folder).created_at
        expected = fixture_result()
        expected["future_field"] = {"kept": True}
        observed = []

        def fake_run(before, after, on_progress, *, mock):
            self.assertEqual(before, [folder / "before-1" / "old.docx"])
            self.assertEqual(after, [folder / "after-1" / "new.pdf"])
            self.assertTrue(mock)
            on_progress("alignment", 0.35)
            observed.append(self.store.status(folder).model_dump())
            return expected

        with patch("app.services.analyses.run_analysis", side_effect=fake_run):
            self.store.run(analysis_id)

        self.assertEqual(observed[0]["step"], "alignment")
        self.assertEqual(observed[0]["progress"], 0.35)
        self.assertEqual(observed[0]["created_at"], created_at)
        self.assertEqual(self.store.status(folder).status, "done")
        self.assertEqual(self.store.status(folder).created_at, created_at)
        self.assertEqual(self.store.result(folder)["future_field"], {"kept": True})

    def test_history_counts_sorts_and_reads_legacy_status(self) -> None:
        first_id, first_folder = self.create()
        self.store.run(first_id)
        second_id, second_folder = self.create()
        history = self.store.history()
        self.assertEqual([item["id"] for item in history], [second_id, first_id])
        self.assertNotIn("counts", history[0])
        self.assertEqual(history[1]["counts"], {"findings": 1, "rejected": 1, "high": 0})

        status_path = first_folder / "status.json"
        legacy = json.loads(status_path.read_text(encoding="utf-8"))
        legacy.pop("created_at")
        self.store._write_json(status_path, legacy)
        fallback = self.store.status(first_folder).created_at
        self.assertIsNotNone(datetime.fromisoformat(fallback))
        self.assertEqual(AnalysisStore(self.store.settings).status(first_folder).created_at, fallback)
        self.assertEqual(self.store.status(second_folder).status, "queued")

    def test_review_saves_both_finding_lists_and_keeps_new_fields(self) -> None:
        analysis_id, folder = self.create()
        self.store.run(analysis_id)
        original = deepcopy(self.store.result(folder))
        self.assertIsNone(self.store.review(folder, "missing", "accepted", None))
        self.assertEqual(self.store.result(folder), original)

        self.store.review(folder, "f1", "rejected", "Not supported")
        updated = self.store.review(folder, "f2", "accepted", "Confirmed")
        self.assertEqual(updated["findings"][0]["review"]["status"], "rejected")
        self.assertEqual(updated["rejected_findings"][0]["review"]["status"], "accepted")
        self.assertIn("Возможная утрата должностей", updated["conclusion_md"])
        self.assertNotIn("Созданы ДИТААД", updated["conclusion_md"])
        for key in ("documents", "alignments", "flows", "categories"):
            self.assertEqual(updated[key], original[key])
        self.assertEqual(AnalysisStore(self.store.settings).result(folder), updated)

    def test_failure_and_demo_fallback(self) -> None:
        real_store = AnalysisStore(Settings(_env_file=None, ai_mock=False, storage_dir=self.folder))
        normal_id = real_store.create([
            ("before", "old.docx", b"old"), ("after", "new.docx", b"new"),
        ])
        original_created_at = real_store.status(real_store.directory(normal_id)).created_at
        with patch("app.services.analyses.run_analysis", side_effect=RuntimeError("secret diagnostics")):
            real_store.run(normal_id)
        failed_folder = real_store.directory(normal_id)
        self.assertEqual(real_store.status(failed_folder).status, "failed")
        self.assertEqual(real_store.status(failed_folder).created_at, original_created_at)
        self.assertNotIn("secret diagnostics", real_store.status(failed_folder).error)
        self.assertFalse((failed_folder / "result.json").exists())

        demo_id = real_store.create_demo()
        with patch("app.services.analyses.run_analysis", side_effect=[
            RuntimeError("LLM unavailable"), fixture_result(),
        ]) as run:
            real_store.run(demo_id)
        self.assertEqual([call.kwargs["mock"] for call in run.call_args_list], [False, True])
        self.assertEqual(real_store.status(real_store.directory(demo_id)).status, "done")

        failed_demo_id = real_store.create_demo()
        with patch("app.services.analyses.run_analysis", side_effect=[
            RuntimeError("AI unavailable"), RuntimeError("mock unavailable"),
        ]):
            real_store.run(failed_demo_id)
        self.assertEqual(real_store.status(real_store.directory(failed_demo_id)).status, "failed")

        missing_ai_id = real_store.create([
            ("before", "old.docx", b"old"), ("after", "new.docx", b"new"),
        ])
        with patch("app.services.analyses.run_analysis", side_effect=ModuleNotFoundError("ai")):
            real_store.run(missing_ai_id)
        self.assertEqual(real_store.status(real_store.directory(missing_ai_id)).error, "Пакет ИИ недоступен")

        missing_key_id = real_store.create([
            ("before", "old.docx", b"old"), ("after", "new.docx", b"new"),
        ])
        with patch("app.services.analyses.run_analysis", side_effect=KeyError("OPENAI_API_KEY")):
            real_store.run(missing_key_id)
        self.assertEqual(real_store.status(real_store.directory(missing_key_id)).error, "ИИ не настроен: заполните ai/.env")

    def test_old_result_is_read_with_new_contract_lists(self) -> None:
        analysis_id, folder = self.create()
        legacy = fixture_result()
        for key in ("rejected_findings", "documents", "alignments", "flows", "categories"):
            legacy.pop(key)
        self.store._write_json(folder / "result.json", legacy)
        restored = self.store.result(folder)
        for key in ("rejected_findings", "documents", "alignments", "flows", "categories"):
            self.assertEqual(restored[key], [])
