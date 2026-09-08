from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import intake


class _ModelResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "response": json.dumps(
                    {
                        "tags": ["swelling", "not_an_allowed_tag"],
                        "confidence": 0.91,
                    }
                )
            }
        ).encode("utf-8")


class IntakeProfileTests(unittest.TestCase):
    def settings(self, enabled: bool) -> SimpleNamespace:
        return SimpleNamespace(
            local_model_enabled=enabled,
            local_model_id="qwen3.5:4b",
            local_model_url="http://127.0.0.1:11434/api/generate",
        )

    def test_rules_profile_never_calls_inference(self) -> None:
        with (
            patch.object(intake, "settings", self.settings(False)),
            patch.object(
                intake.urllib.request,
                "urlopen",
                side_effect=AssertionError("rules profile attempted inference"),
            ),
        ):
            result = intake.normalize_intake("Severe tooth pain", "exam")
        self.assertEqual(result.source, "clinician-policy-rules")
        self.assertEqual(result.tags, ("pain",))
        self.assertEqual(result.priority, "urgent")

    def test_model_profile_accepts_only_allowlisted_tags(self) -> None:
        with (
            patch.object(intake, "settings", self.settings(True)),
            patch.object(intake.urllib.request, "urlopen", return_value=_ModelResponse()),
        ):
            result = intake.normalize_intake("Face feels enlarged", "exam")
        self.assertEqual(result.source, "qwen3.5:4b")
        self.assertEqual(result.tags, ("swelling",))
        self.assertEqual(result.priority, "urgent")
        self.assertEqual(result.confidence, 0.91)

    def test_model_failure_falls_back_to_rules(self) -> None:
        with (
            patch.object(intake, "settings", self.settings(True)),
            patch.object(intake.urllib.request, "urlopen", side_effect=OSError("offline")),
        ):
            result = intake.normalize_intake("Routine cleaning", "cleaning")
        self.assertEqual(result.source, "clinician-policy-rules")
        self.assertEqual(result.tags, ("routine_care",))
        self.assertEqual(result.priority, "routine")


if __name__ == "__main__":
    unittest.main()
