"""Clean-install smoke test for default-first scheduling.

Run this only against an isolated temporary stack with an empty database.
All records are visibly synthetic and the temporary database may be discarded.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from test_live_smoke import Client


def main() -> int:
    base_url = os.environ.get("CLEAN_INSTALL_BASE_URL", "https://127.0.0.1:8444")
    username = os.environ.get("CLEAN_INSTALL_USERNAME", "ootb-admin")
    password = os.environ.get("CLEAN_INSTALL_PASSWORD", "Synthetic-Clean-Install-Only-2026!")
    client = Client(base_url)

    health = client.request("GET", "/health")
    assert health == {"status": "ok", "mode": "offline"}
    client.request(
        "POST",
        "/api/auth/login",
        {"username": username, "password": password},
    )

    calibration = client.request("GET", "/api/calibration")
    assert calibration["defaults_active"] is True
    assert calibration["data_required_for_scheduling"] is False
    assert calibration["auto_applied"] is False
    assert calibration["recommendations"] == []
    assert calibration["procedures"]
    assert all(item["observed_sample_size"] == 0 for item in calibration["procedures"])
    assert all(item["calibration_status"] == "defaults_active" for item in calibration["procedures"])

    tomorrow = date.today() + timedelta(days=1)
    result = client.request(
        "POST",
        "/api/recommendations",
        {
            "patient_name": "Synthetic Clean Install Patient",
            "medical_record_number": "SYNTHETIC-CLEAN-INSTALL-001",
            "procedure_code": "exam",
            "condition": "Routine synthetic validation",
            "date_from": tomorrow.isoformat(),
            "date_to": (tomorrow + timedelta(days=21)).isoformat(),
            "time_from": "08:00:00",
            "time_to": "17:00:00",
            "preferred_doctor_id": None,
        },
    )
    assert result["candidates"], "reference defaults must produce a feasible option"
    booked = client.request(
        "POST",
        "/api/appointments",
        {
            "recommendation_id": result["candidates"][0]["id"],
            "staff_confirms_intake": True,
        },
    )
    assert booked["status"] == "confirmed" and booked["locked"] is True
    print("clean-install default-first smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
