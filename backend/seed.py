from __future__ import annotations

from datetime import date

from .auth import create_password
from .config import settings
from .db import transaction


PROCEDURES = (
    ("exam", "Comprehensive exam", "general", 20, 10, 10, 12500),
    ("cleaning", "Dental cleaning", "general", 10, 40, 10, 17500),
    ("filling", "Composite filling", "general", 30, 10, 40, 32500),
    ("crown", "Crown preparation", "general", 60, 10, 45, 135000),
    ("crown-seat", "Crown seating / lab return", "general", 20, 10, 10, 0),
    ("root-canal", "Root canal treatment", "general", 90, 10, 15, 155000),
    ("extraction", "Dental extraction", "general", 60, 15, 15, 65000),
    ("implant", "Dental implant placement", "general", 80, 10, 30, 275000),
    ("emergency", "Emergency evaluation", "general", 30, 10, 20, 19500),
)

DOCTORS = (
    ("DR-PATEL", "Dr. Maya Patel", "general", {item[0] for item in PROCEDURES}),
    ("DR-LEE", "Dr. James Lee", "general", {item[0] for item in PROCEDURES}),
    ("DR-MARTINEZ", "Dr. Sofia Martinez", "general", {item[0] for item in PROCEDURES}),
)

ROOMS = (
    ("OP-1", "Hygiene Operatory 1", "hygiene"),
    ("OP-2", "Hygiene Operatory 2", "hygiene"),
    ("HY-3", "Hygiene Operatory 3", "hygiene"),
    ("HY-4", "Hygiene Operatory 4", "hygiene"),
    ("HY-5", "Hygiene Operatory 5", "hygiene"),
    ("EX-1", "Exam Operatory 1", "exam"),
    ("EX-2", "Exam Operatory 2", "exam"),
    ("SURG-1", "Flexible Surgical Suite", "surgical"),
)

SUPPORT_PROVIDERS = tuple(
    [(f"HYG-{number}", f"Hygienist {number}", "hygienist") for number in range(1, 6)]
    + [(f"AST-{number}", f"Dental Assistant {number}", "assistant") for number in range(1, 5)]
)

PHASES = {
    "exam": (("assistant-prep", "Room and patient preparation", "assistant", 10), ("doctor-exam", "Dentist examination", "doctor", 20), ("assistant-finish", "Checkout and turnover", "assistant", 10)),
    "cleaning": (("hygiene-care", "Hygiene care", "hygienist", 40), ("doctor-check", "Dentist hygiene examination", "doctor", 10), ("hygiene-finish", "Polish and education", "hygienist", 10)),
    "filling": (("assistant-prep", "Preparation", "assistant", 10), ("doctor-prep", "Dentist preparation", "doctor", 30), ("assistant-restore", "Restoration completion", "assistant", 30), ("turnover", "Room turnover", "room", 10)),
    "crown": (("assistant-prep", "Preparation", "assistant", 10), ("doctor-crown", "Dentist crown preparation", "doctor", 60), ("assistant-finish", "Scan, temporary and instructions", "assistant", 30), ("turnover", "Room turnover", "room", 15)),
    "crown-seat": (("assistant-prep", "Lab case preparation", "assistant", 10), ("doctor-seat", "Dentist crown seating", "doctor", 20), ("assistant-finish", "Instructions and turnover", "assistant", 10)),
    "root-canal": (("assistant-prep", "Preparation", "assistant", 10), ("doctor-treatment", "Dentist treatment", "doctor", 90), ("assistant-finish", "Closure and instructions", "assistant", 15)),
    "extraction": (("assistant-prep", "Surgical preparation", "assistant", 15), ("doctor-extraction", "Dentist extraction", "doctor", 60), ("assistant-finish", "Recovery and turnover", "assistant", 15)),
    "implant": (("assistant-prep", "Surgical preparation", "assistant", 10), ("doctor-implant", "Dentist implant placement", "doctor", 80), ("assistant-finish", "Recovery and instructions", "assistant", 20), ("turnover", "Room turnover", "room", 10)),
    "emergency": (("assistant-triage", "Assistant triage", "assistant", 10), ("doctor-evaluation", "Dentist emergency evaluation", "doctor", 30), ("assistant-finish", "Instructions and turnover", "assistant", 20)),
}


