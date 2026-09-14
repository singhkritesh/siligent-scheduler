"""End-to-end smoke test for a running local stack.

The test uses only synthetic records. It intentionally leaves the resulting
appointment and audit evidence in the local development database.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).parents[2]


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


class Client:
    def __init__(self, base_url: str):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.base_url = base_url
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"},
        )
        try:
            with self.opener.open(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8")) if response.length != 0 else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8")
            raise AssertionError(f"{method} {path} failed with {error.code}: {detail}") from error

    def request_file(self, path: str, filename: str, content: bytes, content_type: str):
        boundary = "----SiligentSyntheticSimulationBoundary"
        data = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("ascii") + content + f"\r\n--{boundary}--\r\n".encode("ascii")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        try:
            with self.opener.open(request, timeout=240) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8")
            raise AssertionError(f"POST {path} failed with {error.code}: {detail}") from error

    def expect_file_error(
        self,
        path: str,
        filename: str,
        content: bytes,
        content_type: str,
        expected_status: int,
    ) -> str:
        boundary = "----SiligentSyntheticRejectedUploadBoundary"
        data = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("ascii") + content + f"\r\n--{boundary}--\r\n".encode("ascii")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        try:
            self.opener.open(request, timeout=45)
        except urllib.error.HTTPError as error:
            assert error.code == expected_status, f"expected {expected_status}, got {error.code}"
            return error.read().decode("utf-8")
        raise AssertionError(f"POST {path} unexpectedly succeeded")

    def expect_error(
        self, method: str, path: str, body: dict | None, expected_status: int
    ) -> str:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"},
        )
        try:
            self.opener.open(request, timeout=45)
        except urllib.error.HTTPError as error:
            assert error.code == expected_status, f"expected {expected_status}, got {error.code}"
            return error.read().decode("utf-8")
        raise AssertionError(f"{method} {path} unexpectedly succeeded")


def main() -> int:
    env = load_env()
    run_key = datetime.now().strftime("%Y%m%d%H%M%S%f")
    client = Client(f"https://127.0.0.1:{env.get('UI_PORT', '8443')}")
    health = client.request("GET", "/health")
    assert health["status"] == "ok" and health["mode"] == "offline"

    login = client.request(
        "POST",
        "/api/auth/login",
        {
            "username": env["BOOTSTRAP_ADMIN_USERNAME"],
            "password": env["BOOTSTRAP_ADMIN_PASSWORD"],
        },
    )
    assert login["user"]["role"] == "administrator"

    auditor_username = f"synthetic-auditor-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    auditor_password = "Synthetic-Auditor-Only-123!"
    client.request(
        "POST",
        "/api/configuration/users",
        {
            "username": auditor_username,
            "display_name": "Synthetic Authorization Auditor",
            "role": "auditor",
            "password": auditor_password,
        },
    )
    auditor = Client(client.base_url)
    auditor_login = auditor.request(
        "POST", "/api/auth/login", {"username": auditor_username, "password": auditor_password}
    )
    assert auditor_login["user"]["role"] == "auditor"
    for protected_path in (
        "/api/dashboard",
        f"/api/appointments?date_from={date.today()}&date_to={date.today()}",
        f"/api/operations?day={date.today()}",
        "/api/waitlist",
    ):
        auditor.expect_error("GET", protected_path, None, 403)
    assert "events" in auditor.request("GET", "/api/audit")

    catalog = client.request("GET", "/api/catalog")
    assert catalog["procedures"] and catalog["doctors"]
    assert len(catalog["rooms"]) >= 8
    assert len([item for item in catalog["providers"] if item["role"] == "hygienist"]) >= 5
    assert len([item for item in catalog["providers"] if item["role"] == "assistant"]) >= 4
    assert all(item["phases"] for item in catalog["procedures"])

    for support_role in ("assistant", "hygienist"):
        support_code = f"SYNTH-{support_role[:3].upper()}-{run_key[-10:]}"
        support = client.request(
            "POST",
            "/api/configuration/providers",
            {
                "staff_code": support_code,
                "display_name": f"Synthetic {support_role.title()} Delete",
                "role": support_role,
            },
        )
        support_impact = client.request(
            "GET", f"/api/configuration/providers/{support['id']}/deletion-impact"
        )
        assert support_impact["blocking_total"] == 0 and support_impact["setup_total"] >= 5
        client.expect_error(
            "DELETE",
            f"/api/configuration/providers/{support['id']}",
            {"reason": "Synthetic permanent deletion validation", "confirm_permanent_delete": True},
            409,
        )
        support_deactivated = client.request(
            "PUT",
            f"/api/configuration/providers/{support['id']}/status",
            {"active": False, "reason": "Synthetic provider lifecycle validation"},
        )
        assert support_deactivated["active"] is False
        support_deleted = client.request(
            "DELETE",
            f"/api/configuration/providers/{support['id']}",
            {"reason": "Synthetic permanent deletion validation", "confirm_permanent_delete": True},
        )
        assert support_deleted["permanently_deleted"] is True

    disposable_doctor = client.request(
        "POST",
        "/api/configuration/doctors",
        {
            "staff_code": f"SYNTH-DEL-{run_key[-10:]}",
            "display_name": "Synthetic Dentist Delete",
            "specialty": "General dentistry",
            "procedure_codes": [catalog["procedures"][0]["code"]],
            "max_active_rooms": 1,
        },
    )
    client.request(
        "PUT",
        f"/api/configuration/doctors/{disposable_doctor['id']}/status",
        {"active": False, "reason": "Synthetic dentist permanent deletion validation"},
    )
    disposable_deleted = client.request(
        "DELETE",
        f"/api/configuration/providers/{disposable_doctor['provider_id']}",
        {"reason": "Synthetic dentist permanent deletion validation", "confirm_permanent_delete": True},
    )
    assert disposable_deleted["permanently_deleted"] is True

    doctor_code = f"SYNTH-DOC-{run_key[-12:]}"
    doctor = client.request(
        "POST",
        "/api/configuration/doctors",
        {
            "staff_code": doctor_code,
            "display_name": "Synthetic Dentist Lifecycle",
            "specialty": "General dentistry",
            "procedure_codes": [catalog["procedures"][0]["code"]],
            "max_active_rooms": 2,
        },
    )
    created_configuration = client.request("GET", "/api/configuration")
    created_dentist = next(
        item for item in created_configuration["providers"] if item["doctor_id"] == doctor["id"]
    )
    dentist_username = f"synthetic-dentist-{run_key[-12:]}"
    dentist_password = "Synthetic-Dentist-Only-123!"
    dentist_account = client.request(
        "POST",
        "/api/configuration/users",
        {
            "username": dentist_username,
            "display_name": "Synthetic Dentist Account",
            "role": "clinician",
            "provider_id": doctor["provider_id"],
            "password": dentist_password,
        },
    )
    assert created_dentist["active"] is True and created_dentist["doctor_active"] is True
    lifecycle_search = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Dentist Lifecycle Patient",
            "medical_record_number": f"SYNTHETIC-DENTIST-{run_key}",
            "procedure_code": catalog["procedures"][0]["code"],
            "condition": "",
            "date_from": (date.today() + timedelta(days=90)).isoformat(),
            "date_to": (date.today() + timedelta(days=150)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": doctor["id"],
        },
    )
    lifecycle_candidates = [
        item for item in lifecycle_search["candidates"] if item["doctor_id"] == doctor["id"]
    ]
    assert lifecycle_candidates, "expected a future synthetic appointment for the new dentist"
    lifecycle_booking = client.request(
        "POST",
        "/api/appointments",
        {"recommendation_id": lifecycle_candidates[0]["id"], "staff_confirms_intake": True},
    )
    assert lifecycle_booking["status"] == "confirmed" and lifecycle_booking["locked"] is True
    lifecycle_block_search = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Dentist Block Preview",
            "medical_record_number": f"SYNTHETIC-DENTIST-BLOCK-{run_key}",
            "procedure_code": catalog["procedures"][0]["code"],
            "condition": "",
            "date_from": (date.today() + timedelta(days=200)).isoformat(),
            "date_to": (date.today() + timedelta(days=240)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": doctor["id"],
        },
    )
    lifecycle_block_candidates = [
        item for item in lifecycle_block_search["candidates"] if item["doctor_id"] == doctor["id"]
    ]
    assert lifecycle_block_candidates, "expected a protected-block candidate for the new dentist"
    lifecycle_block_slot = lifecycle_block_candidates[0]
    lifecycle_block = client.request(
        "POST",
        "/api/configuration/reserved-blocks",
        {
            "doctor_id": doctor["id"],
            "procedure_code": catalog["procedures"][0]["code"],
            "starts_at": lifecycle_block_slot["starts_at"],
            "ends_at": lifecycle_block_slot["ends_at"],
            "room_id": None,
            "equipment_id": None,
            "equipment_unit_number": None,
            "release_at": None,
            "reason": "Synthetic dentist lifecycle protected block",
        },
    )
    assert lifecycle_block["count"] == 1
    impact = client.request("GET", f"/api/configuration/doctors/{doctor['id']}/impact")
    assert impact["future_appointment_count"] >= 1 and impact["active_block_count"] == 1
    client.expect_error(
        "PUT",
        f"/api/configuration/doctors/{doctor['id']}/status",
        {"active": False, "reason": "Synthetic dentist lifecycle validation"},
        409,
    )
    client.expect_error(
        "PUT",
        f"/api/configuration/doctors/{doctor['id']}/status",
        {
            "active": False,
            "reason": "Synthetic dentist lifecycle validation",
            "acknowledge_future_appointments": True,
        },
        409,
    )
    deactivated = client.request(
        "PUT",
        f"/api/configuration/doctors/{doctor['id']}/status",
        {
            "active": False,
            "reason": "Synthetic dentist lifecycle validation",
            "acknowledge_future_appointments": True,
            "release_active_blocks": True,
        },
    )
    assert deactivated["active"] is False and deactivated["changed"] is True
    client.expect_error(
        "DELETE",
        f"/api/configuration/providers/{doctor['provider_id']}",
        {"reason": "Synthetic protected history deletion validation", "confirm_permanent_delete": True},
        409,
    )
    released_blocks = client.request("GET", "/api/reserved-blocks")
    assert any(
        item["id"] == lifecycle_block["ids"][0] and item["status"] == "released"
        for item in released_blocks["blocks"]
    ), "deactivation must release only explicitly approved protected blocks"
    preserved = client.request(
        "GET",
        f"/api/appointments?date_from={(date.today() + timedelta(days=90)).isoformat()}&date_to={(date.today() + timedelta(days=150)).isoformat()}",
    )
    assert any(
        item["id"] == lifecycle_booking["appointment_id"] and item["status"] == "confirmed"
        for item in preserved["appointments"]
    ), "deactivation must preserve the confirmed appointment"
    dentist_client = Client(client.base_url)
    dentist_client.expect_error(
        "POST", "/api/auth/login", {"username": dentist_username, "password": dentist_password}, 401
    )
    client.expect_error(
        "PUT",
        f"/api/configuration/users/{dentist_account['id']}/status",
        {"active": True, "reason": "Synthetic account activation should require dentist activation"},
        409,
    )
    reactivated = client.request(
        "PUT",
        f"/api/configuration/doctors/{doctor['id']}/status",
        {"active": True, "reason": "Synthetic dentist lifecycle reactivation"},
    )
    assert reactivated["active"] is True
    account_reactivated = client.request(
        "PUT",
        f"/api/configuration/users/{dentist_account['id']}/status",
        {"active": True, "reason": "Synthetic linked account lifecycle reactivation"},
    )
    assert account_reactivated["active"] is True
    dentist_login = dentist_client.request(
        "POST", "/api/auth/login", {"username": dentist_username, "password": dentist_password}
    )
    assert dentist_login["user"]["role"] == "clinician"

    today = date.today()
    any_opening = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Any Opening Patient",
            "medical_record_number": f"SYNTHETIC-ANY-OPENING-{run_key}",
            "procedure_code": "exam",
            "condition": "",
            "patient_always_available": True,
        },
    )
    assert any_opening["availability_assumption"] == "any_opening"
    assert any_opening["candidates"], "expected capacity for the any-opening workflow"

    basic_simulation = (
        "request_id,patient_ref,procedure_code\n"
        "BASIC-REQ-1,BASIC-PAT-1,exam\n"
        "BASIC-REQ-2,BASIC-PAT-2,cleaning\n"
    ).encode("utf-8")
    simulation_preview = client.request_file(
        "/api/simulations/preview", "basic.csv", basic_simulation, "text/csv"
    )
    assert simulation_preview["summary"]["row_count"] == 2
    assert simulation_preview["preview_rows"][0]["difficulty"] == "standard"
    assert simulation_preview["preview_rows"][0]["priority"] == "routine"
    assert simulation_preview["preview_rows"][0]["availability_assumption"] == "any_opening"
    simulation_result = client.request_file(
        "/api/simulations/run", "basic.csv", basic_simulation, "text/csv"
    )
    assert simulation_result["report"]["row_count"] == 2
    assert simulation_result["report"]["live_calendar_changed"] is False

    existing_blocks = client.request("GET", "/api/reserved-blocks")
    for item in existing_blocks["blocks"]:
        if (
            item["status"] == "active"
            and item["reason"] == "Synthetic protected crown capacity validation"
        ):
            client.request(
                "POST",
                f"/api/configuration/reserved-blocks/{item['id']}/release",
                {"reason": "Cleaning up a prior interrupted synthetic validation"},
            )
    block_seed = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Reserved Block Seed",
            "medical_record_number": f"SYNTHETIC-BLOCK-SEED-{run_key}",
            "procedure_code": "exam",
            "condition": "",
            "date_from": (today + timedelta(days=45)).isoformat(),
            "date_to": (today + timedelta(days=90)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
        },
    )
    assert block_seed["candidates"], "expected capacity for a synthetic reserved block"
    block_slot = block_seed["candidates"][0]
    reserved_block = client.request(
        "POST",
        "/api/configuration/reserved-blocks",
        {
            "doctor_id": block_slot["doctor_id"],
            "procedure_code": "crown",
            "starts_at": block_slot["starts_at"],
            "ends_at": block_slot["ends_at"],
            "room_id": None,
            "equipment_id": None,
            "equipment_unit_number": None,
            "release_at": None,
            "reason": "Synthetic protected crown capacity validation",
        },
    )
    listed_blocks = client.request("GET", "/api/reserved-blocks")
    assert any(item["id"] == reserved_block["id"] for item in listed_blocks["blocks"])

    practice_timezone = ZoneInfo(catalog["timezone"])
    block_start = datetime.fromisoformat(block_slot["starts_at"]).astimezone(practice_timezone)
    block_end = datetime.fromisoformat(block_slot["ends_at"]).astimezone(practice_timezone)
    ordinary_search = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Blocked Patient",
            "medical_record_number": f"SYNTHETIC-BLOCKED-{run_key}",
            "procedure_code": "exam",
            "condition": "",
            "date_from": block_start.date().isoformat(),
            "date_to": block_start.date().isoformat(),
            "time_from": block_start.time().isoformat(),
            "time_to": block_end.time().isoformat(),
            "preferred_doctor_id": block_slot["doctor_id"],
        },
    )
    assert not any(
        item["doctor_id"] == block_slot["doctor_id"]
        and datetime.fromisoformat(item["starts_at"]) < datetime.fromisoformat(block_slot["ends_at"])
        and datetime.fromisoformat(item["ends_at"]) > datetime.fromisoformat(block_slot["starts_at"])
        for item in ordinary_search["candidates"]
    ), "ordinary search must not use a nonmatching reserved doctor block"

    override_search = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Override Patient",
            "medical_record_number": f"SYNTHETIC-OVERRIDE-{run_key}",
            "procedure_code": "exam",
            "condition": "",
            "date_from": block_start.date().isoformat(),
            "date_to": block_start.date().isoformat(),
            "time_from": block_start.time().isoformat(),
            "time_to": block_end.time().isoformat(),
            "preferred_doctor_id": block_slot["doctor_id"],
            "allow_reserved_block_override": True,
        },
    )
    override_candidates = [
        item for item in override_search["candidates"]
        if item["doctor_id"] == block_slot["doctor_id"]
        and item["requires_reserved_block_override"]
    ]
    assert override_candidates, json.dumps(override_search, indent=2)
    override_slot = override_candidates[0]
    client.expect_error(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": override_slot["id"],
            "staff_confirms_intake": False,
        },
        409,
    )
    override_booking = client.request(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": override_slot["id"],
            "staff_confirms_intake": False,
            "reserved_block_override_acknowledged": True,
            "reserved_block_override_reason": "Synthetic exact override authorization validation",
        },
    )
    assert override_booking["locked"] is True
    client.request(
        "POST",
        f"/api/configuration/reserved-blocks/{reserved_block['id']}/release",
        {"reason": "Synthetic validation completed and protected capacity released"},
    )

    recommendations = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Validation Patient",
            "medical_record_number": f"SYNTHETIC-E2E-{run_key}",
            "procedure_code": "exam",
            "condition": "Routine checkup with mild cold sensitivity",
            "date_from": (today + timedelta(days=1)).isoformat(),
            "date_to": (today + timedelta(days=21)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
        },
    )
    assert recommendations["candidates"], "expected at least one feasible recommendation"
    assert 0 <= recommendations["intake"]["attendance_risk"]["probability"] <= 1
    assert recommendations["candidates"][0]["phases"]
    assert {phase["role"] for phase in recommendations["candidates"][0]["phases"]} >= {
        "doctor", "assistant"
    }
    patient_search = client.request(
        "POST",
        "/api/patients/search",
        {"query": f"SYNTHETIC-E2E-{run_key}", "limit": 10},
    )
    assert any(
        item["medical_record_number"] == f"SYNTHETIC-E2E-{run_key}"
        for item in patient_search["patients"]
    ), "expected the progressive scheduler's patient lookup to find the existing record"
    client.expect_error(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": recommendations["candidates"][0]["id"],
            "staff_confirms_intake": False,
        },
        409,
    )
    confirmed = client.request(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": recommendations["candidates"][0]["id"],
            "staff_confirms_intake": True,
        },
    )
    assert confirmed["status"] == "confirmed" and confirmed["locked"] is True

    appointment_id = confirmed["appointment_id"]
    reschedule_options = client.request(
        "POST",
        f"/api/appointments/{appointment_id}/reschedule-options",
        {
            "date_from": (today + timedelta(days=22)).isoformat(),
            "date_to": (today + timedelta(days=42)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
        },
    )
    assert reschedule_options["candidates"], "expected an authorized reschedule option"
    rescheduled = client.request(
        "POST",
        f"/api/appointments/{appointment_id}/reschedule",
        {
            "recommendation_id": reschedule_options["candidates"][0]["id"],
            "reason": "Synthetic end-to-end authorization validation",
        },
    )
    assert rescheduled["locked"] is True

    calendar = client.request(
        "GET",
        f"/api/appointments?date_from={(today + timedelta(days=22)).isoformat()}"
        f"&date_to={(today + timedelta(days=42)).isoformat()}",
    )
    moved = next(item for item in calendar["appointments"] if item["id"] == appointment_id)
    operation_day = moved["starts_at"][:10]
    operations = client.request("GET", f"/api/operations?day={operation_day}")
    operation_visit = next(item for item in operations["appointments"] if item["id"] == appointment_id)
    assert operation_visit["phases"]
    assert operation_visit["phases"][0]["starts_at"] == operation_visit["starts_at"]
    assert operation_visit["phases"][-1]["ends_at"] == operation_visit["ends_at"]
    assert operations["providers"]

    waitlist = client.request(
        "POST",
        "/api/waitlist",
        {
            "patient_name": "Synthetic Waitlist Patient",
            "medical_record_number": f"SYNTHETIC-E2E-WAITLIST-{run_key}",
            "procedure_code": "cleaning",
            "earliest_date": (today + timedelta(days=1)).isoformat(),
            "latest_date": (today + timedelta(days=60)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
            "priority": "routine",
            "notes": "Synthetic end-to-end waitlist validation",
        },
    )
    waitlist_matches = client.request("POST", f"/api/waitlist/{waitlist['id']}/matches")
    assert waitlist_matches["candidates"]
    assert any(
        phase["role"] == "hygienist"
        for phase in waitlist_matches["candidates"][0]["phases"]
    )
    contact = client.request(
        "POST",
        f"/api/waitlist/{waitlist['id']}/contacts",
        {"channel": "phone", "outcome": "left_message", "incentive_offered": "$10 same-day credit"},
    )
    assert contact["outcome"] == "left_message"

    configuration = client.request("GET", "/api/configuration")
    assert len(configuration["rooms"]) >= 8 and configuration["providers"]
    assert configuration["procedures"] and configuration["phases"]
    assert len(configuration["equipment"]) >= 3
    dentist_provider = next(item for item in configuration["providers"] if item["doctor_id"])
    capacity = client.request(
        "PUT",
        f"/api/configuration/doctors/{dentist_provider['doctor_id']}/capacity",
        {"max_active_rooms": dentist_provider["max_active_rooms"]},
    )
    assert capacity["max_active_rooms"] == dentist_provider["max_active_rooms"]
    client.request(
        "PUT",
        "/api/configuration/preferences",
        {"provider_id": dentist_provider["id"], "procedure_code": "exam", "preference": 0},
    )
    client.request(
        "PUT",
        "/api/configuration/shifts",
        {
            "provider_id": dentist_provider["id"],
            "shift_date": (today + timedelta(days=300)).isoformat(),
            "status": "scheduled",
            "local_start": "08:00:00",
            "local_end": "17:00:00",
            "covering_for_provider_id": None,
            "notes": "Synthetic rota validation",
        },
    )

    complex_crown = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Crown Patient",
            "medical_record_number": f"SYNTHETIC-E2E-CROWN-{run_key}",
            "procedure_code": "crown",
            "condition": "",
            "date_from": (today + timedelta(days=1)).isoformat(),
            "date_to": (today + timedelta(days=45)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
            "difficulty": "complex",
            "waitlist_consent": False,
        },
    )
    assert complex_crown["candidates"]
    assert complex_crown["candidates"][0]["equipment"], "crown must reserve the configured scanner"
    complex_minutes = sum(
        int((datetime.fromisoformat(phase["ends_at"])
             - datetime.fromisoformat(phase["starts_at"])).total_seconds() // 60)
        for phase in complex_crown["candidates"][0]["phases"]
    )
    standard_crown = next(item for item in catalog["procedures"] if item["code"] == "crown")
    assert complex_minutes > sum(item["duration_minutes"] for item in standard_crown["phases"])
    crown_booking = client.request(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": complex_crown["candidates"][0]["id"],
            "staff_confirms_intake": False,
        },
    )
    active_waitlist = client.request("GET", "/api/waitlist")
    crown_followup = next(
        item for item in active_waitlist["entries"]
        if item["predecessor_appointment_id"] == crown_booking["appointment_id"]
        and item["procedure_code"] == "crown-seat"
        and item["relationship"] == "lab_return"
    )
    crown_followup_matches = client.request(
        "POST", f"/api/waitlist/{crown_followup['id']}/matches"
    )
    assert crown_followup_matches["candidates"]
    crown_seat_booking = client.request(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": crown_followup_matches["candidates"][0]["id"],
            "staff_confirms_intake": False,
        },
    )
    assert crown_seat_booking["status"] == "confirmed"

    walk_in = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Walk In",
            "medical_record_number": f"SYNTHETIC-E2E-WALKIN-{run_key}",
            "procedure_code": "emergency",
            "condition": "Urgent pain walk in",
            "date_from": today.isoformat(),
            "date_to": today.isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
            "walk_in": True,
        },
    )
    completed_walk_in = False
    if walk_in["candidates"]:
        walk_in_booking = client.request(
            "POST",
            "/api/appointments",
            {"recommendation_id": walk_in["candidates"][0]["id"], "staff_confirms_intake": True},
        )
        client.request(
            "POST", f"/api/appointments/{walk_in_booking['appointment_id']}/flow", {"action": "check_in"}
        )
        client.request(
            "POST", f"/api/appointments/{walk_in_booking['appointment_id']}/flow", {"action": "seat"}
        )
        walk_in_day = walk_in["candidates"][0]["starts_at"][:10]
        walk_in_operations = client.request("GET", f"/api/operations?day={walk_in_day}")
        walk_in_visit = next(
            item for item in walk_in_operations["appointments"]
            if item["id"] == walk_in_booking["appointment_id"]
        )
        assert walk_in_visit["arrival_type"] == "walk_in" and walk_in_visit["seated_at"]
        completed = client.request(
            "POST",
            f"/api/appointments/{walk_in_booking['appointment_id']}/status",
            {"status": "completed", "reason": "Synthetic completed workflow validation"},
        )
        assert completed["status"] == "completed"
        completed_walk_in = True

    baseline_calibration = client.request("GET", "/api/calibration")
    assert baseline_calibration["defaults_active"] is True
    assert baseline_calibration["data_required_for_scheduling"] is False
    assert baseline_calibration["automatic_observations_enabled"] is True
    assert baseline_calibration["minimum_sample_size"] == 20
    assert baseline_calibration["procedures"]
    assert all(item["active_standard_minutes"] > 0 for item in baseline_calibration["procedures"])

    calibration = client.request(
        "POST",
        "/api/calibration/import",
        {
            "source_name": "Synthetic de-identified E2E",
            "rows": [
                {
                    "procedure_code": "exam",
                    "doctor_staff_code": None,
                    "service_date": (today - timedelta(days=index + 1)).isoformat(),
                    "scheduled_minutes": 40,
                    "actual_minutes": actual,
                    "outcome": "completed",
                }
                for index, actual in enumerate((35, 40, 45, 50, 55) * 4)
            ],
        },
    )
    assert calibration["status"] == "staged" and calibration["row_count"] == 20
    assert calibration["recommendations_ready"] >= 1
    calibration_results = client.request("GET", "/api/calibration")
    assert calibration_results["auto_applied"] is False
    assert any(item["procedure_code"] == "exam" for item in calibration_results["recommendations"])

    analytics = client.request(
        "GET",
        f"/api/analytics?date_from={(today - timedelta(days=30)).isoformat()}"
        f"&date_to={(today + timedelta(days=60)).isoformat()}",
    )
    assert "chair_utilization_percent" in analytics["summary"]
    assert analytics["providers"] and analytics["procedures"]

    closed = client.request(
        "POST",
        f"/api/appointments/{appointment_id}/status",
        {"status": "cancelled", "reason": "Synthetic future cancellation validation"},
    )
    assert closed["status"] == "cancelled"

    dashboard = client.request("GET", "/api/dashboard")
    assert dashboard["metrics"]["upcoming"] >= 1
    audit = client.request("GET", "/api/audit")
    event_types = {event["event_type"] for event in audit["events"]}
    assert "appointment.confirmed" in event_types
    assert "appointment.rescheduled" in event_types
    assert "appointment.cancelled" in event_types
    assert "doctor.created" in event_types
    assert "doctor.deactivated" in event_types
    assert "doctor.reactivated" in event_types
    assert "user.deactivated" in event_types
    assert "user.reactivated" in event_types
    assert "provider.permanently_deleted" in event_types
    if completed_walk_in:
        assert "appointment.completed" in event_types
    assert "waitlist.created" in event_types

    print("live API smoke test passed")
    print(f"model source: {recommendations['intake']['source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
