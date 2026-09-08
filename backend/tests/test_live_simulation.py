"""Authenticated CSV/XLSX simulation smoke test against the running local stack."""

from __future__ import annotations

import sys
import time as wall_time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from backend.tests.test_live_smoke import Client, load_env
from backend.tests.test_simulation_import import minimal_xlsx


def main() -> int:
    env = load_env()
    client = Client(f"https://127.0.0.1:{env.get('UI_PORT', '8443')}")
    csv_content = (
        ROOT / "data/synthetic/synthetic_appointment_requests_100.csv"
    ).read_bytes()
    anonymous = Client(client.base_url)
    anonymous.expect_file_error(
        "/api/simulations/preview",
        "synthetic-requests.csv",
        csv_content,
        "text/csv",
        401,
    )
    login = client.request(
        "POST",
        "/api/auth/login",
        {
            "username": env["BOOTSTRAP_ADMIN_USERNAME"],
            "password": env["BOOTSTRAP_ADMIN_PASSWORD"],
        },
    )
    assert login["user"]["role"] == "administrator"

    today = date.today()
    calendar_path = (
        f"/api/appointments?date_from={today.isoformat()}"
        f"&date_to={(today + timedelta(days=365)).isoformat()}"
    )
    appointments_before = client.request("GET", calendar_path)["appointments"]
    appointment_count_before = len(appointments_before)
    privacy_rejection = (
        "request_id,patient_ref,procedure_code,difficulty,priority,"
        "availability_start_date,availability_end_date,daily_start_time,"
        "daily_end_time,patient_name\n"
        f"BAD-1,BAD-PAT-1,exam,standard,routine,{(today + timedelta(days=30)).isoformat()},"
        f"{(today + timedelta(days=37)).isoformat()},08:00,17:00,Example Name\n"
    ).encode("utf-8")
    privacy_error = client.expect_file_error(
        "/api/simulations/preview",
        "contains-identifier.csv",
        privacy_rejection,
        "text/csv",
        422,
    )
    assert "Direct identifiers" in privacy_error
    preview_started = wall_time.perf_counter()
    preview = client.request_file(
        "/api/simulations/preview", "synthetic-requests.csv", csv_content, "text/csv"
    )
    assert preview["file_format"] == "csv"
    assert preview["summary"]["row_count"] == 100
    assert len(preview["preview_rows"]) == 12
    assert preview["calendar_effect"].startswith("No appointments")
    preview_seconds = wall_time.perf_counter() - preview_started

    run_started = wall_time.perf_counter()
    result = client.request_file(
        "/api/simulations/run", "synthetic-requests.csv", csv_content, "text/csv"
    )
    assert result["file_format"] == "csv"
    assert len(result["results"]) == 100
    assert result["report"]["scheduled"] + result["report"]["unscheduled"] == 100
    assert result["report"]["live_calendar_changed"] is False
    assert result["report"]["locked_appointments_moved"] == 0
    assert result["report"]["invariant_failures"] == []
    run_seconds = wall_time.perf_counter() - run_started

    xlsx_values = [
        "XLSX-REQ-1",
        "XLSX-PAT-1",
        "exam",
        "standard",
        "routine",
        (today + timedelta(days=30)).isoformat(),
        (today + timedelta(days=37)).isoformat(),
        "08:00",
        "17:00",
    ]
    xlsx_preview = client.request_file(
        "/api/simulations/preview",
        "synthetic-request.xlsx",
        minimal_xlsx(xlsx_values),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert xlsx_preview["file_format"] == "xlsx"
    assert xlsx_preview["summary"]["row_count"] == 1

    scenario_day = today + timedelta(days=45)
    while scenario_day.weekday() >= 5:
        scenario_day += timedelta(days=1)
    practice_timezone = ZoneInfo(env.get("PRACTICE_TIMEZONE", "America/New_York"))
    received_at = datetime.combine(
        scenario_day, datetime.min.time().replace(hour=14, minute=17),
        tzinfo=practice_timezone,
    )
    arrival_csv = (
        "request_id,patient_ref,request_received_at,procedure_code,difficulty,priority,"
        "availability_start_date,availability_end_date,daily_start_time,daily_end_time\n"
        f"ARRIVAL-1,ARRIVAL-PAT-1,{received_at.isoformat()},exam,standard,routine,"
        f"{scenario_day.isoformat()},{(scenario_day + timedelta(days=7)).isoformat()},"
        "08:00,17:00\n"
    ).encode("utf-8")
    arrival_result = client.request_file(
        "/api/simulations/run", "arrival-order.csv", arrival_csv, "text/csv"
    )
    assert arrival_result["report"]["scheduled"] == 1
    arrival_start = datetime.fromisoformat(arrival_result["results"][0]["starts_at"])
    assert arrival_start >= received_at
    assert arrival_result["results"][0]["booking_lead_days"] >= 0

    appointments_after = client.request("GET", calendar_path)["appointments"]
    appointment_count_after = len(appointments_after)
    assert appointment_count_after == appointment_count_before
    assert appointments_after == appointments_before
    audit = client.request("GET", "/api/audit")
    event_types = {item["event_type"] for item in audit["events"]}
    assert "simulation.previewed" in event_types
    assert "simulation.completed" in event_types
    print(
        "Live simulation smoke: PASS "
        f"(scheduled={result['report']['scheduled']}, "
        f"unscheduled={result['report']['unscheduled']}, "
        f"calendar_count={appointment_count_after}, "
        f"preview_seconds={preview_seconds:.3f}, run_seconds={run_seconds:.3f}, "
        f"engine_seconds={result['report']['runtime_seconds']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
