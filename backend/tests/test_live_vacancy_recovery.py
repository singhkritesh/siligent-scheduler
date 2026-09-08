"""Live synthetic validation of localized cancellation vacancy recovery."""

from __future__ import annotations

import time
import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from test_live_smoke import Client, load_env


def seed_fixture(nonce: str) -> list[dict]:
    """Insert only synthetic locked visits without exercising unrelated broad search."""
    code = r'''
import json, os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from backend.config import settings
from backend.db import transaction

nonce = os.environ["RECOVERY_FIXTURE_NONCE"]
tz = ZoneInfo(settings.practice_timezone)
with transaction() as c:
    procedure = c.execute("""
        SELECT p.*,
               COALESCE((SELECT sum(t.duration_minutes) FROM procedure_phase_templates t
                          WHERE t.procedure_id = p.id AND t.active),
                        p.preparation_minutes + p.duration_minutes + p.cleanup_minutes) AS total_minutes
          FROM procedures p WHERE p.code = 'exam' AND p.active
    """).fetchone()
    actor = c.execute("SELECT id FROM app_users WHERE role = 'administrator' AND active ORDER BY created_at LIMIT 1").fetchone()
    resources = c.execute("""
        SELECT d.id AS doctor_id, pv.id AS doctor_provider_id, r.id AS room_id
          FROM doctors d
          JOIN providers pv ON pv.doctor_id = d.id AND pv.active
          JOIN doctor_procedure_qualifications q ON q.doctor_id = d.id
          CROSS JOIN rooms r
          JOIN procedure_room_eligibility re ON re.room_id = r.id
         WHERE d.active AND r.active AND q.procedure_id = %s AND re.procedure_id = %s
         ORDER BY d.display_name, r.name
    """, (procedure["id"], procedure["id"])).fetchall()
    chosen = None
    duration = timedelta(minutes=procedure["total_minutes"])
    today = datetime.now(tz).date()
    for resource in resources:
        slots = []
        for offset in range(30, 181):
            day = today + timedelta(days=offset)
            start = datetime.combine(day, time(10, 0), tzinfo=tz)
            end = start + duration
            if not c.execute("""
                SELECT 1
                  FROM provider_working_hours h
                 WHERE h.provider_id = %s AND h.weekday = %s
                   AND h.effective_from <= %s
                   AND (h.effective_through IS NULL OR h.effective_through >= %s)
                   AND h.local_start <= %s AND h.local_end >= %s
            """, (resource["doctor_provider_id"], day.weekday(), day, day, start.time(), end.time())).fetchone():
                continue
            if not c.execute("""
                SELECT 1 FROM room_working_hours h
                 WHERE h.room_id = %s AND h.weekday = %s
                   AND h.effective_from <= %s
                   AND (h.effective_through IS NULL OR h.effective_through >= %s)
                   AND h.local_start <= %s AND h.local_end >= %s
            """, (resource["room_id"], day.weekday(), day, day, start.time(), end.time())).fetchone():
                continue
            if c.execute("SELECT 1 FROM practice_closures WHERE closed_during && tstzrange(%s,%s,'[)')", (start, end)).fetchone():
                continue
            if c.execute("""
                SELECT 1 FROM appointments
                 WHERE status IN ('held','confirmed')
                   AND tstzrange(starts_at,ends_at,'[)') && tstzrange(%s,%s,'[)')
            """, (start, end)).fetchone():
                continue
            if c.execute("""
                SELECT 1 FROM provider_unavailability
                 WHERE provider_id = %s AND unavailable_during && tstzrange(%s,%s,'[)')
            """, (resource["doctor_provider_id"], start, end)).fetchone():
                continue
            if c.execute("""
                SELECT 1 FROM reserved_procedure_blocks
                 WHERE status = 'active' AND (release_at IS NULL OR release_at > transaction_timestamp())
                   AND (doctor_id = %s OR room_id = %s)
                   AND reserved_during && tstzrange(%s,%s,'[)')
            """, (resource["doctor_id"], resource["room_id"], start, end)).fetchone():
                continue
            support_ok = c.execute("""
                SELECT 1 FROM providers pv
                JOIN provider_working_hours h ON h.provider_id = pv.id
                 WHERE pv.active AND pv.role = 'assistant' AND h.weekday = %s
                   AND h.effective_from <= %s
                   AND (h.effective_through IS NULL OR h.effective_through >= %s)
                   AND h.local_start <= %s AND h.local_end >= %s
                   AND NOT EXISTS (
                       SELECT 1 FROM provider_unavailability u
                        WHERE u.provider_id = pv.id
                          AND u.unavailable_during && tstzrange(%s,%s,'[)')
                   ) LIMIT 1
            """, (day.weekday(), day, day, start.time(), end.time(), start, end)).fetchone()
            if not support_ok:
                continue
            if slots and day <= slots[-1][0].date() + timedelta(days=6):
                continue
            slots.append((start, end))
            if len(slots) == 3:
                chosen = (resource, slots)
                break
        if chosen:
            break
    if not chosen:
        raise RuntimeError("could not locate three isolated synthetic fixture slots")
    resource, slots = chosen
    result = []
    for label, (start, end) in zip(("A", "B", "C"), slots):
        patient_id = c.execute("""
            INSERT INTO patients (medical_record_number, display_name, created_by)
            VALUES (%s, %s, %s) RETURNING id
        """, (f"SYN-REC-{label}-{nonce}", f"Synthetic Recovery {label} {nonce}", actor["id"])).fetchone()["id"]
        request_id = c.execute("""
            INSERT INTO scheduling_requests (
                patient_id, procedure_id, normalized_intake, normalization_model_id,
                normalization_confidence, staff_confirmed_intake, priority,
                earliest_date, latest_date, difficulty, waitlist_consent,
                created_by, status
            ) VALUES (%s,%s,%s,'not_applicable',1,true,'routine',%s,%s,'standard',true,%s,'closed')
            RETURNING id
        """, (patient_id, procedure["id"], json.dumps({"source":"synthetic_vacancy_test"}),
              start.date(), start.date(), actor["id"])).fetchone()["id"]
        appointment_id = c.execute("""
            INSERT INTO appointments (
                scheduling_request_id, patient_id, procedure_id, doctor_id, room_id,
                starts_at, ends_at, practice_timezone, status, created_by
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'confirmed',%s) RETURNING id
        """, (request_id, patient_id, procedure["id"], resource["doctor_id"], resource["room_id"],
              start, end, settings.practice_timezone, actor["id"])).fetchone()["id"]
        result.append({"appointment_id": str(appointment_id), "starts_at": start.isoformat(),
                       "ends_at": end.isoformat(), "doctor_id": str(resource["doctor_id"]),
                       "room_id": str(resource["room_id"])})
print(json.dumps(result))
'''
    completed = subprocess.run(
        [
            "docker", "exec", "-e", f"RECOVERY_FIXTURE_NONCE={nonce}",
            "siligent-scheduler-api-1", "python", "-c", code,
        ],
        check=False, capture_output=True, text=True, timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(f"synthetic fixture failed: {completed.stderr}")
    return json.loads(completed.stdout)


def main() -> int:
    env = load_env()
    client = Client(f"https://127.0.0.1:{env.get('UI_PORT', '8443')}")
    assert client.request("GET", "/health")["status"] == "ok"
    login = client.request(
        "POST",
        "/api/auth/login",
        {
            "username": env["BOOTSTRAP_ADMIN_USERNAME"],
            "password": env["BOOTSTRAP_ADMIN_PASSWORD"],
        },
    )
    assert login["user"]["role"] == "administrator"
    catalog = client.request("GET", "/api/catalog")
    timezone = ZoneInfo(catalog["timezone"])
    nonce = str(time.time_ns())[-10:]

    fixture = seed_fixture(nonce)
    first_slot, second_slot, third_slot = fixture
    first_id = first_slot["appointment_id"]
    second_id = second_slot["appointment_id"]
    third_id = third_slot["appointment_id"]
    first_local = datetime.fromisoformat(first_slot["starts_at"]).astimezone(timezone)

    cancelled = client.request(
        "POST",
        f"/api/appointments/{first_id}/status",
        {"status": "cancelled", "reason": "Synthetic vacancy recovery validation"},
    )
    assert cancelled["vacancy_recovery_eligible"] is True
    assert datetime.fromisoformat(cancelled["released_slot"]["starts_at"]) == datetime.fromisoformat(first_slot["starts_at"])

    started = client.request("POST", f"/api/appointments/{first_id}/vacancy-recovery")
    chain = started["chain"]
    assert chain["step_count"] == 0 and chain["status"] == "active"
    assert datetime.fromisoformat(chain["current_vacancy"]["starts_at"]) == datetime.fromisoformat(first_slot["starts_at"])
    assert started["global_schedule_rerun"] is False

    preview_started = time.monotonic()
    preview = client.request("POST", f"/api/vacancy-recovery/{chain['id']}/candidates")
    assert time.monotonic() - preview_started < 5, "focused candidate preview exceeded 5 seconds"
    assert preview["global_schedule_rerun"] is False
    second_offer = next(
        candidate for candidate in preview["candidates"]
        if candidate["appointment_id"] == second_id
    )
    denied_body = {
        "offer_id": second_offer["offer_id"],
        "permission_method": "phone",
        "patient_permission_confirmed": False,
        "exact_move_acknowledged": True,
        "reason": "Synthetic permission denial must preserve the schedule",
    }
    client.expect_error(
        "POST", f"/api/vacancy-recovery/{chain['id']}/move", denied_body, 409
    )

    applied = client.request(
        "POST",
        f"/api/vacancy-recovery/{chain['id']}/move",
        {
            **denied_body,
            "patient_permission_confirmed": True,
            "reason": "Synthetic patient approved this exact earlier appointment",
        },
    )
    chain = applied["chain"]
    assert applied["moved_appointment_id"] == second_id
    assert chain["step_count"] == 1
    assert datetime.fromisoformat(chain["current_vacancy"]["starts_at"]) == datetime.fromisoformat(second_slot["starts_at"])
    assert chain["steps"][0]["appointment_id"] == second_id
    client.expect_error(
        "POST",
        f"/api/vacancy-recovery/{chain['id']}/move",
        {**denied_body, "patient_permission_confirmed": True},
        409,
    )

    first_day = first_local.date().isoformat()
    first_calendar = client.request(
        "GET", f"/api/appointments?date_from={first_day}&date_to={first_day}"
    )
    source = next(item for item in first_calendar["appointments"] if item["id"] == first_id)
    moved_second = next(item for item in first_calendar["appointments"] if item["id"] == second_id)
    assert source["status"] == "cancelled"
    assert datetime.fromisoformat(moved_second["starts_at"]) == datetime.fromisoformat(first_slot["starts_at"])

    preview_started = time.monotonic()
    second_preview = client.request(
        "POST", f"/api/vacancy-recovery/{chain['id']}/candidates"
    )
    assert time.monotonic() - preview_started < 5, "cascade continuation exceeded 5 seconds"
    third_offer = next(
        candidate for candidate in second_preview["candidates"]
        if candidate["appointment_id"] == third_id
    )
    second_applied = client.request(
        "POST",
        f"/api/vacancy-recovery/{chain['id']}/move",
        {
            "offer_id": third_offer["offer_id"],
            "permission_method": "portal",
            "patient_permission_confirmed": True,
            "exact_move_acknowledged": True,
            "reason": "Synthetic portal approval for this exact earlier appointment",
        },
    )
    chain = second_applied["chain"]
    assert chain["step_count"] == 2
    assert datetime.fromisoformat(chain["current_vacancy"]["starts_at"]) == datetime.fromisoformat(third_slot["starts_at"])
    assert [step["appointment_id"] for step in chain["steps"]] == [second_id, third_id]

    stopped = client.request(
        "POST",
        f"/api/vacancy-recovery/{chain['id']}/stop",
        {"reason": "Synthetic two-step vacancy recovery validation completed"},
    )
    assert stopped["chain"]["status"] == "stopped"
    assert stopped["chain"]["step_count"] == 2
    client.expect_error(
        "POST", f"/api/vacancy-recovery/{chain['id']}/candidates", {}, 409
    )
    stopped_calendar = client.request(
        "GET", f"/api/appointments?date_from={first_day}&date_to={first_day}"
    )
    stopped_source = next(
        item for item in stopped_calendar["appointments"] if item["id"] == first_id
    )
    assert stopped_source["vacancy_recovery_chain_id"] == chain["id"]
    assert stopped_source["vacancy_recovery_status"] == "stopped"
    reopened = client.request("POST", f"/api/appointments/{first_id}/vacancy-recovery")
    assert reopened["chain"]["id"] == chain["id"]
    assert reopened["chain"]["status"] == "stopped"

    audit = client.request("GET", "/api/audit")
    event_types = {event["event_type"] for event in audit["events"]}
    assert {
        "vacancy_recovery.started",
        "vacancy_recovery.candidates_previewed",
        "vacancy_recovery.move_applied",
        "vacancy_recovery.stopped",
    }.issubset(event_types)
    print(
        "vacancy recovery E2E passed: cancelled source preserved, two explicit moves applied, "
        "stale offer rejected, chain stopped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
