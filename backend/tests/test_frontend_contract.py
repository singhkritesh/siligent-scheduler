from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[2]


class IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.id_counts: dict[str, int] = {}
        self.inline_scripts = 0
        self.inline_styles = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            element_id = str(values["id"])
            self.ids.add(element_id)
            self.id_counts[element_id] = self.id_counts.get(element_id, 0) + 1
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1
        if "style" in values:
            self.inline_styles += 1


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "frontend" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        cls.css = (ROOT / "frontend" / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        cls.parser = IdParser()
        cls.parser.feed(cls.html)

    def test_every_static_id_used_by_javascript_exists(self) -> None:
        references = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', self.javascript))
        generated_at_runtime = {"intake-confirmation"}
        missing = references - self.parser.ids - generated_at_runtime
        self.assertEqual(missing, set(), f"JavaScript references missing DOM ids: {missing}")

    def test_static_ids_are_unique(self) -> None:
        duplicates = {
            element_id for element_id, count in self.parser.id_counts.items() if count > 1
        }
        self.assertEqual(duplicates, set(), f"Duplicate DOM ids: {duplicates}")

    def test_navigation_targets_have_matching_views(self) -> None:
        targets = set(re.findall(r'data-route="([a-z/-]+)"', self.html))
        for target in targets:
            root = target.split("/", 1)[0]
            self.assertIn(f'{root}-view', self.parser.ids)

    def test_role_aware_routes_are_declared(self) -> None:
        required_routes = {
            "home",
            "operations",
            "scheduler",
            "waitlist",
            "calendar",
            "analytics",
            "simulation",
            "configuration/people",
            "audit",
        }
        routes = set(re.findall(r'data-route="([a-z/-]+)"', self.html))
        self.assertTrue(required_routes.issubset(routes))
        self.assertIn('data-roles="administrator,auditor"', self.html)

    def test_auditor_patient_views_are_backed_by_server_authorization(self) -> None:
        backend = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        for function_name in ("dashboard", "list_appointments", "operations", "list_waitlist"):
            match = re.search(
                rf"def {function_name}\([\s\S]*?Depends\(([^\n]+)\)",
                backend,
            )
            self.assertIsNotNone(match, f"Missing dependency for {function_name}")
            dependency = match.group(1)
            self.assertIn("require_roles", dependency)
            self.assertNotIn("auditor", dependency)

    def test_content_security_policy_compatible_markup(self) -> None:
        self.assertEqual(self.parser.inline_scripts, 0)
        self.assertEqual(self.parser.inline_styles, 0)
        self.assertNotIn('style="', self.javascript)
        self.assertIn('<progress class="progress"', self.javascript)

    def test_offline_assets_are_same_origin(self) -> None:
        self.assertNotRegex(self.html, r'https?://')
        self.assertIn('src="/static/app.js"', self.html)
        self.assertIn('href="/static/app.css"', self.html)

    def test_calibration_is_optional_and_defaults_remain_active(self) -> None:
        self.assertIn("Reference defaults work immediately", self.html)
        self.assertIn("Local history is optional", self.javascript)
        self.assertIn("No data required", self.javascript)

    def test_contextual_help_covers_every_route(self) -> None:
        self.assertIn('id="page-help-button"', self.html)
        self.assertIn('id="help-dialog"', self.html)
        for route in (
            "home", "operations", "scheduler", "waitlist", "calendar",
            "analytics", "simulation", "configuration", "audit",
        ):
            self.assertRegex(self.javascript, rf"\n\s*{route}:\s*{{")
        self.assertIn("showModal()", self.javascript)

    def test_simulation_upload_is_previewed_and_never_books(self) -> None:
        for element_id in (
            "simulation-file",
            "simulation-preview-button",
            "simulation-preview-table",
            "simulation-run-button",
            "simulation-results-table",
            "simulation-download-results",
            "simulation-download-report",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('accept=".csv,.xlsx', self.html)
        self.assertIn('/api/simulations/preview', self.javascript)
        self.assertIn('/api/simulations/run', self.javascript)
        self.assertIn("report.live_calendar_changed === false", self.javascript)
        self.assertIn("setSimulationBusy(true)", self.javascript)
        self.assertIn('state.simulationFile = $("#simulation-file").files[0] || null', self.javascript)
        self.assertIn("window.setTimeout(() => URL.revokeObjectURL(url), 1000)", self.javascript)

    def test_scheduling_is_progressive_and_requires_review(self) -> None:
        self.assertEqual(self.html.count('data-schedule-step="'), 4)
        self.assertIn('id="patient-search"', self.html)
        self.assertIn('api("/api/patients/search"', self.javascript)
        self.assertNotIn("/api/patients?q=", self.javascript)
        self.assertIn('id="confirm-dialog"', self.html)
        self.assertIn('id="confirm-slot-button"', self.html)
        self.assertNotIn("window.confirm", self.javascript)
        self.assertNotIn("window.prompt", self.javascript)
        self.assertRegex(
            self.html,
            r'id="patient-name" required minlength="2" maxlength="160"',
        )
        self.assertRegex(
            self.html,
            r'id="patient-mrn" required minlength="2" maxlength="80"',
        )
        self.assertIn('patient_name: $("#patient-name").value.trim()', self.javascript)
        self.assertIn('medical_record_number: $("#patient-mrn").value.trim()', self.javascript)
        self.assertIn('Patient record number (MRN)', self.javascript)

    def test_reserved_blocks_are_visible_governed_and_override_gated(self) -> None:
        for element_id in (
            "configuration-reserved-blocks",
            "reserved-block-form",
            "reserved-block-override-search",
            "reserved-block-override-review",
            "reserved-block-override-reason",
            "reserved-block-override-acknowledgement",
            "reserved-block-release-dialog",
            "day-reserved-blocks",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("requires_reserved_block_override", self.javascript)
        self.assertIn("reserved_block_override_acknowledged", self.javascript)
        self.assertIn("/api/configuration/reserved-blocks", self.javascript)

    def test_vacancy_recovery_is_localized_and_permission_gated(self) -> None:
        for element_id in (
            "vacancy-recovery-dialog",
            "start-vacancy-recovery",
            "find-vacancy-candidates",
            "vacancy-candidates",
            "vacancy-permission-method",
            "vacancy-permission-confirmed",
            "vacancy-exact-acknowledged",
            "apply-vacancy-move",
            "vacancy-recovery-history",
            "vacancy-stop-button",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("No automatic reshuffling", self.html)
        self.assertIn("One permission, one move", self.html)
        self.assertIn("patient_permission_confirmed", self.javascript)
        self.assertIn("exact_move_acknowledged", self.javascript)
        self.assertIn("/vacancy-recovery", self.javascript)
        self.assertIn("Resume recovery", self.javascript)
        self.assertIn("View recovery", self.javascript)
        self.assertIn("resumeVacancyRecovery", self.javascript)
        self.assertNotIn("window.confirm", self.javascript)

    def test_appointment_lists_use_explicit_schedule_columns(self) -> None:
        for label in ("Patient name", "Procedure", "Start", "End", "Doctor / room", "Status", "Actions"):
            self.assertIn(f"<span>{label}</span>", self.javascript)
        self.assertIn('class="appointment-patient"', self.javascript)
        self.assertIn('class="appointment-procedure"', self.javascript)
        self.assertIn('class="appointment-start"', self.javascript)
        self.assertIn('class="appointment-end"', self.javascript)

    def test_settings_are_segmented_and_forms_are_progressively_disclosed(self) -> None:
        for section in ("people", "availability", "resources", "clinical", "calibration"):
            self.assertIn(f'data-settings-section="{section}"', self.html)
            self.assertIn(f'data-settings-route="{section}"', self.html)
        self.assertGreaterEqual(self.html.count('class="editor-disclosure"'), 10)

    def test_responsive_navigation_does_not_hide_authorized_destinations(self) -> None:
        self.assertIn("@media (max-width: 820px)", self.css)
        self.assertIn("overflow-x: auto", self.css)
        self.assertNotIn(".nav-item:nth-of-type", self.css)

    def test_schedule_columns_reflow_before_they_become_cramped(self) -> None:
        self.assertIn("@media (max-width: 1279px)", self.css)
        self.assertIn(".appointment-table-head { display: none; }", self.css)
        self.assertIn("content: attr(data-label)", self.css)
        self.assertIn(".home-grid { display: grid; grid-template-columns: 1fr;", self.css)

    def test_practice_timezone_controls_display_and_local_configuration_inputs(self) -> None:
        self.assertIn("function practiceTimeZone()", self.javascript)
        self.assertIn("function practiceLocalToIso(value)", self.javascript)
        self.assertIn("timeZone: practiceTimeZone()", self.javascript)
        self.assertNotIn('new Date($("#leave-start").value).toISOString()', self.javascript)
        self.assertNotIn('new Date($("#closure-start").value).toISOString()', self.javascript)
        self.assertNotIn('new Date($("#reserved-block-start").value).toISOString()', self.javascript)


if __name__ == "__main__":
    unittest.main()
