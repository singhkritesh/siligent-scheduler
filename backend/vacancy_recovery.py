"""Localized, permission-gated recovery of one cancelled appointment vacancy."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg import Connection

from .config import settings
from .db import append_audit
from .scheduling import create_recommendations


MAX_RETURNED_CANDIDATES = 8
MAX_EXAMINED_APPOINTMENTS = 200


def serialize_chain(connection: Connection, chain_id: str) -> dict[str, object]:
    chain = connection.execute(
        """
        SELECT c.*, d.display_name AS doctor_name, r.name AS room_name,
               sa.starts_at AS source_starts_at, sa.ends_at AS source_ends_at
          FROM vacancy_recovery_chains c
          JOIN doctors d ON d.id = c.current_doctor_id
          LEFT JOIN rooms r ON r.id = c.current_room_id
          JOIN appointments sa ON sa.id = c.source_appointment_id
         WHERE c.id = %s
        """,
        (chain_id,),
    ).fetchone()
    if not chain:
        raise ValueError("Vacancy recovery chain not found")
    steps = connection.execute(
        """
        SELECT s.sequence, s.appointment_id, p.display_name AS patient_name,
               pr.name AS procedure_name, s.vacancy_starts_at, s.vacancy_ends_at,
               s.released_starts_at, s.released_ends_at, s.permission_method,
               s.moved_at
          FROM vacancy_recovery_steps s
          JOIN appointments a ON a.id = s.appointment_id
          JOIN patients p ON p.id = a.patient_id
          JOIN procedures pr ON pr.id = a.procedure_id
         WHERE s.chain_id = %s ORDER BY s.sequence
        """,
        (chain_id,),
    ).fetchall()
    return {
        "id": str(chain["id"]),
        "source_appointment_id": str(chain["source_appointment_id"]),
        "status": chain["status"],
        "version": int(chain["version"]),
        "step_count": int(chain["step_count"]),
        "current_vacancy": {
            "doctor_id": str(chain["current_doctor_id"]),
            "doctor_name": chain["doctor_name"],
            "room_id": str(chain["current_room_id"]) if chain["current_room_id"] else None,
            "room_name": chain["room_name"],
            "starts_at": chain["current_starts_at"].isoformat(),
            "ends_at": chain["current_ends_at"].isoformat(),
        },
        "steps": [
            {
                "sequence": int(step["sequence"]),
                "appointment_id": str(step["appointment_id"]),
                "patient_name": step["patient_name"],
                "procedure_name": step["procedure_name"],
                "filled_starts_at": step["vacancy_starts_at"].isoformat(),
                "filled_ends_at": step["vacancy_ends_at"].isoformat(),
                "released_starts_at": step["released_starts_at"].isoformat(),
                "released_ends_at": step["released_ends_at"].isoformat(),
                "permission_method": step["permission_method"],
                "moved_at": step["moved_at"].isoformat(),
            }
            for step in steps
        ],
        "stop_reason": chain["stop_reason"],
    }


def start_chain(
    connection: Connection,
    *,
    appointment_id: str,
    actor_id: str,
    correlation_id: str,
) -> dict[str, object]:
    existing = connection.execute(
        "SELECT id FROM vacancy_recovery_chains WHERE source_appointment_id = %s",
        (appointment_id,),
    ).fetchone()
    if existing:
        return serialize_chain(connection, str(existing["id"]))
    source = connection.execute(
        """
        SELECT id, doctor_id, room_id, starts_at, ends_at, status::text AS status,
               checked_in_at, seated_at
          FROM appointments WHERE id = %s FOR SHARE
        """,
        (appointment_id,),
    ).fetchone()
    if not source or source["status"] != "cancelled":
        raise ValueError("Only a cancelled appointment can open vacancy recovery")
    if source["room_id"] is None:
        raise ValueError("The cancelled appointment has no operatory to recover")
    if source["starts_at"] <= datetime.now(source["starts_at"].tzinfo):
        raise ValueError("Only a future cancelled appointment can open vacancy recovery")
    if source["checked_in_at"] or source["seated_at"]:
        raise ValueError("A visit that entered patient flow cannot open vacancy recovery")
    inserted = connection.execute(
        """
        INSERT INTO vacancy_recovery_chains (
            source_appointment_id, current_doctor_id, current_room_id,
            current_starts_at, current_ends_at, started_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_appointment_id) DO NOTHING
        RETURNING id
        """,
        (
            source["id"], source["doctor_id"], source["room_id"],
            source["starts_at"], source["ends_at"], actor_id,
        ),
    ).fetchone()
    if not inserted:
        existing = connection.execute(
            "SELECT id FROM vacancy_recovery_chains WHERE source_appointment_id = %s",
            (appointment_id,),
        ).fetchone()
        return serialize_chain(connection, str(existing["id"]))
    chain_id = inserted["id"]
    append_audit(
        connection,
        actor_id=actor_id,
        event_type="vacancy_recovery.started",
        entity_type="vacancy_recovery_chain",
        entity_id=str(chain_id),
        correlation_id=correlation_id,
        details={"source_appointment_id": appointment_id},
    )
    return serialize_chain(connection, str(chain_id))


def find_candidates(
    connection: Connection,
    *,
    chain_id: str,
    actor_id: str,
    correlation_id: str,
) -> dict[str, object]:
    chain = connection.execute(
        "SELECT * FROM vacancy_recovery_chains WHERE id = %s FOR UPDATE",
        (chain_id,),
    ).fetchone()
    if not chain or chain["status"] != "active":
        raise ValueError("Active vacancy recovery chain not found")
    if chain["current_starts_at"] <= datetime.now(chain["current_starts_at"].tzinfo):
        raise ValueError("The current vacancy is no longer in the future")
    if chain["current_room_id"] is None:
        raise ValueError("The current vacancy has no operatory")

    connection.execute(
        """
        UPDATE vacancy_recovery_offers SET status = 'invalidated'
         WHERE chain_id = %s AND status = 'open'
        """,
        (chain_id,),
    )
    timezone = ZoneInfo(settings.practice_timezone)
    vacancy_start = chain["current_starts_at"].astimezone(timezone)
    vacancy_end = chain["current_ends_at"].astimezone(timezone)
    candidates = connection.execute(
        """
        SELECT a.id, a.patient_id, a.procedure_id, a.doctor_id, a.room_id,
               a.starts_at, a.ends_at, a.lock_version,
               p.display_name AS patient_name,
               pr.code, pr.name, pr.duration_minutes, pr.preparation_minutes,
               pr.cleanup_minutes, pr.production_cents,
               COALESCE(sr.priority::text, 'routine') AS priority,
               COALESCE(sr.difficulty, 'standard') AS difficulty,
               COALESCE(sr.waitlist_consent, false) AS earlier_slot_opt_in
          FROM appointments a
          JOIN patients p ON p.id = a.patient_id
          JOIN procedures pr ON pr.id = a.procedure_id AND pr.active
          LEFT JOIN scheduling_requests sr ON sr.id = a.scheduling_request_id
         WHERE a.status = 'confirmed'
           AND a.room_id IS NOT NULL
           AND a.starts_at > %s
           AND a.starts_at > transaction_timestamp()
           AND a.checked_in_at IS NULL AND a.seated_at IS NULL
           AND a.id <> %s
           AND COALESCE((
               SELECT sum(
                   CASE WHEN COALESCE(sr.difficulty, 'standard') = 'complex'
                        THEN COALESCE(t.complex_duration_minutes, t.duration_minutes)
                        ELSE t.duration_minutes END
               )
                 FROM procedure_phase_templates t
                WHERE t.procedure_id = a.procedure_id AND t.active
           ), pr.preparation_minutes + pr.duration_minutes + pr.cleanup_minutes)
               <= EXTRACT(EPOCH FROM (%s - %s)) / 60
           AND NOT EXISTS (
               SELECT 1 FROM appointments patient_conflict
                WHERE patient_conflict.patient_id = a.patient_id
                  AND patient_conflict.id <> a.id
                  AND patient_conflict.status IN ('held', 'confirmed')
                  AND tstzrange(patient_conflict.starts_at, patient_conflict.ends_at, '[)')
                      && tstzrange(%s, %s, '[)')
           )
           AND EXISTS (
               SELECT 1 FROM doctor_procedure_qualifications q
                WHERE q.doctor_id = %s AND q.procedure_id = a.procedure_id
                  AND q.effective_from <= %s
                  AND (q.effective_through IS NULL OR q.effective_through >= %s)
           )
           AND EXISTS (
               SELECT 1 FROM procedure_room_eligibility e
                WHERE e.procedure_id = a.procedure_id AND e.room_id = %s
           )
         ORDER BY COALESCE(sr.waitlist_consent, false) DESC,
                  CASE COALESCE(sr.priority::text, 'routine')
                    WHEN 'urgent' THEN 0 WHEN 'priority' THEN 1 ELSE 2 END,
                  a.starts_at, a.id
         LIMIT %s
        """,
        (
            chain["current_starts_at"], chain["source_appointment_id"],
            chain["current_ends_at"], chain["current_starts_at"],
            chain["current_starts_at"], chain["current_ends_at"],
            chain["current_doctor_id"], vacancy_start.date(), vacancy_start.date(),
            chain["current_room_id"], MAX_EXAMINED_APPOINTMENTS,
        ),
    ).fetchall()

    results: list[dict[str, object]] = []
    infeasible_profiles: set[tuple[str, str]] = set()
    examined = 0
    for candidate in candidates:
        examined += 1
        profile = (str(candidate["procedure_id"]), candidate["difficulty"])
        if profile in infeasible_profiles:
            continue
        scheduling_request_id = connection.execute(
            """
            INSERT INTO scheduling_requests (
                patient_id, procedure_id, normalized_intake,
                normalization_model_id, normalization_confidence,
                staff_confirmed_intake, priority, earliest_date, latest_date,
                difficulty, waitlist_consent, created_by, status
            ) VALUES (%s, %s, %s, 'not_applicable', 1, true, %s, %s, %s,
                      %s, %s, %s, 'closed') RETURNING id
            """,
            (
                candidate["patient_id"], candidate["procedure_id"],
                json.dumps({"source": "vacancy_recovery", "chain_id": chain_id}),
                candidate["priority"], vacancy_start.date(), vacancy_start.date(),
                candidate["difficulty"], candidate["earlier_slot_opt_in"], actor_id,
            ),
        ).fetchone()["id"]
        recommendations = create_recommendations(
            connection,
            scheduling_request_id=str(scheduling_request_id),
            patient_id=str(candidate["patient_id"]),
            procedure={
                "id": candidate["procedure_id"],
                "code": candidate["code"],
                "name": candidate["name"],
                "duration_minutes": candidate["duration_minutes"],
                "preparation_minutes": candidate["preparation_minutes"],
                "cleanup_minutes": candidate["cleanup_minutes"],
                "production_cents": candidate["production_cents"],
            },
            start_date=vacancy_start.date(),
            end_date=vacancy_start.date(),
            start_time=vacancy_start.timetz().replace(tzinfo=None),
            end_time=vacancy_end.timetz().replace(tzinfo=None),
            preferred_doctor_id=str(chain["current_doctor_id"]),
            actor_id=actor_id,
            priority=candidate["priority"],
            difficulty=candidate["difficulty"],
            reschedules_appointment_id=str(candidate["id"]),
            required_doctor_id=str(chain["current_doctor_id"]),
            required_room_id=str(chain["current_room_id"]),
            required_starts_at=chain["current_starts_at"],
        )
        if not recommendations:
            # Failed exact-slot probes have no operational or audit consumer.
            # Remove the closed synthetic request to avoid unbounded preview debris.
            connection.execute(
                "DELETE FROM scheduling_requests WHERE id = %s",
                (scheduling_request_id,),
            )
            infeasible_profiles.add(profile)
            continue
        recommendation = recommendations[0]
        offer_id = connection.execute(
            """
            INSERT INTO vacancy_recovery_offers (
                chain_id, chain_version, appointment_id, recommendation_id,
                old_lock_version, old_doctor_id, old_room_id, old_starts_at, old_ends_at,
                target_doctor_id, target_room_id, target_starts_at, target_ends_at,
                created_by, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, transaction_timestamp() + interval '15 minutes')
            RETURNING id
            """,
            (
                chain_id, chain["version"], candidate["id"], recommendation["id"],
                candidate["lock_version"], candidate["doctor_id"], candidate["room_id"],
                candidate["starts_at"], candidate["ends_at"], chain["current_doctor_id"],
                chain["current_room_id"], chain["current_starts_at"],
                recommendation["ends_at"], actor_id,
            ),
        ).fetchone()["id"]
        advancement_minutes = int(
            (candidate["starts_at"] - chain["current_starts_at"]).total_seconds() // 60
        )
        results.append(
            {
                "offer_id": str(offer_id),
                "appointment_id": str(candidate["id"]),
                "patient_name": candidate["patient_name"],
                "procedure_name": candidate["name"],
                "procedure_code": candidate["code"],
                "priority": candidate["priority"],
                "earlier_slot_opt_in": bool(candidate["earlier_slot_opt_in"]),
                "current_starts_at": candidate["starts_at"].isoformat(),
                "current_ends_at": candidate["ends_at"].isoformat(),
                "proposed_starts_at": recommendation["starts_at"],
                "proposed_ends_at": recommendation["ends_at"],
                "doctor_name": recommendation["doctor_name"],
                "room_name": recommendation["room_name"],
                "advancement_minutes": advancement_minutes,
                "expires_in_minutes": 15,
            }
        )
        if len(results) >= MAX_RETURNED_CANDIDATES:
            break

    append_audit(
        connection,
        actor_id=actor_id,
        event_type="vacancy_recovery.candidates_previewed",
        entity_type="vacancy_recovery_chain",
        entity_id=chain_id,
        correlation_id=correlation_id,
        details={
            "chain_version": int(chain["version"]),
            "examined_count": examined,
            "candidate_count": len(results),
            "global_schedule_rerun": False,
        },
    )
    return {
        "chain": serialize_chain(connection, chain_id),
        "candidates": results,
        "examined_count": examined,
        "candidate_limit": MAX_RETURNED_CANDIDATES,
        "global_schedule_rerun": False,
    }


def stop_chain(
    connection: Connection,
    *,
    chain_id: str,
    actor_id: str,
    reason: str,
    correlation_id: str,
) -> dict[str, object]:
    chain = connection.execute(
        "SELECT status FROM vacancy_recovery_chains WHERE id = %s FOR UPDATE",
        (chain_id,),
    ).fetchone()
    if not chain:
        raise ValueError("Vacancy recovery chain not found")
    if chain["status"] == "active":
        connection.execute(
            """
            UPDATE vacancy_recovery_chains
               SET status = 'stopped', ended_by = %s, ended_at = transaction_timestamp(),
                   stop_reason = %s, version = version + 1
             WHERE id = %s
            """,
            (actor_id, reason.strip(), chain_id),
        )
        connection.execute(
            "UPDATE vacancy_recovery_offers SET status = 'invalidated' WHERE chain_id = %s AND status = 'open'",
            (chain_id,),
        )
        append_audit(
            connection,
            actor_id=actor_id,
            event_type="vacancy_recovery.stopped",
            entity_type="vacancy_recovery_chain",
            entity_id=chain_id,
            correlation_id=correlation_id,
            details={"reason_recorded": True},
        )
    return serialize_chain(connection, chain_id)