def seed_runtime() -> None:
    if not settings.bootstrap_admin_password:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be configured")

    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO practice_settings (
                singleton, practice_name, timezone, scheduling_horizon_days,
                policy_version
            ) VALUES (true, %s, %s, %s, 'mvp-2026-01')
            ON CONFLICT (singleton) DO NOTHING
            """,
            (
                settings.practice_name,
                settings.practice_timezone,
                settings.scheduling_horizon_days,
            ),
        )

        admin = connection.execute(
            "SELECT id FROM app_users WHERE external_subject = %s",
            (f"local:{settings.bootstrap_admin_username.lower()}",),
        ).fetchone()
        if not admin:
            admin = connection.execute(
                """
                INSERT INTO app_users (external_subject, display_name, role)
                VALUES (%s, 'Practice Administrator', 'administrator')
                RETURNING id
                """,
                (f"local:{settings.bootstrap_admin_username.lower()}",),
            ).fetchone()
            salt, password_hash = create_password(settings.bootstrap_admin_password)
            connection.execute(
                """
                INSERT INTO local_credentials (
                    user_id, username, password_salt, password_hash
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    admin["id"],
                    settings.bootstrap_admin_username,
                    salt,
                    password_hash,
                ),
            )

        for code, name, specialty, duration, prep, cleanup, production_cents in PROCEDURES:
            connection.execute(
                """
                INSERT INTO procedures (
                    code, name, required_specialty, duration_minutes,
                    preparation_minutes, cleanup_minutes, production_cents, policy_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'production-2026-08')
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    required_specialty = EXCLUDED.required_specialty,
                    duration_minutes = EXCLUDED.duration_minutes,
                    preparation_minutes = EXCLUDED.preparation_minutes,
                    cleanup_minutes = EXCLUDED.cleanup_minutes,
                    production_cents = EXCLUDED.production_cents,
                    policy_version = EXCLUDED.policy_version
                WHERE procedures.policy_version = 'mvp-2026-01'
                """,
                (code, name, specialty, duration, prep, cleanup, production_cents),
            )

        for staff_code, name, specialty, _ in DOCTORS:
            connection.execute(
                """
                INSERT INTO doctors (staff_code, display_name, specialty)
                VALUES (%s, %s, %s)
                ON CONFLICT (staff_code) DO NOTHING
                """,
                (staff_code, name, specialty),
            )

        for code, name, category in ROOMS:
            connection.execute(
                """
                INSERT INTO rooms (code, name, category)
                VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category
                WHERE rooms.category = 'general'
                """,
                (code, name, category),
            )

        for staff_code, name, _specialty, _codes in DOCTORS:
            doctor = connection.execute(
                "SELECT id FROM doctors WHERE staff_code = %s", (staff_code,)
            ).fetchone()
            connection.execute(
                """
                INSERT INTO providers (staff_code, display_name, role, doctor_id)
                VALUES (%s, %s, 'doctor', %s)
                ON CONFLICT (staff_code) DO NOTHING
                """,
                (staff_code, name, doctor["id"]),
            )

        for staff_code, name, role in SUPPORT_PROVIDERS:
            connection.execute(
                """
                INSERT INTO providers (staff_code, display_name, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (staff_code) DO NOTHING
                """,
                (staff_code, name, role),
            )

        effective_from = date(2025, 1, 1)
        for staff_code, _, _, procedure_codes in DOCTORS:
            doctor = connection.execute(
                "SELECT id FROM doctors WHERE staff_code = %s", (staff_code,)
            ).fetchone()
            for procedure_code in procedure_codes:
                procedure = connection.execute(
                    "SELECT id FROM procedures WHERE code = %s", (procedure_code,)
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO doctor_procedure_qualifications (
                        doctor_id, procedure_id, effective_from, approved_by
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (doctor_id, procedure_id, effective_from) DO NOTHING
                    """,
                    (doctor["id"], procedure["id"], effective_from, admin["id"]),
                )

            for weekday in range(5):
                exists = connection.execute(
                    """
                    SELECT 1 FROM doctor_working_hours
                     WHERE doctor_id = %s AND weekday = %s AND effective_from = %s
                    """,
                    (doctor["id"], weekday, effective_from),
                ).fetchone()
                if not exists:
                    connection.execute(
                        """
                        INSERT INTO doctor_working_hours (
                            doctor_id, weekday, local_start, local_end, effective_from
                        ) VALUES (%s, %s, '08:00', '17:00', %s)
                        """,
                        (doctor["id"], weekday, effective_from),
                    )

            provider = connection.execute(
                "SELECT id FROM providers WHERE doctor_id = %s", (doctor["id"],)
            ).fetchone()
            for weekday in range(5):
                connection.execute(
                    """
                    INSERT INTO provider_working_hours (
                        provider_id, weekday, local_start, local_end, effective_from
                    )
                    SELECT %s, %s, '08:00', '17:00', %s
                     WHERE NOT EXISTS (
                        SELECT 1 FROM provider_working_hours
                         WHERE provider_id = %s AND weekday = %s AND effective_from = %s
                    )
                    """,
                    (provider["id"], weekday, effective_from, provider["id"], weekday, effective_from),
                )

        support_rows = connection.execute(
            "SELECT id FROM providers WHERE role IN ('assistant', 'hygienist')"
        ).fetchall()
        for provider in support_rows:
            for weekday in range(5):
                connection.execute(
                    """
                    INSERT INTO provider_working_hours (
                        provider_id, weekday, local_start, local_end, effective_from
                    )
                    SELECT %s, %s, '08:00', '17:00', %s
                     WHERE NOT EXISTS (
                        SELECT 1 FROM provider_working_hours
                         WHERE provider_id = %s AND weekday = %s AND effective_from = %s
                    )
                    """,
                    (provider["id"], weekday, effective_from, provider["id"], weekday, effective_from),
                )

        procedures = connection.execute("SELECT id FROM procedures WHERE active").fetchall()
        rooms = connection.execute("SELECT id FROM rooms WHERE active").fetchall()
        for room in rooms:
            for procedure in procedures:
                connection.execute(
                    """
                    INSERT INTO procedure_room_eligibility (procedure_id, room_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (procedure["id"], room["id"]),
                )
            for weekday in range(5):
                exists = connection.execute(
                    """
                    SELECT 1 FROM room_working_hours
                     WHERE room_id = %s AND weekday = %s AND effective_from = %s
                    """,
                    (room["id"], weekday, effective_from),
                ).fetchone()
                if not exists:
                    connection.execute(
                        """
                        INSERT INTO room_working_hours (
                            room_id, weekday, local_start, local_end, effective_from
                        ) VALUES (%s, %s, '08:00', '17:00', %s)
                        """,
                        (room["id"], weekday, effective_from),
                    )

        for procedure_code, phases in PHASES.items():
            procedure = connection.execute(
                "SELECT id FROM procedures WHERE code = %s", (procedure_code,)
            ).fetchone()
            existing = connection.execute(
                "SELECT 1 FROM procedure_phase_templates WHERE procedure_id = %s LIMIT 1",
                (procedure["id"],),
            ).fetchone()
            if not existing:
                for sequence, (phase_code, phase_name, role, minutes) in enumerate(phases, 1):
                    connection.execute(
                        """
                        INSERT INTO procedure_phase_templates (
                            procedure_id, sequence, code, name, required_role, duration_minutes
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (procedure["id"], sequence, phase_code, phase_name, role, minutes),
                    )

        connection.execute(
            """
            UPDATE procedure_phase_templates
               SET complex_duration_minutes = CEIL(duration_minutes * 1.25 / 5.0)::integer * 5
             WHERE complex_duration_minutes IS NULL
            """
        )

        for provider in connection.execute("SELECT id, role::text AS role FROM providers").fetchall():
            target = 500000 if provider["role"] == "doctor" else 150000
            for weekday in range(5):
                connection.execute(
                    """
                    INSERT INTO provider_daily_targets (
                        provider_id, weekday, target_cents, effective_from
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (provider["id"], weekday, target, effective_from),
                )

        for procedure in connection.execute("SELECT id, code FROM procedures WHERE active").fetchall():
            shares = (("hygienist", 9000), ("doctor", 1000)) if procedure["code"] == "cleaning" else (("doctor", 10000),)
            for role, basis_points in shares:
                connection.execute(
                    """
                    INSERT INTO procedure_role_production_share (procedure_id, role, basis_points)
                    VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (procedure["id"], role, basis_points),
                )

        for weekday in range(5):
            connection.execute(
                """
                INSERT INTO emergency_capacity_rules (
                    weekday, local_start, local_end, slots_per_doctor, release_hours_before
                ) VALUES (%s, '16:00', '17:00', 2, 2)
                ON CONFLICT DO NOTHING
                """,
                (weekday,),
            )

        crown = connection.execute("SELECT id FROM procedures WHERE code = 'crown'").fetchone()
        crown_seat = connection.execute("SELECT id FROM procedures WHERE code = 'crown-seat'").fetchone()
        connection.execute(
            """
            INSERT INTO procedure_followup_rules (
                procedure_id, followup_procedure_id, minimum_days, maximum_days, reason
            ) VALUES (%s, %s, 14, 30, 'lab_return')
            ON CONFLICT DO NOTHING
            """,
            (crown["id"], crown_seat["id"]),
        )

        for code, name, quantity in (
            ("PORTABLE-XRAY", "Portable X-ray unit", 2),
            ("INTRAORAL-SCANNER", "Intraoral scanner", 1),
            ("SURGICAL-MOTOR", "Implant surgical motor", 1),
        ):
            connection.execute(
                """
                INSERT INTO equipment (code, name, quantity)
                VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING
                """,
                (code, name, quantity),
            )

        for procedure_code, equipment_code, quantity in (
            ("root-canal", "PORTABLE-XRAY", 1),
            ("crown", "INTRAORAL-SCANNER", 1),
            ("implant", "SURGICAL-MOTOR", 1),
        ):
            connection.execute(
                """
                INSERT INTO procedure_equipment_requirements (procedure_id, equipment_id, quantity)
                SELECT p.id, e.id, %s FROM procedures p, equipment e
                 WHERE p.code = %s AND e.code = %s
                ON CONFLICT DO NOTHING
                """,
                (quantity, procedure_code, equipment_code),
            )
