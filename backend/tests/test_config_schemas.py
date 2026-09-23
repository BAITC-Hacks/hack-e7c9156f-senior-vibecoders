import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings
from app.schemas import AnalysisStatus, ReviewRequest


class ConfigAndSchemaTest(TestCase):
    def test_environment_settings_and_explicit_override(self) -> None:
        values = {
            "AI_MOCK": "false", "STORAGE_DIR": "C:/temporary/analyses",
            "FRONTEND_ORIGIN": "https://frontend.example",
        }
        with patch.dict(os.environ, values):
            settings = Settings(_env_file=None)
            self.assertFalse(settings.ai_mock)
            self.assertEqual(settings.storage_dir, Path(values["STORAGE_DIR"]))
            self.assertEqual(settings.frontend_origin, values["FRONTEND_ORIGIN"])
            self.assertTrue(Settings(_env_file=None, ai_mock=True).ai_mock)

    def test_status_and_review_request_validate_contract_values(self) -> None:
        status = AnalysisStatus(id="a1", status="queued", progress=0)
        self.assertIsNone(status.created_at)
        self.assertEqual(ReviewRequest(status="accepted").status, "accepted")
        for progress in (-0.01, 1.01):
            with self.assertRaises(ValidationError):
                AnalysisStatus(id="a1", status="running", progress=progress)
        with self.assertRaises(ValidationError):
            AnalysisStatus(id="a1", status="unknown", progress=0.5)
        with self.assertRaises(ValidationError):
            ReviewRequest(status="pending")
