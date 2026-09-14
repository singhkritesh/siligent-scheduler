from __future__ import annotations

import json
import time as sleep_time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import psycopg
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .auth import SESSION_COOKIE, authenticate, create_password, current_user, logout, require_roles
from .config import settings
from .db import append_audit, connect, run_migrations, transaction
from .intake import normalize_intake
from .scheduling import create_recommendations, daterange, local_interval
from .seed import seed_runtime
from .simulation_import import MAX_UPLOAD_BYTES, SimulationImportError, parse_simulation_upload
from .simulation_service import preview_simulation, run_simulation
from .vacancy_recovery import find_candidates as find_vacancy_candidates
from .vacancy_recovery import serialize_chain, start_chain, stop_chain

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


class TrimmedBody(BaseModel):
    """Normalize human-entered text before applying length constraints."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class PatientSearchBody(TrimmedBody):
    query: str = Field(min_length=2, max_length=160)
    limit: int = Field(default=10, ge=1, le=20)


class RecommendationBody(TrimmedBody):
    patient_name: str = Field(min_length=2, max_length=160)
    medical_record_number: str = Field(min_length=2, max_length=80)
    procedure_code: str = Field(min_length=1, max_length=80)
    condition: str = Field(default="", max_length=4000)
    patient_always_available: bool | None = None
    date_from: date | None = None
    date_to: date | None = None
    time_from: time | None = None
    time_to: time | None = None
    preferred_doctor_id: str | None = None
    difficulty: str = Field(default="standard", pattern="^(standard|complex)$")
    waitlist_consent: bool = False
    walk_in: bool = False
    allow_reserved_block_override: bool = False

    @field_validator("patient_name", "medical_record_number")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ConfirmBody(TrimmedBody):
    recommendation_id: str
    staff_confirms_intake: bool = False
    reserved_block_override_acknowledged: bool = False
    reserved_block_override_reason: str | None = Field(
        default=None, min_length=10, max_length=500
    )


class RescheduleSearchBody(TrimmedBody):
    date_from: date
    date_to: date
    time_from: time
    time_to: time
    preferred_doctor_id: str | None = None


class RescheduleApplyBody(TrimmedBody):
    recommendation_id: str
    reason: str = Field(min_length=10, max_length=500)


class VacancyRecoveryMoveBody(TrimmedBody):
    offer_id: str
    permission_method: str = Field(pattern="^(phone|sms|in_person|portal)$")
    patient_permission_confirmed: bool
    exact_move_acknowledged: bool
    reason: str = Field(min_length=10, max_length=500)


class VacancyRecoveryStopBody(TrimmedBody):
    reason: str = Field(min_length=10, max_length=500)


class AppointmentStatusBody(TrimmedBody):
    status: str = Field(pattern="^(completed|cancelled|no_show)$")
    reason: str = Field(min_length=3, max_length=500)


class WaitlistBody(TrimmedBody):
    patient_name: str = Field(min_length=2, max_length=160)
    medical_record_number: str = Field(min_length=2, max_length=80)
    procedure_code: str = Field(min_length=1, max_length=80)
    earliest_date: date
    latest_date: date
    time_from: time
    time_to: time
    preferred_doctor_id: str | None = None
    priority: str = Field(default="routine", pattern="^(routine|priority|urgent)$")
    notes: str = Field(default="", max_length=1000)


class UnavailabilityBody(TrimmedBody):
    provider_id: str
    starts_at: datetime
    ends_at: datetime
    reason_code: str = Field(min_length=3, max_length=80)


class TargetBody(TrimmedBody):
    weekday: int = Field(ge=0, le=6)
    target_cents: int = Field(ge=0, le=100_000_000)


class UserCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=2, max_length=160)
    role: str = Field(pattern="^(administrator|scheduler|clinician|auditor)$")
    password: str = Field(min_length=12, max_length=256)

    @field_validator("username", "display_name", mode="before")
    @classmethod
    def strip_identity_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class ProviderCreateBody(TrimmedBody):
    staff_code: str = Field(min_length=2, max_length=40)
    display_name: str = Field(min_length=2, max_length=160)
    role: str = Field(pattern="^(assistant|hygienist)$")


class RoomCreateBody(TrimmedBody):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(default="general", max_length=40)
    turnover_minutes: int = Field(default=10, ge=0, le=120)


class AppointmentFlowBody(TrimmedBody):
    action: str = Field(pattern="^(check_in|seat)$")


class WaitlistContactBody(TrimmedBody):
    channel: str = Field(pattern="^(phone|sms|in_person)$")
    outcome: str = Field(pattern="^(no_answer|left_message|offered|accepted|declined)$")
    incentive_offered: str = Field(default="", max_length=200)


class ShiftOverrideBody(TrimmedBody):
    provider_id: str
    shift_date: date
    status: str = Field(pattern="^(scheduled|off|cover)$")
    local_start: time | None = None
    local_end: time | None = None
    covering_for_provider_id: str | None = None
    notes: str = Field(default="", max_length=500)


class DoctorCapacityBody(TrimmedBody):
    max_active_rooms: int = Field(ge=1, le=8)


class PreferenceBody(TrimmedBody):
    provider_id: str
    procedure_code: str
    preference: int = Field(ge=-10, le=10)


class PhaseBody(TrimmedBody):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    role: str = Field(pattern="^(doctor|hygienist|assistant|room)$")
    standard_minutes: int = Field(ge=5, le=480)
    complex_minutes: int = Field(ge=5, le=600)


class ProcedurePolicyBody(TrimmedBody):
    name: str = Field(min_length=2, max_length=160)
    production_cents: int = Field(ge=0, le=100_000_000)
    phases: list[PhaseBody] = Field(min_length=1, max_length=20)


class EquipmentBody(TrimmedBody):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    quantity: int = Field(ge=1, le=100)


class EquipmentRequirementBody(TrimmedBody):
    procedure_code: str
    equipment_id: str
    quantity: int = Field(ge=0, le=20)


class ClosureBody(TrimmedBody):
    starts_at: datetime
    ends_at: datetime
    reason_code: str = Field(min_length=3, max_length=80)


class ReservedProcedureBlockBody(TrimmedBody):
    doctor_id: str
    procedure_code: str = Field(min_length=1, max_length=80)
    starts_at: datetime
    ends_at: datetime
    room_id: str | None = None
    equipment_id: str | None = None
    equipment_unit_number: int | None = Field(default=None, ge=1, le=100)
    release_at: datetime | None = None
    repeat_weekly_until: date | None = None
    reason: str = Field(min_length=3, max_length=500)


class ReservedBlockReleaseBody(TrimmedBody):
    reason: str = Field(min_length=10, max_length=500)


class HistoricalObservationBody(TrimmedBody):
    model_config = ConfigDict(extra="forbid")

    procedure_code: str
    doctor_staff_code: str | None = None
    service_date: date
    scheduled_minutes: int = Field(gt=0, le=1440)
    actual_minutes: int | None = Field(default=None, gt=0, le=1440)
    outcome: str = Field(pattern="^(completed|cancelled|no_show)$")


class HistoricalImportBody(TrimmedBody):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=2, max_length=160)
    rows: list[HistoricalObservationBody] = Field(min_length=1, max_length=5000)


class CalibrationApplyBody(TrimmedBody):
    approval_reason: str = Field(min_length=10, max_length=500)


def validate_window(date_from: date, date_to: date, time_from: time, time_to: time) -> None:
    today = datetime.now(ZoneInfo(settings.practice_timezone)).date()
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="End date must be on or after start date")
    if time_to <= time_from:
        raise HTTPException(status_code=422, detail="End time must be after start time")
    if date_to > today + timedelta(days=settings.scheduling_horizon_days + 1):
        raise HTTPException(status_code=422, detail="Search exceeds the rolling one-year horizon")


def recommendation_window(body: RecommendationBody) -> tuple[date, date, time, time, bool]:
    """Resolve the default any-opening assumption into an explicit audited window."""

    timezone = ZoneInfo(settings.practice_timezone)
    today = datetime.now(timezone).date()
    if body.walk_in:
        date_from = date_to = today
        time_from = body.time_from or time.min
        time_to = body.time_to or time(23, 59)
        uses_any_opening = False
    elif body.patient_always_available is True or (
        body.patient_always_available is None
        and all(value is None for value in (body.date_from, body.date_to, body.time_from, body.time_to))
    ):
        date_from = today
        date_to = today + timedelta(days=settings.scheduling_horizon_days)
        time_from = time.min
        time_to = time(23, 59)
        uses_any_opening = True
    else:
        if None in (body.date_from, body.date_to, body.time_from, body.time_to):
            raise HTTPException(
                status_code=422,
                detail="Custom patient availability requires both dates and both daily times",
            )
        date_from = body.date_from
        date_to = body.date_to
        time_from = body.time_from
        time_to = body.time_to
        uses_any_opening = False
    validate_window(date_from, date_to, time_from, time_to)
    return date_from, date_to, time_from, time_to, uses_any_opening


def require_aware_datetime(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=422, detail=f"{label} must include a timezone offset")


def weekly_block_occurrences(
    local_start: datetime,
    local_end: datetime,
    local_release: datetime | None,
    repeat_until: date,
) -> tuple[tuple[datetime, datetime, datetime | None], ...]:
    """Expand one local wall-clock block into exact weekly audited occurrences."""

    occurrences: list[tuple[datetime, datetime, datetime | None]] = []
    offset = 0
    while (local_start + timedelta(weeks=offset)).date() <= repeat_until:
        occurrences.append(
            (
                local_start + timedelta(weeks=offset),
                local_end + timedelta(weeks=offset),
                local_release + timedelta(weeks=offset) if local_release else None,
            )
        )
        offset += 1
    return tuple(occurrences)


def release_expired_reserved_blocks(
    connection: psycopg.Connection,
    *,
    actor_id: str,
    correlation_id: str,
) -> None:
    expired = connection.execute(
        """
        SELECT id FROM reserved_procedure_blocks
         WHERE status = 'active' AND release_at <= transaction_timestamp()
         FOR UPDATE
        """
    ).fetchall()
    for row in expired:
        connection.execute(
            "SELECT set_config('siligent.reserved_block_change_id', %s, true)",
            (str(row["id"]),),
        )
        connection.execute(
            """
            UPDATE reserved_procedure_blocks
               SET status = 'released', released_by = %s,
                   released_at = transaction_timestamp(),
                   release_reason = 'Automatic release time reached'
             WHERE id = %s
            """,
            (actor_id, row["id"]),
        )
        append_audit(
            connection,
            actor_id=actor_id,
            event_type="reserved_block.auto_released",
            entity_type="reserved_procedure_block",
            entity_id=str(row["id"]),
            correlation_id=correlation_id,
            details={"reason": "automatic_release_time"},
        )


def serialize_reserved_block(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "doctor_id": str(row["doctor_id"]),
        "doctor_name": row["doctor_name"],
        "procedure_code": row["procedure_code"],
        "procedure_name": row["procedure_name"],
        "room_id": str(row["room_id"]) if row["room_id"] else None,
        "room_name": row["room_name"],
        "equipment_id": str(row["equipment_id"]) if row["equipment_id"] else None,
        "equipment_name": row["equipment_name"],
        "equipment_unit_number": row["equipment_unit_number"],
        "starts_at": row["starts_at"].isoformat(),
        "ends_at": row["ends_at"].isoformat(),
        "release_at": row["release_at"].isoformat() if row["release_at"] else None,
        "status": row["status"],
        "reason": row["reason"],
    }


def wait_for_database() -> None:
    for _ in range(40):
        try:
            with connect() as connection:
                connection.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            sleep_time.sleep(0.5)
    raise RuntimeError("database did not become ready")


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_database()
    run_migrations()
    seed_runtime()
    yield


app = FastAPI(
    title="Siligent Scheduler",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


@app.exception_handler(psycopg.errors.InvalidTextRepresentation)
async def invalid_database_identifier(_: Request, __: Exception) -> JSONResponse:
    """Return a safe client error instead of leaking a database parsing failure."""

    return JSONResponse(status_code=422, content={"detail": "A supplied identifier is invalid"})


@app.exception_handler(psycopg.errors.ForeignKeyViolation)
async def unknown_database_reference(_: Request, __: Exception) -> JSONResponse:
    """Normalize stale or unknown linked-resource identifiers."""

    return JSONResponse(
        status_code=409,
        content={"detail": "A referenced resource no longer exists; refresh and try again"},
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        fetch_site = request.headers.get("sec-fetch-site", "same-origin")
        if fetch_site not in {"same-origin", "none"}:
            return Response(status_code=403)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health():
    with connect() as connection:
        connection.execute("SELECT 1")
    return {"status": "ok", "mode": "offline"}


async def _read_simulation_upload(file: UploadFile) -> tuple[str, list[dict[str, object]]]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        timezone = ZoneInfo(settings.practice_timezone)
        return parse_simulation_upload(
            content,
            file.filename or "",
            today=datetime.now(timezone).date(),
            horizon_days=settings.scheduling_horizon_days,
        )
    except SimulationImportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/simulations/preview")
async def simulation_preview(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    file_format, rows = await _read_simulation_upload(file)
    try:
        result = await run_in_threadpool(
            _preview_simulation_transaction, rows, file_format, str(user["id"])
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"file_format": file_format, **result}


@app.post("/api/simulations/run")
async def simulation_run(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    file_format, rows = await _read_simulation_upload(file)
    try:
        result = await run_in_threadpool(
            _run_simulation_transaction, rows, file_format, str(user["id"])
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"file_format": file_format, **result}


def _preview_simulation_transaction(
    rows: list[dict[str, object]], file_format: str, actor_id: str
) -> dict[str, object]:
    with transaction() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        result = preview_simulation(connection, rows)
        append_audit(
            connection,
            actor_id=actor_id,
            event_type="simulation.previewed",
            entity_type="simulation",
            entity_id=None,
            correlation_id=str(uuid.uuid4()),
            details={
                "row_count": len(rows),
                "file_format": file_format,
                "contains_direct_identifiers": False,
                "live_calendar_changed": False,
            },
        )
    return result


def _run_simulation_transaction(
    rows: list[dict[str, object]], file_format: str, actor_id: str
) -> dict[str, object]:
    with transaction() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        result = run_simulation(connection, rows, actor_id=actor_id)
        append_audit(
            connection,
            actor_id=actor_id,
            event_type="simulation.completed",
            entity_type="simulation",
            entity_id=None,
            correlation_id=str(uuid.uuid4()),
            outcome="failure" if result["report"]["invariant_failures"] else "success",
            details={
                "row_count": len(rows),
                "scheduled_count": result["report"]["scheduled"],
                "unscheduled_count": result["report"]["unscheduled"],
                "file_format": file_format,
                "contains_direct_identifiers": False,
                "live_calendar_changed": False,
            },
        )
    return result


@app.post("/api/auth/login")
def login_route(body: LoginBody, response: Response):
    return {"user": authenticate(body.username, body.password, response)}


@app.get("/api/auth/session")
def session_route(user: dict = Depends(current_user)):
    return {"user": user}


@app.post("/api/auth/logout", status_code=204)
def logout_route(
    response: Response,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    user: dict = Depends(current_user),
):
    logout(token, response, user)


@app.get("/api/catalog")
def catalog(user: dict = Depends(current_user)):
    with connect() as connection:
        procedures = connection.execute(
            """
            SELECT id, code, name, duration_minutes, preparation_minutes, cleanup_minutes,
                   production_cents
              FROM procedures WHERE active ORDER BY name
            """
        ).fetchall()
        doctors = connection.execute(
            "SELECT id, display_name, specialty FROM doctors WHERE active ORDER BY display_name"
        ).fetchall()
        phase_rows = connection.execute(
            """
            SELECT p.code AS procedure_code, ph.sequence, ph.name, ph.required_role,
                   ph.duration_minutes
              FROM procedure_phase_templates ph
              JOIN procedures p ON p.id = ph.procedure_id
             WHERE ph.active ORDER BY p.code, ph.sequence
            """
        ).fetchall()
        resources = connection.execute(
            """
            SELECT id, staff_code, display_name, role::text AS role, active
              FROM providers ORDER BY role, display_name
            """
        ).fetchall()
        rooms = connection.execute(
            "SELECT id, code, name, category, turnover_minutes, active FROM rooms ORDER BY name"
        ).fetchall()
    phases_by_procedure: dict[str, list[dict]] = {}
    for phase in phase_rows:
        phases_by_procedure.setdefault(phase["procedure_code"], []).append(
            {
                "sequence": phase["sequence"], "name": phase["name"],
                "role": phase["required_role"], "duration_minutes": phase["duration_minutes"],
            }
        )
    return {
        "practice_name": settings.practice_name,
        "timezone": settings.practice_timezone,
        "horizon_days": settings.scheduling_horizon_days,
        "procedures": [
            {
                **{key: value for key, value in row.items() if key != "id"},
                "phases": phases_by_procedure.get(row["code"], []),
            }
            for row in procedures
        ],
        "doctors": [
            {"id": str(row["id"]), "name": row["display_name"], "specialty": row["specialty"]}
            for row in doctors
        ],
        "providers": [
            {"id": str(row["id"]), "staff_code": row["staff_code"],
             "name": row["display_name"], "role": row["role"], "active": row["active"]}
            for row in resources
        ],
        "rooms": [
            {"id": str(row["id"]), "code": row["code"], "name": row["name"],
             "category": row["category"], "turnover_minutes": row["turnover_minutes"],
             "active": row["active"]}
            for row in rooms
        ],
        "user": user,
    }


@app.post("/api/patients/search")
def search_patients(
    body: PatientSearchBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    query = body.query.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Enter at least 2 characters to search patients")
    pattern = f"%{query}%"
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        rows = connection.execute(
            """
            SELECT p.id, p.display_name, p.medical_record_number,
                   (SELECT max(a.starts_at) FROM appointments a WHERE a.patient_id = p.id)
                       AS last_appointment_at
              FROM patients p
             WHERE p.display_name ILIKE %s OR p.medical_record_number ILIKE %s
             ORDER BY CASE WHEN lower(p.medical_record_number) = lower(%s) THEN 0 ELSE 1 END,
                      p.display_name
             LIMIT %s
            """,
            (pattern, pattern, query, body.limit),
        ).fetchall()
        append_audit(
            connection,
            actor_id=user["id"],
            event_type="patient.search",
            entity_type="patient_directory",
            entity_id=None,
            correlation_id=correlation_id,
            details={"result_count": len(rows)},
        )
    return {
        "patients": [
            {
                "id": str(row["id"]),
                "display_name": row["display_name"],
                "medical_record_number": row["medical_record_number"],
                "last_appointment_at": row["last_appointment_at"].isoformat()
                if row["last_appointment_at"]
                else None,
            }
            for row in rows
        ]
    }


@app.get("/api/dashboard")
def dashboard(
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    timezone = ZoneInfo(settings.practice_timezone)
    today = datetime.now(timezone).date()
    day_start = datetime.combine(today, time.min, tzinfo=timezone)
    day_end = day_start + timedelta(days=1)
    with connect() as connection:
        metrics = connection.execute(
            """
            SELECT
              count(*) FILTER (WHERE starts_at >= %s AND starts_at < %s AND status = 'confirmed') AS today,
              count(*) FILTER (WHERE starts_at >= transaction_timestamp() AND status = 'confirmed') AS upcoming,
              count(*) FILTER (WHERE status = 'held') AS holds
            FROM appointments
            """,
            (day_start, day_end),
        ).fetchone()
        pending = connection.execute(
            "SELECT count(*) AS count FROM scheduling_requests WHERE status = 'pending'"
        ).fetchone()["count"]
        waitlist = connection.execute(
            "SELECT count(*) AS count FROM waitlist_entries WHERE status = 'active'"
        ).fetchone()["count"]
        production = connection.execute(
            """
            SELECT COALESCE(sum(c.amount_cents), 0) AS amount
              FROM appointment_production_credits c
              JOIN appointments a ON a.id = c.appointment_id
             WHERE a.starts_at >= %s AND a.starts_at < %s
               AND a.status IN ('confirmed', 'completed')
            """,
            (day_start, day_end),
        ).fetchone()["amount"]
        next_appointments = connection.execute(
            """
            SELECT a.id, a.starts_at, a.ends_at, a.status::text AS status,
                   p.display_name AS patient_name, pr.name AS procedure_name,
                   d.display_name AS doctor_name, r.name AS room_name
              FROM appointments a
              JOIN patients p ON p.id = a.patient_id
              JOIN procedures pr ON pr.id = a.procedure_id
              JOIN doctors d ON d.id = a.doctor_id
              LEFT JOIN rooms r ON r.id = a.room_id
             WHERE a.status = 'confirmed' AND a.ends_at >= transaction_timestamp()
             ORDER BY a.starts_at
             LIMIT 8
            """
        ).fetchall()
    return {
        "metrics": {
            "today": metrics["today"],
            "upcoming": metrics["upcoming"],
            "pending": pending,
            "holds": metrics["holds"],
            "waitlist": waitlist,
            "production_cents": production,
        },
        "upcoming": [serialize_appointment(row) for row in next_appointments],
        "user": user,
    }


def serialize_appointment(row: dict) -> dict:
    result = {
        "id": str(row["id"]),
        "starts_at": row["starts_at"].isoformat(),
        "ends_at": row["ends_at"].isoformat(),
        "status": row["status"],
        "patient_name": row["patient_name"],
        "procedure_name": row["procedure_name"],
        "doctor_name": row["doctor_name"],
        "room_name": row["room_name"],
    }
    for key in (
        "arrival_type", "checked_in_at", "seated_at", "completed_at",
        "vacancy_recovery_chain_id", "vacancy_recovery_status",
    ):
        if key in row:
            value = row[key]
            result[key] = (
                value.isoformat() if isinstance(value, datetime)
                else str(value) if key == "vacancy_recovery_chain_id" and value
                else value
            )
    return result


def persist_phase_plan(
    connection: psycopg.Connection,
    appointment_id: str,
    phase_plan: list[dict] | str,
    appointment_start: datetime,
    appointment_end: datetime,
) -> None:
    phases = json.loads(phase_plan) if isinstance(phase_plan, str) else phase_plan
    if not phases:
        raise HTTPException(status_code=409, detail="Recommendation has no clinical phase plan")
    last_end = appointment_start
    for index, phase in enumerate(phases, 1):
        starts_at = datetime.fromisoformat(phase["starts_at"])
        ends_at = datetime.fromisoformat(phase["ends_at"])
        if starts_at != last_end or ends_at <= starts_at or ends_at > appointment_end:
            raise HTTPException(status_code=409, detail="Recommendation phase plan is invalid")
        connection.execute(
            """
            INSERT INTO appointment_phases (
                appointment_id, sequence, phase_code, phase_name, role,
                provider_id, starts_at, ends_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                appointment_id, index, phase["code"], phase["name"], phase["role"],
                phase.get("provider_id"), starts_at, ends_at,
            ),
        )
        last_end = ends_at
    if last_end != appointment_end:
        raise HTTPException(status_code=409, detail="Recommendation phases do not cover the visit")


def persist_equipment_plan(
    connection: psycopg.Connection,
    appointment_id: str,
    equipment_plan: list[dict] | str,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    plan = json.loads(equipment_plan) if isinstance(equipment_plan, str) else equipment_plan
    counts: dict[str, int] = {}
    for item in plan:
        equipment_id = str(item["equipment_id"])
        unit_number = int(item["unit_number"])
        equipment = connection.execute(
            "SELECT quantity FROM equipment WHERE id = %s AND active",
            (equipment_id,),
        ).fetchone()
        if not equipment or unit_number < 1 or unit_number > equipment["quantity"]:
            raise HTTPException(status_code=409, detail="Equipment configuration changed; search again")
        connection.execute(
            """
            INSERT INTO appointment_equipment_reservations (
                appointment_id, equipment_id, unit_number, starts_at, ends_at
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (appointment_id, equipment_id, unit_number, starts_at, ends_at),
        )
        counts[equipment_id] = counts.get(equipment_id, 0) + 1
    for equipment_id, quantity in counts.items():
        connection.execute(
            """
            INSERT INTO appointment_equipment (appointment_id, equipment_id, quantity)
            VALUES (%s, %s, %s)
            ON CONFLICT (appointment_id, equipment_id)
            DO UPDATE SET quantity = EXCLUDED.quantity
            """,
            (appointment_id, equipment_id, quantity),
        )


def refresh_production_credits(
    connection: psycopg.Connection,
    appointment_id: str,
    procedure_id: str,
    production_cents: int,
) -> None:
    connection.execute(
        "DELETE FROM appointment_production_credits WHERE appointment_id = %s",
        (appointment_id,),
    )
    shares = connection.execute(
        """
        SELECT role::text AS role, basis_points
          FROM procedure_role_production_share WHERE procedure_id = %s
        """,
        (procedure_id,),
    ).fetchall()
    for share in shares:
        provider = connection.execute(
            """
            SELECT provider_id FROM appointment_phases
             WHERE appointment_id = %s AND role = %s AND provider_id IS NOT NULL
             ORDER BY sequence LIMIT 1
            """,
            (appointment_id, share["role"]),
        ).fetchone()
        if provider:
            connection.execute(
                """
                INSERT INTO appointment_production_credits (
                    appointment_id, provider_id, amount_cents
                ) VALUES (%s, %s, %s)
                ON CONFLICT (appointment_id, provider_id) DO UPDATE
                    SET amount_cents = appointment_production_credits.amount_cents + EXCLUDED.amount_cents
                """,
                (
                    appointment_id, provider["provider_id"],
                    production_cents * share["basis_points"] // 10000,
                ),
            )


@app.get("/api/appointments")
def list_appointments(
    date_from: date,
    date_to: date,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    if date_to < date_from or (date_to - date_from).days > settings.scheduling_horizon_days:
        raise HTTPException(status_code=422, detail="Invalid calendar range")
    timezone = ZoneInfo(settings.practice_timezone)
    range_start = datetime.combine(date_from, time.min, tzinfo=timezone)
    range_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone)
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        rows = connection.execute(
            """
            SELECT a.id, a.starts_at, a.ends_at, a.status::text AS status,
                   a.arrival_type, a.checked_in_at, a.seated_at, a.completed_at,
                   p.display_name AS patient_name, pr.name AS procedure_name,
                   d.display_name AS doctor_name, r.name AS room_name,
                   vc.id AS vacancy_recovery_chain_id,
                   vc.status AS vacancy_recovery_status
              FROM appointments a
              JOIN patients p ON p.id = a.patient_id
              JOIN procedures pr ON pr.id = a.procedure_id
              JOIN doctors d ON d.id = a.doctor_id
              LEFT JOIN rooms r ON r.id = a.room_id
              LEFT JOIN vacancy_recovery_chains vc ON vc.source_appointment_id = a.id
             WHERE a.starts_at < %s
               AND a.ends_at >= %s
               AND a.status IN ('confirmed', 'completed', 'cancelled', 'no_show')
             ORDER BY a.starts_at
            """,
            (range_end, range_start),
        ).fetchall()
        append_audit(
            connection,
            actor_id=user["id"],
            event_type="appointment.calendar_view",
            entity_type="calendar",
            entity_id=None,
            correlation_id=correlation_id,
            details={"range_days": (date_to - date_from).days + 1},
        )
    return {"appointments": [serialize_appointment(row) for row in rows]}


@app.post("/api/recommendations")
def recommendations(
    body: RecommendationBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    date_from, date_to, time_from, time_to, uses_any_opening = recommendation_window(body)
    if body.allow_reserved_block_override and user["role"] not in {"administrator", "clinician"}:
        raise HTTPException(
            status_code=403,
            detail="Reserved-block override searches require an administrator or clinician",
        )
    intake = normalize_intake(body.condition, body.procedure_code)
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        release_expired_reserved_blocks(
            connection, actor_id=user["id"], correlation_id=correlation_id
        )
        procedure = connection.execute(
            """
            SELECT id, code, name, duration_minutes, preparation_minutes, cleanup_minutes,
                   production_cents
              FROM procedures WHERE code = %s AND active
            """,
            (body.procedure_code,),
        ).fetchone()
        if not procedure:
            raise HTTPException(status_code=404, detail="Procedure not found")
        patient = connection.execute(
            "SELECT id FROM patients WHERE medical_record_number = %s",
            (body.medical_record_number,),
        ).fetchone()
        if patient:
            patient_id = patient["id"]
            connection.execute(
                "UPDATE patients SET display_name = %s WHERE id = %s",
                (body.patient_name, patient_id),
            )
        else:
            patient_id = connection.execute(
                """
                INSERT INTO patients (medical_record_number, display_name, created_by)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (body.medical_record_number, body.patient_name, user["id"]),
            ).fetchone()["id"]
        request_id = connection.execute(
            """
            INSERT INTO scheduling_requests (
                patient_id, procedure_id, condition_summary, normalized_intake,
                normalization_model_id, normalization_confidence,
                staff_confirmed_intake, priority, earliest_date, latest_date,
                difficulty, waitlist_consent, walk_in, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, false, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                patient_id,
                procedure["id"],
                body.condition.strip() or None,
                json.dumps({"tags": intake.tags}),
                intake.source,
                intake.confidence,
                intake.priority,
                date_from,
                date_to,
                body.difficulty,
                body.waitlist_consent,
                body.walk_in,
                user["id"],
            ),
        ).fetchone()["id"]
        timezone = ZoneInfo(settings.practice_timezone)
        for day in daterange(date_from, date_to):
            interval = local_interval(day, time_from, time_to, timezone)
            connection.execute(
                "INSERT INTO patient_availability (scheduling_request_id, available_during) VALUES (%s, tstzrange(%s, %s, '[)'))",
                (request_id, interval.start, interval.end),
            )
        candidates = create_recommendations(
            connection,
            scheduling_request_id=str(request_id),
            patient_id=str(patient_id),
            procedure=procedure,
            start_date=date_from,
            end_date=date_to,
            start_time=time_from,
            end_time=time_to,
            preferred_doctor_id=body.preferred_doctor_id,
            actor_id=user["id"],
            priority=intake.priority,
            difficulty=body.difficulty,
            allow_reserved_block_override=body.allow_reserved_block_override,
        )
        attendance = connection.execute(
            """
            SELECT count(*) FILTER (WHERE status IN ('completed', 'cancelled', 'no_show')) AS resolved,
                   count(*) FILTER (WHERE status = 'no_show') AS no_shows
              FROM appointments WHERE patient_id = %s
            """,
            (patient_id,),
        ).fetchone()
        resolved_visits = int(attendance["resolved"])
        no_show_risk = round((int(attendance["no_shows"]) + 1) / (resolved_visits + 4), 3)
        if not candidates and body.waitlist_consent:
            connection.execute(
                """
                INSERT INTO waitlist_entries (
                    patient_id, procedure_id, preferred_doctor_id, earliest_date,
                    latest_date, local_start, local_end, priority, notes, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    patient_id, procedure["id"], body.preferred_doctor_id,
                    date_from, date_to, time_from, time_to,
                    intake.priority, "Added automatically after no feasible slot", user["id"],
                ),
            )
        append_audit(
            connection,
            actor_id=user["id"],
            event_type="scheduling.recommendations_generated",
            entity_type="scheduling_request",
            entity_id=str(request_id),
            correlation_id=correlation_id,
            details={
                "candidate_count": len(candidates),
                "model_source": intake.source,
                "patient_always_available": uses_any_opening,
                "reserved_block_override_search": body.allow_reserved_block_override,
            },
        )
    return {
        "request_id": str(request_id),
        "availability_assumption": "any_opening" if uses_any_opening else "custom_window",
        "intake": {
            "tags": intake.tags,
            "priority": intake.priority,
            "source": intake.source,
            "confidence": intake.confidence,
            "requires_staff_confirmation": bool(body.condition.strip()),
            "attendance_risk": {
                "probability": no_show_risk,
                "basis": "smoothed local attendance history",
                "resolved_visits": resolved_visits,
                "staff_action": "confirm contact details and consider the ASAP list" if no_show_risk >= 0.35 else "standard confirmation workflow",
            },
        },
        "candidates": candidates,
    }


@app.post("/api/appointments", status_code=201)
def confirm_appointment(
    body: ConfirmBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    correlation_id = str(uuid.uuid4())
    try:
        with transaction() as connection:
            recommendation = connection.execute(
                """
                SELECT rs.*, sr.patient_id, sr.procedure_id,
                       sr.condition_summary, sr.staff_confirmed_intake,
                       sr.source_waitlist_id, sr.walk_in
                  FROM recommendation_snapshots rs
                  JOIN scheduling_requests sr ON sr.id = rs.scheduling_request_id
                 WHERE rs.id = %s AND rs.consumed_at IS NULL
                   AND rs.expires_at > transaction_timestamp()
                   AND rs.reschedules_appointment_id IS NULL
                 FOR UPDATE
                """,
                (body.recommendation_id,),
            ).fetchone()
            if not recommendation:
                raise HTTPException(status_code=409, detail="Recommendation expired or unavailable")
            if (
                recommendation["condition_summary"]
                and not recommendation["staff_confirmed_intake"]
                and not body.staff_confirms_intake
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Review and confirm the locally normalized intake before booking",
                )
            qualified = connection.execute(
                """
                SELECT 1 FROM doctor_procedure_qualifications
                 WHERE doctor_id = %s AND procedure_id = %s
                   AND effective_from <= %s::date
                   AND (effective_through IS NULL OR effective_through >= %s::date)
                """,
                (
                    recommendation["doctor_id"], recommendation["procedure_id"],
                    recommendation["starts_at"], recommendation["starts_at"],
                ),
            ).fetchone()
            if not qualified:
                raise HTTPException(status_code=409, detail="Doctor qualification changed; search again")
            conflict_payload = recommendation["reserved_block_conflicts"]
            stored_conflicts = (
                json.loads(conflict_payload)
                if isinstance(conflict_payload, str)
                else list(conflict_payload)
            )
            active_conflicts = []
            if stored_conflicts:
                active_conflicts = connection.execute(
                    """
                    SELECT id FROM reserved_procedure_blocks
                     WHERE id = ANY(%s::uuid[]) AND status = 'active'
                       AND (release_at IS NULL OR release_at > transaction_timestamp())
                     FOR UPDATE
                    """,
                    (stored_conflicts,),
                ).fetchall()
            override_permission_ids: list[str] = []
            if active_conflicts:
                if user["role"] not in {"administrator", "clinician"}:
                    raise HTTPException(
                        status_code=403,
                        detail="Reserved-block overrides require an administrator or clinician",
                    )
                if (
                    not body.reserved_block_override_acknowledged
                    or not body.reserved_block_override_reason
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="A reason and explicit acknowledgement are required to override the reserved block",
                    )
                for conflict in active_conflicts:
                    permission_id = connection.execute(
                        """
                        INSERT INTO reserved_block_override_permissions (
                            block_id, recommendation_id, scheduling_request_id,
                            doctor_id, procedure_id, room_id, starts_at, ends_at,
                            granted_by, reason, expires_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  transaction_timestamp() + interval '2 minutes')
                        RETURNING id
                        """,
                        (
                            conflict["id"], recommendation["id"],
                            recommendation["scheduling_request_id"],
                            recommendation["doctor_id"], recommendation["procedure_id"],
                            recommendation["room_id"], recommendation["starts_at"],
                            recommendation["ends_at"], user["id"],
                            body.reserved_block_override_reason.strip(),
                        ),
                    ).fetchone()["id"]
                    override_permission_ids.append(str(permission_id))
                    append_audit(
                        connection,
                        actor_id=user["id"],
                        event_type="reserved_block.override_authorized",
                        entity_type="reserved_procedure_block",
                        entity_id=str(conflict["id"]),
                        correlation_id=correlation_id,
                        details={
                            "recommendation_id": body.recommendation_id,
                            "reason_recorded": True,
                        },
                    )
                connection.execute(
                    "SELECT set_config('siligent.reserved_block_override_permission_ids', %s, true)",
                    (",".join(override_permission_ids),),
                )
            appointment_id = connection.execute(
                """
                INSERT INTO appointments (
                    scheduling_request_id, patient_id, procedure_id, doctor_id,
                    room_id, starts_at, ends_at, practice_timezone, status, arrival_type,
                    created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', %s, %s)
                RETURNING id
                """,
                (
                    recommendation["scheduling_request_id"],
                    recommendation["patient_id"],
                    recommendation["procedure_id"],
                    recommendation["doctor_id"],
                    recommendation["room_id"],
                    recommendation["starts_at"],
                    recommendation["ends_at"],
                    settings.practice_timezone,
                    "walk_in" if recommendation["walk_in"] else "scheduled",
                    user["id"],
                ),
            ).fetchone()["id"]
            persist_phase_plan(
                connection,
                str(appointment_id),
                recommendation["phase_plan"],
                recommendation["starts_at"],
                recommendation["ends_at"],
            )
            persist_equipment_plan(
                connection,
                str(appointment_id),
                recommendation["equipment_plan"],
                recommendation["starts_at"],
                recommendation["ends_at"],
            )
            fulfilled_blocks = connection.execute(
                """
                SELECT b.id FROM reserved_procedure_blocks b
                 WHERE b.status = 'active'
                   AND (b.release_at IS NULL OR b.release_at > transaction_timestamp())
                   AND b.doctor_id = %s AND b.procedure_id = %s
                   AND b.reserved_during @> tstzrange(%s, %s, '[)')
                   AND (b.room_id IS NULL OR b.room_id = %s)
                   AND (
                       b.equipment_id IS NULL OR EXISTS (
                           SELECT 1 FROM appointment_equipment_reservations er
                            WHERE er.appointment_id = %s
                              AND er.equipment_id = b.equipment_id
                              AND er.unit_number = b.equipment_unit_number
                       )
                   )
                 FOR UPDATE
                """,
                (
                    recommendation["doctor_id"], recommendation["procedure_id"],
                    recommendation["starts_at"], recommendation["ends_at"],
                    recommendation["room_id"], appointment_id,
                ),
            ).fetchall()
            for block in fulfilled_blocks:
                connection.execute(
                    "SELECT set_config('siligent.reserved_block_change_id', %s, true)",
                    (str(block["id"]),),
                )
                connection.execute(
                    """
                    UPDATE reserved_procedure_blocks
                       SET status = 'fulfilled', fulfilled_by_appointment_id = %s
                     WHERE id = %s
                    """,
                    (appointment_id, block["id"]),
                )
                append_audit(
                    connection,
                    actor_id=user["id"],
                    event_type="reserved_block.fulfilled",
                    entity_type="reserved_procedure_block",
                    entity_id=str(block["id"]),
                    correlation_id=correlation_id,
                    details={"appointment_id": str(appointment_id)},
                )
            refresh_production_credits(
                connection,
                str(appointment_id),
                str(recommendation["procedure_id"]),
                recommendation["production_cents"],
            )
            if recommendation["source_waitlist_id"]:
                source_waitlist = connection.execute(
                    """
                    SELECT w.predecessor_appointment_id, w.relationship,
                           w.earliest_date - (a.starts_at AT TIME ZONE %s)::date AS minimum_days,
                           w.latest_date - (a.starts_at AT TIME ZONE %s)::date AS maximum_days
                      FROM waitlist_entries w
                      JOIN appointments a ON a.id = w.predecessor_appointment_id
                     WHERE w.id = %s
                    """,
                    (
                        settings.practice_timezone, settings.practice_timezone,
                        recommendation["source_waitlist_id"],
                    ),
                ).fetchone()
                if source_waitlist and source_waitlist["predecessor_appointment_id"]:
                    connection.execute(
                        """
                        INSERT INTO appointment_links (
                            predecessor_id, successor_id, relationship, minimum_days, maximum_days
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            source_waitlist["predecessor_appointment_id"], appointment_id,
                            source_waitlist["relationship"], source_waitlist["minimum_days"] or 0,
                            source_waitlist["maximum_days"],
                        ),
                    )

            followup_rules = connection.execute(
                """
                SELECT followup_procedure_id, minimum_days, maximum_days, reason
                  FROM procedure_followup_rules WHERE procedure_id = %s
                """,
                (recommendation["procedure_id"],),
            ).fetchall()
            visit_date = recommendation["starts_at"].astimezone(
                ZoneInfo(settings.practice_timezone)
            ).date()
            for rule in followup_rules:
                connection.execute(
                    """
                    INSERT INTO waitlist_entries (
                        patient_id, procedure_id, preferred_doctor_id,
                        earliest_date, latest_date, local_start, local_end,
                        priority, notes, created_by, predecessor_appointment_id, relationship
                    ) VALUES (%s, %s, %s, %s, %s, '08:00', '17:00',
                              'routine', NULL, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        recommendation["patient_id"], rule["followup_procedure_id"],
                        recommendation["doctor_id"],
                        visit_date + timedelta(days=rule["minimum_days"]),
                        visit_date + timedelta(days=rule["maximum_days"]),
                        user["id"], appointment_id, rule["reason"],
                    ),
                )
            connection.execute(
                "UPDATE recommendation_snapshots SET consumed_at = transaction_timestamp() WHERE id = %s",
                (recommendation["id"],),
            )
            connection.execute(
                "UPDATE scheduling_requests SET status = 'scheduled' WHERE id = %s",
                (recommendation["scheduling_request_id"],),
            )
            connection.execute(
                """
                UPDATE waitlist_entries SET status = 'scheduled', updated_at = transaction_timestamp()
                 WHERE id = (
                    SELECT source_waitlist_id FROM scheduling_requests WHERE id = %s
                 )
                """,
                (recommendation["scheduling_request_id"],),
            )
            if body.staff_confirms_intake:
                connection.execute(
                    "UPDATE scheduling_requests SET staff_confirmed_intake = true WHERE id = %s",
                    (recommendation["scheduling_request_id"],),
                )
            connection.execute(
                """
                INSERT INTO appointment_status_history (
                    appointment_id, previous_status, new_status, actor_id, reason_code
                ) VALUES (%s, NULL, 'confirmed', %s, 'recommendation_confirmed')
                """,
                (appointment_id, user["id"]),
            )
            append_audit(
                connection,
                actor_id=user["id"],
                event_type="appointment.confirmed",
                entity_type="appointment",
                entity_id=str(appointment_id),
                correlation_id=correlation_id,
                details={
                    "recommendation_id": body.recommendation_id,
                    "intake_confirmed": body.staff_confirms_intake,
                },
            )
    except psycopg.errors.ExclusionViolation as exc:
        raise HTTPException(status_code=409, detail="The slot was just taken; search again") from exc
    except psycopg.errors.RaiseException as exc:
        raise HTTPException(status_code=409, detail=str(exc).splitlines()[0]) from exc
    return {"appointment_id": str(appointment_id), "status": "confirmed", "locked": True}


@app.post("/api/appointments/{appointment_id}/reschedule-options")
def reschedule_options(
    appointment_id: str,
    body: RescheduleSearchBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    validate_window(body.date_from, body.date_to, body.time_from, body.time_to)
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        appointment = connection.execute(
            """
            SELECT a.*, p.display_name AS patient_name, p.medical_record_number,
                   pr.code, pr.name, pr.duration_minutes,
                   pr.preparation_minutes, pr.cleanup_minutes, pr.production_cents
              FROM appointments a
              JOIN patients p ON p.id = a.patient_id
              JOIN procedures pr ON pr.id = a.procedure_id
             WHERE a.id = %s AND a.status = 'confirmed'
            """,
            (appointment_id,),
        ).fetchone()
        if not appointment:
            raise HTTPException(status_code=404, detail="Confirmed appointment not found")
        request_id = connection.execute(
            """
            INSERT INTO scheduling_requests (
                patient_id, procedure_id, normalized_intake,
                normalization_model_id, normalization_confidence,
                staff_confirmed_intake, priority, earliest_date, latest_date,
                created_by
            ) VALUES (%s, %s, '{"source":"reschedule"}', 'not_applicable', 1,
                      true, 'routine', %s, %s, %s)
            RETURNING id
            """,
            (
                appointment["patient_id"], appointment["procedure_id"],
                body.date_from, body.date_to, user["id"],
            ),
        ).fetchone()["id"]
        candidates = create_recommendations(
            connection,
            scheduling_request_id=str(request_id),
            patient_id=str(appointment["patient_id"]),
            procedure={
                "id": appointment["procedure_id"],
                "code": appointment["code"],
                "name": appointment["name"],
                "duration_minutes": appointment["duration_minutes"],
                "preparation_minutes": appointment["preparation_minutes"],
                "cleanup_minutes": appointment["cleanup_minutes"],
                "production_cents": appointment["production_cents"],
            },
            start_date=body.date_from,
            end_date=body.date_to,
            start_time=body.time_from,
            end_time=body.time_to,
            preferred_doctor_id=body.preferred_doctor_id,
            actor_id=user["id"],
            reschedules_appointment_id=appointment_id,
            priority="routine",
        )
        append_audit(
            connection,
            actor_id=user["id"],
            event_type="appointment.reschedule_previewed",
            entity_type="appointment",
            entity_id=appointment_id,
            correlation_id=correlation_id,
            details={"candidate_count": len(candidates)},
        )
    return {"candidates": candidates, "appointment_id": appointment_id}


def _execute_reschedule(
    connection: psycopg.Connection,
    *,
    appointment_id: str,
    recommendation_id: str,
    actor_id: str,
    reason: str,
    correlation_id: str,
    audit_source: str = "manual",
) -> tuple[dict, dict, str]:
    current = connection.execute(
        "SELECT * FROM appointments WHERE id = %s AND status = 'confirmed' FOR UPDATE",
        (appointment_id,),
    ).fetchone()
    recommendation = connection.execute(
        """
        SELECT * FROM recommendation_snapshots
         WHERE id = %s AND reschedules_appointment_id = %s
           AND consumed_at IS NULL AND expires_at > transaction_timestamp()
         FOR UPDATE
        """,
        (recommendation_id, appointment_id),
    ).fetchone()
    if not current or not recommendation:
        raise HTTPException(status_code=409, detail="Reschedule option expired or unavailable")
    permission_id = connection.execute(
        """
        INSERT INTO reschedule_permissions (
            appointment_id, old_doctor_id, new_doctor_id,
            old_room_id, new_room_id, old_starts_at, old_ends_at,
            new_starts_at, new_ends_at, granted_by, reason, expires_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  transaction_timestamp() + interval '2 minutes')
        RETURNING id
        """,
        (
            appointment_id, current["doctor_id"], recommendation["doctor_id"],
            current["room_id"], recommendation["room_id"], current["starts_at"],
            current["ends_at"], recommendation["starts_at"], recommendation["ends_at"],
            actor_id, reason.strip(),
        ),
    ).fetchone()["id"]
    connection.execute(
        "SELECT set_config('siligent.reschedule_permission_id', %s, true)",
        (str(permission_id),),
    )
    connection.execute(
        """
        UPDATE appointments
           SET doctor_id = %s, room_id = %s, starts_at = %s, ends_at = %s
         WHERE id = %s
        """,
        (
            recommendation["doctor_id"], recommendation["room_id"],
            recommendation["starts_at"], recommendation["ends_at"], appointment_id,
        ),
    )
    connection.execute("DELETE FROM appointment_phases WHERE appointment_id = %s", (appointment_id,))
    connection.execute(
        "DELETE FROM appointment_equipment_reservations WHERE appointment_id = %s",
        (appointment_id,),
    )
    connection.execute("DELETE FROM appointment_equipment WHERE appointment_id = %s", (appointment_id,))
    persist_phase_plan(
        connection, appointment_id, recommendation["phase_plan"],
        recommendation["starts_at"], recommendation["ends_at"],
    )
    persist_equipment_plan(
        connection, appointment_id, recommendation["equipment_plan"],
        recommendation["starts_at"], recommendation["ends_at"],
    )
    fulfilled_blocks = connection.execute(
        """
        SELECT b.id FROM reserved_procedure_blocks b
         WHERE b.status = 'active'
           AND (b.release_at IS NULL OR b.release_at > transaction_timestamp())
           AND b.doctor_id = %s AND b.procedure_id = %s
           AND b.reserved_during @> tstzrange(%s, %s, '[)')
           AND (b.room_id IS NULL OR b.room_id = %s)
           AND (
               b.equipment_id IS NULL OR EXISTS (
                   SELECT 1 FROM appointment_equipment_reservations er
                    WHERE er.appointment_id = %s
                      AND er.equipment_id = b.equipment_id
                      AND er.unit_number = b.equipment_unit_number
               )
           )
         FOR UPDATE
        """,
        (
            recommendation["doctor_id"], current["procedure_id"],
            recommendation["starts_at"], recommendation["ends_at"],
            recommendation["room_id"], appointment_id,
        ),
    ).fetchall()
    for block in fulfilled_blocks:
        connection.execute(
            "SELECT set_config('siligent.reserved_block_change_id', %s, true)",
            (str(block["id"]),),
        )
        connection.execute(
            """
            UPDATE reserved_procedure_blocks
               SET status = 'fulfilled', fulfilled_by_appointment_id = %s
             WHERE id = %s
            """,
            (appointment_id, block["id"]),
        )
        append_audit(
            connection, actor_id=actor_id, event_type="reserved_block.fulfilled",
            entity_type="reserved_procedure_block", entity_id=str(block["id"]),
            correlation_id=correlation_id,
            details={"appointment_id": appointment_id, "source": "reschedule"},
        )
    refresh_production_credits(
        connection, appointment_id, str(current["procedure_id"]),
        recommendation["production_cents"],
    )
    connection.execute(
        "UPDATE recommendation_snapshots SET consumed_at = transaction_timestamp() WHERE id = %s",
        (recommendation["id"],),
    )
    append_audit(
        connection, actor_id=actor_id, event_type="appointment.rescheduled",
        entity_type="appointment", entity_id=appointment_id,
        correlation_id=correlation_id,
        details={
            "permission_id": str(permission_id),
            "recommendation_id": recommendation_id,
            "source": audit_source,
        },
    )
    return dict(current), dict(recommendation), str(permission_id)


@app.post("/api/appointments/{appointment_id}/reschedule", status_code=200)
def apply_reschedule(
    appointment_id: str,
    body: RescheduleApplyBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    correlation_id = str(uuid.uuid4())
    try:
        with transaction() as connection:
            _execute_reschedule(
                connection,
                appointment_id=appointment_id,
                recommendation_id=body.recommendation_id,
                actor_id=user["id"],
                reason=body.reason,
                correlation_id=correlation_id,
            )
    except psycopg.errors.ExclusionViolation as exc:
        raise HTTPException(status_code=409, detail="The replacement slot was just taken") from exc
    except psycopg.errors.RaiseException as exc:
        raise HTTPException(
            status_code=409,
            detail="The replacement now conflicts with protected capacity; search again",
        ) from exc
    return {"appointment_id": appointment_id, "status": "confirmed", "locked": True}


@app.post("/api/appointments/{appointment_id}/status")
def update_appointment_status(
    appointment_id: str,
    body: AppointmentStatusBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        current = connection.execute(
            """
            SELECT status::text AS status, doctor_id, room_id, starts_at, ends_at,
                   checked_in_at, seated_at
              FROM appointments WHERE id = %s FOR UPDATE
            """,
            (appointment_id,),
        ).fetchone()
        if not current or current["status"] != "confirmed":
            raise HTTPException(status_code=409, detail="Only confirmed appointments can be closed")
        now = datetime.now(current["starts_at"].tzinfo)
        if body.status == "completed" and not current["seated_at"]:
            raise HTTPException(status_code=409, detail="Seat the patient before completing the visit")
        if body.status == "no_show":
            if current["starts_at"] > now:
                raise HTTPException(status_code=409, detail="A visit cannot be marked no-show before its start time")
            if current["checked_in_at"] or current["seated_at"]:
                raise HTTPException(status_code=409, detail="A patient who arrived cannot be marked no-show")
        connection.execute(
            "UPDATE appointments SET status = %s WHERE id = %s",
            (body.status, appointment_id),
        )
        connection.execute(
            "UPDATE appointment_phases SET active = false WHERE appointment_id = %s",
            (appointment_id,),
        )
        connection.execute(
            "UPDATE appointment_equipment_reservations SET active = false WHERE appointment_id = %s",
            (appointment_id,),
        )
        if body.status == "completed":
            connection.execute(
                "UPDATE appointments SET completed_at = transaction_timestamp() WHERE id = %s",
                (appointment_id,),
            )
            observation = connection.execute(
                """
                INSERT INTO procedure_duration_observations (
                    batch_id, procedure_id, doctor_id, service_date,
                    scheduled_minutes, actual_minutes, outcome,
                    source
                )
                SELECT NULL, a.procedure_id, a.doctor_id,
                       (a.starts_at AT TIME ZONE %s)::date,
                       ROUND(EXTRACT(EPOCH FROM (a.ends_at - a.starts_at)) / 60)::integer,
                       ROUND(EXTRACT(EPOCH FROM (transaction_timestamp() - a.seated_at)) / 60)::integer,
                       'completed', 'native'
                  FROM appointments a
                 WHERE a.id = %s AND a.seated_at IS NOT NULL
                   AND transaction_timestamp() - a.seated_at >= interval '5 minutes'
                RETURNING procedure_id
                """,
                (settings.practice_timezone, appointment_id),
            ).fetchone()
            if observation:
                _refresh_calibration_recommendations(
                    connection, {str(observation["procedure_id"])}, source_batch_id=None
                )
        connection.execute(
            """
            INSERT INTO appointment_status_history (
                appointment_id, previous_status, new_status, actor_id, reason_code
            ) VALUES (%s, 'confirmed', %s, %s, %s)
            """,
            (appointment_id, body.status, user["id"], body.reason.strip()),
        )
        append_audit(
            connection, actor_id=user["id"], event_type=f"appointment.{body.status}",
            entity_type="appointment", entity_id=appointment_id,
            correlation_id=correlation_id, details={"reason_recorded": True},
        )
        matching_waitlist = connection.execute(
            """
            SELECT count(*) AS count
              FROM waitlist_entries w
              JOIN appointments a ON a.id = %s
             WHERE w.status = 'active' AND w.procedure_id = a.procedure_id
               AND (a.starts_at AT TIME ZONE %s)::date BETWEEN w.earliest_date AND w.latest_date
            """,
            (appointment_id, settings.practice_timezone),
        ).fetchone()["count"]
    vacancy_recovery_eligible = bool(
        body.status == "cancelled"
        and user["role"] in {"administrator", "scheduler"}
        and current["room_id"] is not None
        and current["starts_at"] > datetime.now(current["starts_at"].tzinfo)
        and current["checked_in_at"] is None
        and current["seated_at"] is None
    )
    return {
        "appointment_id": appointment_id,
        "status": body.status,
        "waitlist_matches": matching_waitlist,
        "vacancy_recovery_eligible": vacancy_recovery_eligible,
        "released_slot": {
            "starts_at": current["starts_at"].isoformat(),
            "ends_at": current["ends_at"].isoformat(),
        } if vacancy_recovery_eligible else None,
    }


@app.post("/api/appointments/{appointment_id}/vacancy-recovery")
def begin_vacancy_recovery(
    appointment_id: str,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    try:
        with transaction() as connection:
            chain = start_chain(
                connection,
                appointment_id=appointment_id,
                actor_id=user["id"],
                correlation_id=str(uuid.uuid4()),
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"chain": chain, "global_schedule_rerun": False}


@app.get("/api/vacancy-recovery/{chain_id}")
def get_vacancy_recovery(
    chain_id: str,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    try:
        with connect() as connection:
            chain = serialize_chain(connection, chain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"chain": chain, "global_schedule_rerun": False}


@app.post("/api/vacancy-recovery/{chain_id}/candidates")
def preview_vacancy_recovery_candidates(
    chain_id: str,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    try:
        with transaction() as connection:
            return find_vacancy_candidates(
                connection,
                chain_id=chain_id,
                actor_id=user["id"],
                correlation_id=str(uuid.uuid4()),
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/vacancy-recovery/{chain_id}/move")
def apply_vacancy_recovery_move(
    chain_id: str,
    body: VacancyRecoveryMoveBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    if not body.patient_permission_confirmed or not body.exact_move_acknowledged:
        raise HTTPException(
            status_code=409,
            detail="Confirm patient permission and the exact one-appointment move",
        )
    correlation_id = str(uuid.uuid4())
    try:
        with transaction() as connection:
            chain = connection.execute(
                "SELECT * FROM vacancy_recovery_chains WHERE id = %s FOR UPDATE",
                (chain_id,),
            ).fetchone()
            if not chain or chain["status"] != "active":
                raise HTTPException(status_code=409, detail="The recovery chain is no longer active")
            if chain["current_starts_at"] <= datetime.now(chain["current_starts_at"].tzinfo):
                raise HTTPException(status_code=409, detail="The vacancy is no longer in the future")
            offer = connection.execute(
                """
                SELECT * FROM vacancy_recovery_offers
                 WHERE id = %s AND chain_id = %s AND chain_version = %s
                   AND status = 'open' AND expires_at > transaction_timestamp()
                 FOR UPDATE
                """,
                (body.offer_id, chain_id, chain["version"]),
            ).fetchone()
            if not offer:
                raise HTTPException(status_code=409, detail="This vacancy option expired; find candidates again")
            appointment = connection.execute(
                """
                SELECT * FROM appointments
                 WHERE id = %s AND status = 'confirmed' FOR UPDATE
                """,
                (offer["appointment_id"],),
            ).fetchone()
            if (
                not appointment
                or appointment["lock_version"] != offer["old_lock_version"]
                or appointment["doctor_id"] != offer["old_doctor_id"]
                or appointment["room_id"] != offer["old_room_id"]
                or appointment["starts_at"] != offer["old_starts_at"]
                or appointment["ends_at"] != offer["old_ends_at"]
                or appointment["checked_in_at"] is not None
                or appointment["seated_at"] is not None
                or appointment["starts_at"] <= chain["current_starts_at"]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="The selected appointment changed; find candidates again",
                )
            recommendation = connection.execute(
                """
                SELECT * FROM recommendation_snapshots
                 WHERE id = %s AND reschedules_appointment_id = %s
                   AND consumed_at IS NULL AND expires_at > transaction_timestamp()
                 FOR SHARE
                """,
                (offer["recommendation_id"], offer["appointment_id"]),
            ).fetchone()
            if (
                not recommendation
                or recommendation["doctor_id"] != offer["target_doctor_id"]
                or recommendation["room_id"] != offer["target_room_id"]
                or recommendation["starts_at"] != offer["target_starts_at"]
                or recommendation["ends_at"] != offer["target_ends_at"]
                or offer["target_doctor_id"] != chain["current_doctor_id"]
                or offer["target_room_id"] != chain["current_room_id"]
                or offer["target_starts_at"] != chain["current_starts_at"]
                or offer["target_ends_at"] > chain["current_ends_at"]
            ):
                raise HTTPException(status_code=409, detail="The exact vacancy option is no longer valid")

            old_appointment, _, permission_id = _execute_reschedule(
                connection,
                appointment_id=str(offer["appointment_id"]),
                recommendation_id=str(offer["recommendation_id"]),
                actor_id=user["id"],
                reason=body.reason,
                correlation_id=correlation_id,
                audit_source="vacancy_recovery",
            )
            sequence = int(chain["step_count"]) + 1
            connection.execute(
                """
                INSERT INTO vacancy_recovery_steps (
                    chain_id, sequence, offer_id, appointment_id,
                    reschedule_permission_id, vacancy_doctor_id, vacancy_room_id,
                    vacancy_starts_at, vacancy_ends_at, released_doctor_id,
                    released_room_id, released_starts_at, released_ends_at,
                    permission_method, permission_confirmed, authorization_reason, moved_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, true, %s, %s)
                """,
                (
                    chain_id, sequence, offer["id"], offer["appointment_id"],
                    permission_id, chain["current_doctor_id"], chain["current_room_id"],
                    chain["current_starts_at"], chain["current_ends_at"],
                    old_appointment["doctor_id"], old_appointment["room_id"],
                    old_appointment["starts_at"], old_appointment["ends_at"],
                    body.permission_method, body.reason.strip(), user["id"],
                ),
            )
            connection.execute(
                """
                UPDATE vacancy_recovery_offers
                   SET status = 'consumed', consumed_at = transaction_timestamp()
                 WHERE id = %s
                """,
                (offer["id"],),
            )
            connection.execute(
                """
                UPDATE vacancy_recovery_offers SET status = 'invalidated'
                 WHERE chain_id = %s AND status = 'open'
                """,
                (chain_id,),
            )
            connection.execute(
                """
                UPDATE vacancy_recovery_chains
                   SET current_doctor_id = %s, current_room_id = %s,
                       current_starts_at = %s, current_ends_at = %s,
                       step_count = %s, version = version + 1
                 WHERE id = %s
                """,
                (
                    old_appointment["doctor_id"], old_appointment["room_id"],
                    old_appointment["starts_at"], old_appointment["ends_at"],
                    sequence, chain_id,
                ),
            )
            append_audit(
                connection,
                actor_id=user["id"],
                event_type="vacancy_recovery.move_applied",
                entity_type="vacancy_recovery_chain",
                entity_id=chain_id,
                correlation_id=correlation_id,
                details={
                    "appointment_id": str(offer["appointment_id"]),
                    "offer_id": str(offer["id"]),
                    "permission_id": permission_id,
                    "permission_method": body.permission_method,
                    "sequence": sequence,
                    "global_schedule_rerun": False,
                },
            )
            result = serialize_chain(connection, chain_id)
    except psycopg.errors.ExclusionViolation as exc:
        raise HTTPException(status_code=409, detail="The vacancy was just taken") from exc
    except psycopg.errors.RaiseException as exc:
        raise HTTPException(status_code=409, detail="The protected move is no longer valid") from exc
    return {"chain": result, "moved_appointment_id": str(offer["appointment_id"]), "global_schedule_rerun": False}


@app.post("/api/vacancy-recovery/{chain_id}/stop")
def end_vacancy_recovery(
    chain_id: str,
    body: VacancyRecoveryStopBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    try:
        with transaction() as connection:
            chain = stop_chain(
                connection,
                chain_id=chain_id,
                actor_id=user["id"],
                reason=body.reason,
                correlation_id=str(uuid.uuid4()),
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"chain": chain, "global_schedule_rerun": False}


@app.post("/api/appointments/{appointment_id}/flow")
def update_appointment_flow(
    appointment_id: str,
    body: AppointmentFlowBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    with transaction() as connection:
        current = connection.execute(
            """
            SELECT status::text AS status, checked_in_at, seated_at, starts_at
              FROM appointments WHERE id = %s FOR UPDATE
            """,
            (appointment_id,),
        ).fetchone()
        if not current or current["status"] != "confirmed":
            raise HTTPException(status_code=409, detail="Only confirmed visits can advance")
        practice_timezone = ZoneInfo(settings.practice_timezone)
        if current["starts_at"].astimezone(practice_timezone).date() != datetime.now(practice_timezone).date():
            raise HTTPException(
                status_code=409,
                detail="Patient flow can only advance on the scheduled practice date",
            )
        if body.action == "check_in":
            if current["checked_in_at"]:
                raise HTTPException(status_code=409, detail="Patient is already checked in")
            connection.execute(
                "UPDATE appointments SET checked_in_at = transaction_timestamp() WHERE id = %s",
                (appointment_id,),
            )
        else:
            if not current["checked_in_at"]:
                raise HTTPException(status_code=409, detail="Check the patient in before seating")
            if current["seated_at"]:
                raise HTTPException(status_code=409, detail="Patient is already seated")
            connection.execute(
                "UPDATE appointments SET seated_at = transaction_timestamp() WHERE id = %s",
                (appointment_id,),
            )
        append_audit(
            connection, actor_id=user["id"], event_type=f"appointment.{body.action}",
            entity_type="appointment", entity_id=appointment_id,
            correlation_id=str(uuid.uuid4()),
        )
    return {"appointment_id": appointment_id, "flow": body.action}


@app.get("/api/operations")
def operations(
    day: date,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    timezone = ZoneInfo(settings.practice_timezone)
    start = datetime.combine(day, time.min, tzinfo=timezone)
    end = start + timedelta(days=1)
    with connect() as connection:
        appointment_rows = connection.execute(
            """
            SELECT a.id, a.starts_at, a.ends_at, a.status::text AS status,
                   a.arrival_type, a.checked_in_at, a.seated_at, a.completed_at,
                   p.display_name AS patient_name, pr.name AS procedure_name,
                   pr.production_cents, d.display_name AS doctor_name, r.name AS room_name,
                   vc.id AS vacancy_recovery_chain_id,
                   vc.status AS vacancy_recovery_status
              FROM appointments a
              JOIN patients p ON p.id = a.patient_id
              JOIN procedures pr ON pr.id = a.procedure_id
              JOIN doctors d ON d.id = a.doctor_id
              LEFT JOIN rooms r ON r.id = a.room_id
              LEFT JOIN vacancy_recovery_chains vc ON vc.source_appointment_id = a.id
             WHERE a.starts_at < %s AND a.ends_at > %s
               AND a.status IN ('confirmed', 'completed', 'cancelled', 'no_show')
             ORDER BY a.starts_at, r.name
            """,
            (end, start),
        ).fetchall()
        phase_rows = connection.execute(
            """
            SELECT ap.appointment_id, ap.sequence, ap.phase_name, ap.role,
                   ap.starts_at, ap.ends_at, pv.display_name AS provider_name
              FROM appointment_phases ap
              LEFT JOIN providers pv ON pv.id = ap.provider_id
             WHERE ap.starts_at < %s AND ap.ends_at > %s
             ORDER BY ap.appointment_id, ap.sequence
            """,
            (end, start),
        ).fetchall()
        provider_rows = connection.execute(
            """
            SELECT pv.id, pv.display_name, pv.role::text AS role,
                   COALESCE(sum(c.amount_cents) FILTER (WHERE a.id IS NOT NULL), 0) AS production_cents,
                   COALESCE((
                       SELECT t.target_cents FROM provider_daily_targets t
                        WHERE t.provider_id = pv.id AND t.weekday = %s
                          AND t.effective_from <= %s
                          AND (t.effective_through IS NULL OR t.effective_through >= %s)
                        ORDER BY t.effective_from DESC LIMIT 1
                   ), 0) AS target_cents,
                   COALESCE((
                       SELECT sum(EXTRACT(EPOCH FROM (ap.ends_at - ap.starts_at)) / 60)::integer
                         FROM appointment_phases ap
                        WHERE ap.provider_id = pv.id AND ap.active
                          AND ap.starts_at < %s AND ap.ends_at > %s
                   ), 0) AS booked_minutes
              FROM providers pv
              LEFT JOIN appointment_production_credits c ON c.provider_id = pv.id
              LEFT JOIN appointments a ON a.id = c.appointment_id
                 AND a.starts_at < %s AND a.ends_at > %s
                 AND a.status IN ('confirmed', 'completed')
             WHERE pv.active
             GROUP BY pv.id, pv.display_name, pv.role
             ORDER BY pv.role, pv.display_name
            """,
            (day.weekday(), day, day, end, start, end, start),
        ).fetchall()
    phase_map: dict[str, list[dict]] = {}
    for row in phase_rows:
        phase_map.setdefault(str(row["appointment_id"]), []).append(
            {
                "sequence": row["sequence"], "name": row["phase_name"], "role": row["role"],
                "provider_name": row["provider_name"],
                "starts_at": row["starts_at"].isoformat(), "ends_at": row["ends_at"].isoformat(),
            }
        )
    appointments = []
    for row in appointment_rows:
        serialized = serialize_appointment(row)
        serialized["production_cents"] = row["production_cents"]
        serialized["phases"] = phase_map.get(str(row["id"]), [])
        appointments.append(serialized)
    return {
        "day": day.isoformat(), "appointments": appointments,
        "providers": [
            {"id": str(row["id"]), "name": row["display_name"], "role": row["role"],
             "production_cents": row["production_cents"], "target_cents": row["target_cents"],
             "booked_minutes": row["booked_minutes"]}
            for row in provider_rows
        ],
    }


@app.get("/api/waitlist")
def list_waitlist(
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT w.id, w.predecessor_appointment_id, w.relationship,
                   w.earliest_date, w.latest_date, w.local_start, w.local_end,
                   w.priority::text AS priority, w.status, w.created_at,
                   p.display_name AS patient_name, p.medical_record_number,
                   pr.code AS procedure_code, pr.name AS procedure_name,
                   d.display_name AS doctor_name,
                   (SELECT count(*) FROM waitlist_contact_attempts ca
                     WHERE ca.waitlist_entry_id = w.id) AS contact_attempts,
                   (SELECT ca.outcome FROM waitlist_contact_attempts ca
                     WHERE ca.waitlist_entry_id = w.id
                     ORDER BY ca.attempted_at DESC LIMIT 1) AS last_contact_outcome
              FROM waitlist_entries w
              JOIN patients p ON p.id = w.patient_id
              JOIN procedures pr ON pr.id = w.procedure_id
              LEFT JOIN doctors d ON d.id = w.preferred_doctor_id
             WHERE w.status IN ('active', 'offered')
             ORDER BY CASE w.priority WHEN 'urgent' THEN 1 WHEN 'priority' THEN 2 ELSE 3 END,
                      w.created_at
            """
        ).fetchall()
    return {
        "entries": [
            {
                **row, "id": str(row["id"]),
                "predecessor_appointment_id": str(row["predecessor_appointment_id"])
                if row["predecessor_appointment_id"] else None,
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
    }


@app.post("/api/waitlist", status_code=201)
def create_waitlist(
    body: WaitlistBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    validate_window(body.earliest_date, body.latest_date, body.time_from, body.time_to)
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        procedure = connection.execute(
            "SELECT id FROM procedures WHERE code = %s AND active", (body.procedure_code,)
        ).fetchone()
        if not procedure:
            raise HTTPException(status_code=404, detail="Procedure not found")
        patient = connection.execute(
            "SELECT id FROM patients WHERE medical_record_number = %s",
            (body.medical_record_number,),
        ).fetchone()
        if patient:
            patient_id = patient["id"]
            connection.execute("UPDATE patients SET display_name = %s WHERE id = %s", (body.patient_name, patient_id))
        else:
            patient_id = connection.execute(
                "INSERT INTO patients (medical_record_number, display_name, created_by) VALUES (%s, %s, %s) RETURNING id",
                (body.medical_record_number, body.patient_name, user["id"]),
            ).fetchone()["id"]
        waitlist_id = connection.execute(
            """
            INSERT INTO waitlist_entries (
                patient_id, procedure_id, preferred_doctor_id, earliest_date,
                latest_date, local_start, local_end, priority, notes, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (patient_id, procedure["id"], body.preferred_doctor_id, body.earliest_date,
             body.latest_date, body.time_from, body.time_to, body.priority,
             body.notes.strip() or None, user["id"]),
        ).fetchone()["id"]
        append_audit(
            connection, actor_id=user["id"], event_type="waitlist.created",
            entity_type="waitlist", entity_id=str(waitlist_id), correlation_id=correlation_id,
        )
    return {"id": str(waitlist_id), "status": "active"}


@app.post("/api/waitlist/{waitlist_id}/contacts", status_code=201)
def record_waitlist_contact(
    waitlist_id: str,
    body: WaitlistContactBody,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    with transaction() as connection:
        entry = connection.execute(
            "SELECT status FROM waitlist_entries WHERE id = %s FOR UPDATE",
            (waitlist_id,),
        ).fetchone()
        if not entry or entry["status"] not in {"active", "offered"}:
            raise HTTPException(status_code=409, detail="Waitlist entry is no longer contactable")
        contact_id = connection.execute(
            """
            INSERT INTO waitlist_contact_attempts (
                waitlist_entry_id, channel, outcome, incentive_offered, created_by
            ) VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (waitlist_id, body.channel, body.outcome,
             body.incentive_offered.strip() or None, user["id"]),
        ).fetchone()["id"]
        if body.outcome == "declined":
            connection.execute(
                "UPDATE waitlist_entries SET status = 'declined', updated_at = transaction_timestamp() WHERE id = %s",
                (waitlist_id,),
            )
        elif body.outcome in {"offered", "accepted"}:
            connection.execute(
                "UPDATE waitlist_entries SET status = 'offered', updated_at = transaction_timestamp() WHERE id = %s",
                (waitlist_id,),
            )
        append_audit(
            connection, actor_id=user["id"], event_type="waitlist.contact_recorded",
            entity_type="waitlist", entity_id=waitlist_id,
            correlation_id=str(uuid.uuid4()),
            details={"channel": body.channel, "outcome": body.outcome,
                     "incentive_recorded": bool(body.incentive_offered.strip())},
        )
    return {"id": str(contact_id), "outcome": body.outcome}


@app.post("/api/waitlist/{waitlist_id}/matches")
def waitlist_matches(
    waitlist_id: str,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    with transaction() as connection:
        entry = connection.execute(
            """
            SELECT w.*, p.id AS patient_id, pr.code, pr.name, pr.duration_minutes,
                   pr.preparation_minutes, pr.cleanup_minutes, pr.production_cents
              FROM waitlist_entries w
              JOIN patients p ON p.id = w.patient_id
              JOIN procedures pr ON pr.id = w.procedure_id
             WHERE w.id = %s AND w.status IN ('active', 'offered') FOR UPDATE
            """,
            (waitlist_id,),
        ).fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="Active waitlist entry not found")
        request_id = connection.execute(
            """
            INSERT INTO scheduling_requests (
                patient_id, procedure_id, normalized_intake, normalization_model_id,
                normalization_confidence, staff_confirmed_intake, priority,
                earliest_date, latest_date, source_waitlist_id, created_by
            ) VALUES (%s, %s, '{"source":"waitlist"}', 'not_applicable', 1, true,
                      %s, %s, %s, %s, %s) RETURNING id
            """,
            (entry["patient_id"], entry["procedure_id"], entry["priority"],
             entry["earliest_date"], entry["latest_date"], waitlist_id, user["id"]),
        ).fetchone()["id"]
        candidates = create_recommendations(
            connection, scheduling_request_id=str(request_id), patient_id=str(entry["patient_id"]),
            procedure={
                "id": entry["procedure_id"], "code": entry["code"], "name": entry["name"],
                "duration_minutes": entry["duration_minutes"],
                "preparation_minutes": entry["preparation_minutes"],
                "cleanup_minutes": entry["cleanup_minutes"],
                "production_cents": entry["production_cents"],
            },
            start_date=entry["earliest_date"], end_date=entry["latest_date"],
            start_time=entry["local_start"], end_time=entry["local_end"],
            preferred_doctor_id=str(entry["preferred_doctor_id"]) if entry["preferred_doctor_id"] else None,
            actor_id=user["id"], priority=str(entry["priority"]),
        )
        if candidates:
            connection.execute(
                "UPDATE waitlist_entries SET status = 'offered', updated_at = transaction_timestamp() WHERE id = %s",
                (waitlist_id,),
            )
    return {"waitlist_id": waitlist_id, "candidates": candidates}


@app.get("/api/reserved-blocks")
def list_reserved_blocks(
    date_from: date | None = None,
    date_to: date | None = None,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    timezone = ZoneInfo(settings.practice_timezone)
    today = datetime.now(timezone).date()
    start_date = date_from or today
    end_date = date_to or (today + timedelta(days=settings.scheduling_horizon_days))
    if end_date < start_date or end_date > today + timedelta(days=settings.scheduling_horizon_days):
        raise HTTPException(status_code=422, detail="Reserved-block range is outside the rolling horizon")
    window_start = datetime.combine(start_date, time.min, tzinfo=timezone)
    window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone)
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        release_expired_reserved_blocks(
            connection, actor_id=user["id"], correlation_id=correlation_id
        )
        rows = connection.execute(
            """
            SELECT b.id, b.doctor_id, d.display_name AS doctor_name,
                   p.code AS procedure_code, p.name AS procedure_name,
                   b.room_id, r.name AS room_name,
                   b.equipment_id, e.name AS equipment_name,
                   b.equipment_unit_number,
                   lower(b.reserved_during) AS starts_at,
                   upper(b.reserved_during) AS ends_at,
                   b.release_at, b.status::text AS status, b.reason
              FROM reserved_procedure_blocks b
              JOIN doctors d ON d.id = b.doctor_id
              JOIN procedures p ON p.id = b.procedure_id
              LEFT JOIN rooms r ON r.id = b.room_id
              LEFT JOIN equipment e ON e.id = b.equipment_id
             WHERE b.reserved_during && tstzrange(%s, %s, '[)')
             ORDER BY lower(b.reserved_during), d.display_name
            """,
            (window_start, window_end),
        ).fetchall()
    return {"blocks": [serialize_reserved_block(row) for row in rows]}


@app.post("/api/configuration/reserved-blocks", status_code=201)
def create_reserved_block(
    body: ReservedProcedureBlockBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    require_aware_datetime(body.starts_at, "Block start")
    require_aware_datetime(body.ends_at, "Block end")
    if body.release_at:
        require_aware_datetime(body.release_at, "Automatic release time")
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="Block end must be after block start")
    if body.ends_at - body.starts_at > timedelta(hours=12):
        raise HTTPException(status_code=422, detail="A reserved block cannot exceed 12 hours")
    if (body.equipment_id is None) != (body.equipment_unit_number is None):
        raise HTTPException(status_code=422, detail="Select both equipment and its unit number")
    timezone = ZoneInfo(settings.practice_timezone)
    now = datetime.now(timezone)
    local_start = body.starts_at.astimezone(timezone)
    local_end = body.ends_at.astimezone(timezone)
    if local_start.date() != local_end.date():
        raise HTTPException(status_code=422, detail="A doctor procedure block must start and end on the same practice date")
    if local_start < now:
        raise HTTPException(status_code=422, detail="Reserved blocks must start in the future")
    if local_end.date() > now.date() + timedelta(days=settings.scheduling_horizon_days):
        raise HTTPException(status_code=422, detail="Block exceeds the rolling one-year horizon")
    if body.release_at and not (now < body.release_at.astimezone(timezone) < local_end):
        raise HTTPException(status_code=422, detail="Automatic release must be in the future and before block end")
    repeat_until = body.repeat_weekly_until or local_start.date()
    if repeat_until < local_start.date():
        raise HTTPException(status_code=422, detail="Weekly repeat end cannot precede the first block")
    if repeat_until > now.date() + timedelta(days=settings.scheduling_horizon_days):
        raise HTTPException(status_code=422, detail="Weekly repeat exceeds the rolling one-year horizon")
    local_release = body.release_at.astimezone(timezone) if body.release_at else None
    occurrences = weekly_block_occurrences(
        local_start, local_end, local_release, repeat_until
    )
    for occurrence_start, occurrence_end, _ in occurrences:
        if occurrence_end.date() > now.date() + timedelta(days=settings.scheduling_horizon_days):
            raise HTTPException(status_code=422, detail="A repeated block exceeds the rolling one-year horizon")

    correlation_id = str(uuid.uuid4())
    try:
        with transaction() as connection:
            release_expired_reserved_blocks(
                connection, actor_id=user["id"], correlation_id=correlation_id
            )
            procedure = connection.execute(
                "SELECT id, name FROM procedures WHERE code = %s AND active",
                (body.procedure_code,),
            ).fetchone()
            doctor = connection.execute(
                """
                SELECT d.id, d.display_name, pv.id AS provider_id
                  FROM doctors d
                  JOIN providers pv ON pv.doctor_id = d.id AND pv.active
                 WHERE d.id = %s AND d.active
                """,
                (body.doctor_id,),
            ).fetchone()
            if not procedure or not doctor:
                raise HTTPException(status_code=404, detail="Active doctor or procedure not found")
            if body.room_id:
                eligible_room = connection.execute(
                    """
                    SELECT 1 FROM rooms r
                    JOIN procedure_room_eligibility x ON x.room_id = r.id
                     WHERE r.id = %s AND r.active AND x.procedure_id = %s
                    """,
                    (body.room_id, procedure["id"]),
                ).fetchone()
                if not eligible_room:
                    raise HTTPException(status_code=422, detail="Room is not eligible for this procedure")
            block_ids: list[str] = []
            for occurrence_number, (occurrence_start, occurrence_end, occurrence_release) in enumerate(occurrences, 1):
                shift = connection.execute(
                    """
                    SELECT status, local_start, local_end
                      FROM provider_shift_overrides
                     WHERE provider_id = %s AND shift_date = %s
                    """,
                    (doctor["provider_id"], occurrence_start.date()),
                ).fetchone()
                local_start_time = occurrence_start.time().replace(tzinfo=None)
                local_end_time = occurrence_end.time().replace(tzinfo=None)
                if shift:
                    within_hours = (
                        shift["status"] != "off"
                        and shift["local_start"] is not None
                        and shift["local_end"] is not None
                        and shift["local_start"] <= local_start_time
                        and shift["local_end"] >= local_end_time
                    )
                else:
                    within_hours = bool(connection.execute(
                        """
                        SELECT 1 FROM provider_working_hours
                         WHERE provider_id = %s AND weekday = %s
                           AND local_start <= %s AND local_end >= %s
                           AND effective_from <= %s
                           AND (effective_through IS NULL OR effective_through >= %s)
                        """,
                        (
                            doctor["provider_id"], occurrence_start.weekday(),
                            local_start_time, local_end_time,
                            occurrence_start.date(), occurrence_start.date(),
                        ),
                    ).fetchone())
                if not within_hours:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Doctor is not working for the complete block on {occurrence_start.date().isoformat()}",
                    )
                unavailable = connection.execute(
                    """
                    SELECT 1
                      FROM provider_unavailability
                     WHERE provider_id = %s
                       AND unavailable_during && tstzrange(%s, %s, '[)')
                    UNION ALL
                    SELECT 1
                      FROM practice_closures
                     WHERE closed_during && tstzrange(%s, %s, '[)')
                     LIMIT 1
                    """,
                    (
                        doctor["provider_id"], occurrence_start, occurrence_end,
                        occurrence_start, occurrence_end,
                    ),
                ).fetchone()
                if unavailable:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Doctor procedure block overlaps leave or a closure on {occurrence_start.date().isoformat()}",
                    )
                qualified = connection.execute(
                    """
                    SELECT 1 FROM doctor_procedure_qualifications
                     WHERE doctor_id = %s AND procedure_id = %s
                       AND effective_from <= %s
                       AND (effective_through IS NULL OR effective_through >= %s)
                    """,
                    (
                        doctor["id"], procedure["id"],
                        occurrence_start.date(), occurrence_end.date(),
                    ),
                ).fetchone()
                if not qualified:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Doctor is not qualified for this procedure on {occurrence_start.date().isoformat()}",
                    )
                block_id = connection.execute(
                    """
                    INSERT INTO reserved_procedure_blocks (
                        doctor_id, procedure_id, room_id, equipment_id,
                        equipment_unit_number, reserved_during, release_at,
                        reason, created_by
                    ) VALUES (%s, %s, %s, %s, %s, tstzrange(%s, %s, '[)'), %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        doctor["id"], procedure["id"], body.room_id,
                        body.equipment_id, body.equipment_unit_number,
                        occurrence_start, occurrence_end, occurrence_release,
                        body.reason.strip(), user["id"],
                    ),
                ).fetchone()["id"]
                block_ids.append(str(block_id))
                append_audit(
                    connection,
                    actor_id=user["id"],
                    event_type="reserved_block.created",
                    entity_type="reserved_procedure_block",
                    entity_id=str(block_id),
                    correlation_id=correlation_id,
                    details={
                        "doctor_id": str(doctor["id"]),
                        "procedure_code": body.procedure_code,
                        "room_reserved": bool(body.room_id),
                        "equipment_reserved": bool(body.equipment_id),
                        "weekly_series": len(occurrences) > 1,
                        "occurrence": occurrence_number,
                        "occurrence_count": len(occurrences),
                    },
                )
    except (psycopg.errors.ExclusionViolation, psycopg.errors.RaiseException) as exc:
        raise HTTPException(status_code=409, detail=str(exc).splitlines()[0]) from exc
    return {
        "id": block_ids[0],
        "ids": block_ids,
        "count": len(block_ids),
        "status": "active",
    }


@app.post("/api/configuration/reserved-blocks/{block_id}/release")
def release_reserved_block(
    block_id: str,
    body: ReservedBlockReleaseBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    correlation_id = str(uuid.uuid4())
    with transaction() as connection:
        block = connection.execute(
            "SELECT id FROM reserved_procedure_blocks WHERE id = %s AND status = 'active' FOR UPDATE",
            (block_id,),
        ).fetchone()
        if not block:
            raise HTTPException(status_code=404, detail="Active reserved block not found")
        connection.execute(
            "SELECT set_config('siligent.reserved_block_change_id', %s, true)",
            (block_id,),
        )
        connection.execute(
            """
            UPDATE reserved_procedure_blocks
               SET status = 'released', released_by = %s,
                   released_at = transaction_timestamp(), release_reason = %s
             WHERE id = %s
            """,
            (user["id"], body.reason.strip(), block_id),
        )
        append_audit(
            connection,
            actor_id=user["id"],
            event_type="reserved_block.released",
            entity_type="reserved_procedure_block",
            entity_id=block_id,
            correlation_id=correlation_id,
            details={"reason_recorded": True},
        )
    return {"id": block_id, "status": "released"}


@app.get("/api/configuration")
def configuration(user: dict = Depends(require_roles("administrator", "scheduler"))):
    with connect() as connection:
        providers = connection.execute(
            """
            SELECT pv.id, pv.staff_code, pv.display_name, pv.role::text AS role, pv.active,
                   pv.doctor_id, d.max_active_rooms
              FROM providers pv LEFT JOIN doctors d ON d.id = pv.doctor_id
             ORDER BY pv.role, pv.display_name
            """
        ).fetchall()
        rooms = connection.execute(
            "SELECT id, code, name, category, turnover_minutes, active FROM rooms ORDER BY name"
        ).fetchall()
        leave = connection.execute(
            """
            SELECT u.id, u.provider_id, p.display_name, lower(u.unavailable_during) AS starts_at,
                   upper(u.unavailable_during) AS ends_at, u.reason_code
              FROM provider_unavailability u JOIN providers p ON p.id = u.provider_id
             WHERE upper(u.unavailable_during) >= transaction_timestamp()
             ORDER BY starts_at LIMIT 100
            """
        ).fetchall()
        users = connection.execute(
            "SELECT id, display_name, role::text AS role, active FROM app_users ORDER BY display_name"
        ).fetchall()
        procedures = connection.execute(
            """
            SELECT id, code, name, production_cents, active
              FROM procedures ORDER BY name
            """
        ).fetchall()
        phases = connection.execute(
            """
            SELECT ph.id, p.code AS procedure_code, ph.sequence, ph.code, ph.name,
                   ph.required_role AS role, ph.duration_minutes AS standard_minutes,
                   ph.complex_duration_minutes AS complex_minutes
              FROM procedure_phase_templates ph
              JOIN procedures p ON p.id = ph.procedure_id
             WHERE ph.active ORDER BY p.code, ph.sequence
            """
        ).fetchall()
        preferences = connection.execute(
            """
            SELECT x.provider_id, p.code AS procedure_code, x.preference
              FROM provider_procedure_preferences x
              JOIN procedures p ON p.id = x.procedure_id
             ORDER BY x.provider_id, p.code
            """
        ).fetchall()
        equipment = connection.execute(
            "SELECT id, code, name, quantity, active FROM equipment ORDER BY name"
        ).fetchall()
        equipment_requirements = connection.execute(
            """
            SELECT r.equipment_id, p.code AS procedure_code, r.quantity
              FROM procedure_equipment_requirements r
              JOIN procedures p ON p.id = r.procedure_id
             ORDER BY p.code
            """
        ).fetchall()
        shifts = connection.execute(
            """
            SELECT s.id, s.provider_id, s.shift_date, s.status, s.local_start,
                   s.local_end, s.covering_for_provider_id, s.notes,
                   p.display_name, c.display_name AS covering_for_name
              FROM provider_shift_overrides s
              JOIN providers p ON p.id = s.provider_id
              LEFT JOIN providers c ON c.id = s.covering_for_provider_id
             WHERE s.shift_date >= CURRENT_DATE - 7
             ORDER BY s.shift_date, p.display_name LIMIT 200
            """
        ).fetchall()
        closures = connection.execute(
            """
            SELECT id, lower(closed_during) AS starts_at, upper(closed_during) AS ends_at,
                   reason_code FROM practice_closures
             WHERE upper(closed_during) >= transaction_timestamp()
             ORDER BY starts_at LIMIT 100
            """
        ).fetchall()
    return {
        "providers": [
            {**row, "id": str(row["id"]),
             "doctor_id": str(row["doctor_id"]) if row["doctor_id"] else None}
            for row in providers
        ],
        "rooms": [{**row, "id": str(row["id"])} for row in rooms],
        "unavailability": [
            {**row, "id": str(row["id"]), "provider_id": str(row["provider_id"]),
             "starts_at": row["starts_at"].isoformat(), "ends_at": row["ends_at"].isoformat()}
            for row in leave
        ],
        "users": [{**row, "id": str(row["id"])} for row in users],
        "procedures": [{**row, "id": str(row["id"])} for row in procedures],
        "phases": [{**row, "id": str(row["id"])} for row in phases],
        "preferences": [
            {**row, "provider_id": str(row["provider_id"])} for row in preferences
        ],
        "equipment": [{**row, "id": str(row["id"])} for row in equipment],
        "equipment_requirements": [
            {**row, "equipment_id": str(row["equipment_id"])}
            for row in equipment_requirements
        ],
        "shifts": [
            {**row, "id": str(row["id"]), "provider_id": str(row["provider_id"]),
             "covering_for_provider_id": str(row["covering_for_provider_id"])
             if row["covering_for_provider_id"] else None}
            for row in shifts
        ],
        "closures": [
            {**row, "id": str(row["id"]), "starts_at": row["starts_at"].isoformat(),
             "ends_at": row["ends_at"].isoformat()}
            for row in closures
        ],
    }


@app.post("/api/configuration/unavailability", status_code=201)
def create_unavailability(
    body: UnavailabilityBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None or body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="A valid timezone-aware interval is required")
    with transaction() as connection:
        row = connection.execute(
            """
            INSERT INTO provider_unavailability (
                provider_id, unavailable_during, reason_code, created_by
            ) VALUES (%s, tstzrange(%s, %s, '[)'), %s, %s) RETURNING id
            """,
            (body.provider_id, body.starts_at, body.ends_at, body.reason_code, user["id"]),
        ).fetchone()
        append_audit(
            connection, actor_id=user["id"], event_type="provider.unavailability_created",
            entity_type="provider", entity_id=body.provider_id,
            correlation_id=str(uuid.uuid4()), details={"reason_code": body.reason_code},
        )
    return {"id": str(row["id"])}


@app.post("/api/configuration/providers", status_code=201)
def create_provider(
    body: ProviderCreateBody,
    user: dict = Depends(require_roles("administrator")),
):
    try:
        with transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO providers (staff_code, display_name, role)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (body.staff_code.strip().upper(), body.display_name.strip(), body.role),
            ).fetchone()
            for weekday in range(5):
                connection.execute(
                    """
                    INSERT INTO provider_working_hours (
                        provider_id, weekday, local_start, local_end, effective_from
                    ) VALUES (%s, %s, '08:00', '17:00', CURRENT_DATE)
                    """,
                    (row["id"], weekday),
                )
            append_audit(
                connection, actor_id=user["id"], event_type="provider.created",
                entity_type="provider", entity_id=str(row["id"]),
                correlation_id=str(uuid.uuid4()), details={"role": body.role},
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Provider staff code already exists") from exc
    return {"id": str(row["id"])}


@app.post("/api/configuration/rooms", status_code=201)
def create_room(
    body: RoomCreateBody,
    user: dict = Depends(require_roles("administrator")),
):
    try:
        with transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO rooms (code, name, category, turnover_minutes)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (body.code.strip().upper(), body.name.strip(), body.category.strip(), body.turnover_minutes),
            ).fetchone()
            for procedure in connection.execute("SELECT id FROM procedures WHERE active").fetchall():
                connection.execute(
                    "INSERT INTO procedure_room_eligibility (procedure_id, room_id) VALUES (%s, %s)",
                    (procedure["id"], row["id"]),
                )
            for weekday in range(5):
                connection.execute(
                    """
                    INSERT INTO room_working_hours (
                        room_id, weekday, local_start, local_end, effective_from
                    ) VALUES (%s, %s, '08:00', '17:00', CURRENT_DATE)
                    """,
                    (row["id"], weekday),
                )
            append_audit(
                connection, actor_id=user["id"], event_type="room.created",
                entity_type="room", entity_id=str(row["id"]),
                correlation_id=str(uuid.uuid4()),
                details={"category": body.category.strip()},
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Operatory code already exists") from exc
    return {"id": str(row["id"])}


@app.put("/api/configuration/providers/{provider_id}/target")
def update_target(
    provider_id: str,
    body: TargetBody,
    user: dict = Depends(require_roles("administrator")),
):
    with transaction() as connection:
        provider = connection.execute(
            "SELECT id FROM providers WHERE id = %s AND active", (provider_id,)
        ).fetchone()
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        connection.execute(
            """
            UPDATE provider_daily_targets SET effective_through = CURRENT_DATE - 1
             WHERE provider_id = %s AND weekday = %s AND effective_through IS NULL
               AND effective_from < CURRENT_DATE
            """,
            (provider_id, body.weekday),
        )
        connection.execute(
            """
            INSERT INTO provider_daily_targets (provider_id, weekday, target_cents, effective_from)
            VALUES (%s, %s, %s, CURRENT_DATE)
            ON CONFLICT (provider_id, weekday, effective_from)
            DO UPDATE SET target_cents = EXCLUDED.target_cents
            """,
            (provider_id, body.weekday, body.target_cents),
        )
        append_audit(
            connection, actor_id=user["id"], event_type="provider.target_updated",
            entity_type="provider", entity_id=provider_id,
            correlation_id=str(uuid.uuid4()),
            details={"weekday": body.weekday, "target_cents": body.target_cents},
        )
    return {"provider_id": provider_id, "target_cents": body.target_cents}


@app.put("/api/configuration/doctors/{doctor_id}/capacity")
def update_doctor_capacity(
    doctor_id: str,
    body: DoctorCapacityBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    try:
        with transaction() as connection:
            row = connection.execute(
                "UPDATE doctors SET max_active_rooms = %s, updated_at = transaction_timestamp() WHERE id = %s RETURNING id",
                (body.max_active_rooms, doctor_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Dentist not found")
            append_audit(
                connection, actor_id=user["id"], event_type="doctor.capacity_updated",
                entity_type="doctor", entity_id=doctor_id, correlation_id=str(uuid.uuid4()),
                details={"max_active_rooms": body.max_active_rooms},
            )
    except psycopg.errors.RaiseException as exc:
        raise HTTPException(status_code=409, detail="The limit is below current concurrent visits") from exc
    return {"doctor_id": doctor_id, "max_active_rooms": body.max_active_rooms}


@app.put("/api/configuration/preferences")
def update_provider_preference(
    body: PreferenceBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    with transaction() as connection:
        procedure = connection.execute(
            "SELECT id FROM procedures WHERE code = %s", (body.procedure_code,)
        ).fetchone()
        if not procedure:
            raise HTTPException(status_code=404, detail="Procedure not found")
        connection.execute(
            """
            INSERT INTO provider_procedure_preferences (provider_id, procedure_id, preference)
            VALUES (%s, %s, %s)
            ON CONFLICT (provider_id, procedure_id)
            DO UPDATE SET preference = EXCLUDED.preference
            """,
            (body.provider_id, procedure["id"], body.preference),
        )
        append_audit(
            connection, actor_id=user["id"], event_type="provider.preference_updated",
            entity_type="provider", entity_id=body.provider_id,
            correlation_id=str(uuid.uuid4()),
            details={"procedure_code": body.procedure_code, "preference": body.preference},
        )
    return body.model_dump()


@app.put("/api/configuration/procedures/{procedure_code}")
def update_procedure_policy(
    procedure_code: str,
    body: ProcedurePolicyBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    if any(phase.complex_minutes < phase.standard_minutes for phase in body.phases):
        raise HTTPException(status_code=422, detail="Complex phase time cannot be shorter than standard")
    if len({phase.code for phase in body.phases}) != len(body.phases):
        raise HTTPException(status_code=422, detail="Phase codes must be unique")
    with transaction() as connection:
        procedure = connection.execute(
            "SELECT id FROM procedures WHERE code = %s FOR UPDATE", (procedure_code,)
        ).fetchone()
        if not procedure:
            raise HTTPException(status_code=404, detail="Procedure not found")
        standard_total = sum(phase.standard_minutes for phase in body.phases)
        connection.execute(
            """
            UPDATE procedures SET name = %s, production_cents = %s,
                   duration_minutes = %s, preparation_minutes = 0, cleanup_minutes = 0,
                   policy_version = 'clinician-configured', updated_at = transaction_timestamp()
             WHERE id = %s
            """,
            (body.name.strip(), body.production_cents, standard_total, procedure["id"]),
        )
        connection.execute(
            "DELETE FROM procedure_phase_templates WHERE procedure_id = %s",
            (procedure["id"],),
        )
        for sequence, phase in enumerate(body.phases, 1):
            connection.execute(
                """
                INSERT INTO procedure_phase_templates (
                    procedure_id, sequence, code, name, required_role,
                    duration_minutes, complex_duration_minutes, active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                """,
                (procedure["id"], sequence, phase.code, phase.name, phase.role,
                 phase.standard_minutes, phase.complex_minutes),
            )
        append_audit(
            connection, actor_id=user["id"], event_type="procedure.policy_updated",
            entity_type="procedure", entity_id=str(procedure["id"]),
            correlation_id=str(uuid.uuid4()),
            details={"phase_count": len(body.phases), "standard_minutes": standard_total},
        )
    return {"procedure_code": procedure_code, "phase_count": len(body.phases)}


@app.put("/api/configuration/shifts")
def update_shift_override(
    body: ShiftOverrideBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    if body.status == "off":
        if body.local_start or body.local_end or body.covering_for_provider_id:
            raise HTTPException(status_code=422, detail="Off shifts cannot contain hours or coverage")
    elif not body.local_start or not body.local_end or body.local_end <= body.local_start:
        raise HTTPException(status_code=422, detail="Scheduled shifts require valid local hours")
    if (body.status == "cover") != bool(body.covering_for_provider_id):
        raise HTTPException(status_code=422, detail="Cover shifts require the absent provider")
    with transaction() as connection:
        row = connection.execute(
            """
            INSERT INTO provider_shift_overrides (
                provider_id, shift_date, status, local_start, local_end,
                covering_for_provider_id, notes, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider_id, shift_date) DO UPDATE SET
                status = EXCLUDED.status, local_start = EXCLUDED.local_start,
                local_end = EXCLUDED.local_end,
                covering_for_provider_id = EXCLUDED.covering_for_provider_id,
                notes = EXCLUDED.notes, updated_at = transaction_timestamp()
            RETURNING id
            """,
            (body.provider_id, body.shift_date, body.status, body.local_start,
             body.local_end, body.covering_for_provider_id,
             body.notes.strip() or None, user["id"]),
        ).fetchone()
        append_audit(
            connection, actor_id=user["id"], event_type="provider.shift_override_updated",
            entity_type="provider", entity_id=body.provider_id,
            correlation_id=str(uuid.uuid4()),
            details={"date": body.shift_date.isoformat(), "status": body.status},
        )
    return {"id": str(row["id"])}


@app.post("/api/configuration/equipment", status_code=201)
def create_equipment(
    body: EquipmentBody,
    user: dict = Depends(require_roles("administrator")),
):
    try:
        with transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO equipment (code, name, quantity)
                VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,
                    quantity = EXCLUDED.quantity, active = true
                RETURNING id
                """,
                (body.code.strip().upper(), body.name.strip(), body.quantity),
            ).fetchone()
            append_audit(
                connection, actor_id=user["id"], event_type="equipment.configured",
                entity_type="equipment", entity_id=str(row["id"]),
                correlation_id=str(uuid.uuid4()), details={"quantity": body.quantity},
            )
    except psycopg.errors.RaiseException as exc:
        raise HTTPException(status_code=409, detail="Quantity is below an actively reserved unit") from exc
    return {"id": str(row["id"])}


@app.put("/api/configuration/equipment-requirements")
def update_equipment_requirement(
    body: EquipmentRequirementBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    with transaction() as connection:
        procedure = connection.execute(
            "SELECT id FROM procedures WHERE code = %s", (body.procedure_code,)
        ).fetchone()
        equipment = connection.execute(
            "SELECT quantity FROM equipment WHERE id = %s", (body.equipment_id,)
        ).fetchone()
        if not procedure or not equipment:
            raise HTTPException(status_code=404, detail="Procedure or equipment not found")
        if body.quantity > equipment["quantity"]:
            raise HTTPException(status_code=422, detail="Requirement exceeds available units")
        if body.quantity == 0:
            connection.execute(
                "DELETE FROM procedure_equipment_requirements WHERE procedure_id = %s AND equipment_id = %s",
                (procedure["id"], body.equipment_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO procedure_equipment_requirements (procedure_id, equipment_id, quantity)
                VALUES (%s, %s, %s) ON CONFLICT (procedure_id, equipment_id)
                DO UPDATE SET quantity = EXCLUDED.quantity
                """,
                (procedure["id"], body.equipment_id, body.quantity),
            )
        append_audit(
            connection, actor_id=user["id"], event_type="equipment.requirement_updated",
            entity_type="procedure", entity_id=str(procedure["id"]),
            correlation_id=str(uuid.uuid4()),
            details={"equipment_id": body.equipment_id, "quantity": body.quantity},
        )
    return body.model_dump()


@app.post("/api/configuration/closures", status_code=201)
def create_closure(
    body: ClosureBody,
    user: dict = Depends(require_roles("administrator", "scheduler")),
):
    if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None or body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="A valid timezone-aware interval is required")
    with transaction() as connection:
        row = connection.execute(
            """
            INSERT INTO practice_closures (closed_during, reason_code, created_by)
            VALUES (tstzrange(%s, %s, '[)'), %s, %s) RETURNING id
            """,
            (body.starts_at, body.ends_at, body.reason_code, user["id"]),
        ).fetchone()
        append_audit(
            connection, actor_id=user["id"], event_type="practice.closure_created",
            entity_type="closure", entity_id=str(row["id"]),
            correlation_id=str(uuid.uuid4()), details={"reason_code": body.reason_code},
        )
    return {"id": str(row["id"])}


@app.post("/api/configuration/users", status_code=201)
def create_user(
    body: UserCreateBody,
    user: dict = Depends(require_roles("administrator")),
):
    salt, password_hash = create_password(body.password)
    try:
        with transaction() as connection:
            row = connection.execute(
                """
                INSERT INTO app_users (external_subject, display_name, role)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (f"local:{body.username.lower()}", body.display_name.strip(), body.role),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO local_credentials (user_id, username, password_salt, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (row["id"], body.username.strip(), salt, password_hash),
            )
            append_audit(
                connection, actor_id=user["id"], event_type="user.created",
                entity_type="user", entity_id=str(row["id"]), correlation_id=str(uuid.uuid4()),
                details={"role": body.role},
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    return {"id": str(row["id"]), "role": body.role}


@app.get("/api/analytics")
def analytics(
    date_from: date,
    date_to: date,
    user: dict = Depends(require_roles("administrator", "scheduler", "clinician")),
):
    if date_to < date_from or (date_to - date_from).days > 366:
        raise HTTPException(status_code=422, detail="Analytics range must be 367 days or less")
    timezone = ZoneInfo(settings.practice_timezone)
    starts_at = datetime.combine(date_from, time.min, tzinfo=timezone)
    ends_at = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone)
    with connect() as connection:
        summary = connection.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE status = 'completed') AS completed,
                   count(*) FILTER (WHERE status = 'no_show') AS no_shows,
                   count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                   count(*) FILTER (WHERE arrival_type = 'walk_in') AS walk_ins,
                   COALESCE(sum(EXTRACT(EPOCH FROM (ends_at - starts_at)) / 60)
                       FILTER (WHERE status IN ('confirmed', 'completed')), 0)::integer AS occupied_minutes,
                   COALESCE(avg(EXTRACT(EPOCH FROM (seated_at - checked_in_at)) / 60)
                       FILTER (WHERE seated_at IS NOT NULL), 0)::numeric(10,1) AS average_wait_minutes,
                   COALESCE(avg(EXTRACT(EPOCH FROM (starts_at - created_at)) / 86400)
                       FILTER (WHERE status IN ('confirmed', 'completed')), 0)::numeric(10,1)
                       AS average_booking_lead_days
              FROM appointments
             WHERE starts_at >= %s AND starts_at < %s
            """,
            (starts_at, ends_at),
        ).fetchone()
        capacity = connection.execute(
            """
            SELECT COALESCE(sum(EXTRACT(EPOCH FROM (h.local_end - h.local_start)) / 60), 0)::integer
                       AS capacity_minutes
              FROM generate_series(%s::date, %s::date, interval '1 day') day
              JOIN room_working_hours h ON h.weekday = EXTRACT(ISODOW FROM day)::integer - 1
               AND h.effective_from <= day::date
               AND (h.effective_through IS NULL OR h.effective_through >= day::date)
              JOIN rooms r ON r.id = h.room_id AND r.active
            """,
            (date_from, date_to),
        ).fetchone()["capacity_minutes"]
        production = connection.execute(
            """
            SELECT COALESCE(sum(c.amount_cents), 0) AS amount
              FROM appointment_production_credits c
              JOIN appointments a ON a.id = c.appointment_id
             WHERE a.starts_at >= %s AND a.starts_at < %s
               AND a.status IN ('confirmed', 'completed')
            """,
            (starts_at, ends_at),
        ).fetchone()["amount"]
        providers = connection.execute(
            """
            SELECT pv.id, pv.display_name, pv.role::text AS role,
                   COALESCE(sum(c.amount_cents), 0) AS production_cents,
                   COALESCE((SELECT sum(EXTRACT(EPOCH FROM (ph.ends_at - ph.starts_at)) / 60)
                       FROM appointment_phases ph JOIN appointments a2 ON a2.id = ph.appointment_id
                      WHERE ph.provider_id = pv.id AND a2.starts_at >= %s AND a2.starts_at < %s
                        AND a2.status IN ('confirmed', 'completed')), 0)::integer AS booked_minutes
              FROM providers pv
              LEFT JOIN appointment_production_credits c ON c.provider_id = pv.id
              LEFT JOIN appointments a ON a.id = c.appointment_id
                 AND a.starts_at >= %s AND a.starts_at < %s
                 AND a.status IN ('confirmed', 'completed')
             WHERE pv.active
             GROUP BY pv.id, pv.display_name, pv.role
             ORDER BY pv.role, pv.display_name
            """,
            (starts_at, ends_at, starts_at, ends_at),
        ).fetchall()
        procedures = connection.execute(
            """
            SELECT p.code, p.name, count(a.id) AS visits,
                   count(a.id) FILTER (WHERE a.status = 'no_show') AS no_shows,
                   COALESCE(avg(EXTRACT(EPOCH FROM (a.completed_at - a.seated_at)) / 60)
                       FILTER (WHERE a.completed_at IS NOT NULL AND a.seated_at IS NOT NULL), 0)::numeric(10,1)
                       AS average_actual_minutes
              FROM procedures p LEFT JOIN appointments a ON a.procedure_id = p.id
               AND a.starts_at >= %s AND a.starts_at < %s
             GROUP BY p.id, p.code, p.name ORDER BY p.name
            """,
            (starts_at, ends_at),
        ).fetchall()
    total_resolved = int(summary["completed"] + summary["no_shows"] + summary["cancelled"])
    occupied = int(summary["occupied_minutes"])
    return {
        "range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "summary": {
            **summary,
            "production_cents": production,
            "capacity_minutes": capacity,
            "chair_utilization_percent": round(occupied / capacity * 100, 1) if capacity else 0,
            "no_show_rate_percent": round(int(summary["no_shows"]) / total_resolved * 100, 1)
            if total_resolved else 0,
            "cancellation_rate_percent": round(int(summary["cancelled"]) / total_resolved * 100, 1)
            if total_resolved else 0,
        },
        "providers": [
            {**row, "id": str(row["id"]),
             "revenue_per_booked_hour_cents": round(
                 int(row["production_cents"]) * 60 / int(row["booked_minutes"])
             ) if row["booked_minutes"] else 0}
            for row in providers
        ],
        "procedures": procedures,
        "method": "Descriptive on-premises operational analytics; no autonomous clinical decisions.",
    }


def _refresh_calibration_recommendations(
    connection: psycopg.Connection,
    procedure_ids: set[str],
    *,
    source_batch_id: str | None,
) -> list[str]:
    ready: list[str] = []
    minimum = max(5, settings.calibration_min_samples)
    for procedure_id in procedure_ids:
        stats = connection.execute(
            """
            SELECT count(*) AS sample_size,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY actual_minutes) AS median_minutes,
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY actual_minutes) AS p90_minutes
              FROM procedure_duration_observations
             WHERE procedure_id = %s AND outcome = 'completed' AND actual_minutes IS NOT NULL
            """,
            (procedure_id,),
        ).fetchone()
        if int(stats["sample_size"]) < minimum:
            connection.execute(
                """
                DELETE FROM calibration_recommendations
                 WHERE procedure_id = %s AND applied_at IS NULL
                """,
                (procedure_id,),
            )
            continue
        standard = max(5, round(float(stats["median_minutes"]) / 5) * 5)
        complex_minutes = max(standard, round(float(stats["p90_minutes"]) / 5) * 5)
        connection.execute(
            """
            INSERT INTO calibration_recommendations (
                procedure_id, sample_size, standard_minutes, complex_minutes, source_batch_id
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (procedure_id) DO UPDATE SET
                sample_size = EXCLUDED.sample_size,
                standard_minutes = EXCLUDED.standard_minutes,
                complex_minutes = EXCLUDED.complex_minutes,
                computed_at = transaction_timestamp(), source_batch_id = EXCLUDED.source_batch_id,
                applied_at = NULL, applied_by = NULL, approval_reason = NULL
            """,
            (procedure_id, stats["sample_size"], standard, complex_minutes, source_batch_id),
        )
        ready.append(procedure_id)
    return ready


@app.post("/api/calibration/import", status_code=201)
def import_calibration(
    body: HistoricalImportBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    with transaction() as connection:
        batch_id = connection.execute(
            """
            INSERT INTO historical_import_batches (source_name, row_count, imported_by)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (body.source_name.strip(), len(body.rows), user["id"]),
        ).fetchone()["id"]
        affected: set[str] = set()
        for observation in body.rows:
            procedure = connection.execute(
                "SELECT id FROM procedures WHERE code = %s", (observation.procedure_code,)
            ).fetchone()
            if not procedure:
                raise HTTPException(status_code=422, detail=f"Unknown procedure {observation.procedure_code}")
            doctor_id = None
            if observation.doctor_staff_code:
                doctor = connection.execute(
                    "SELECT id FROM doctors WHERE staff_code = %s", (observation.doctor_staff_code,)
                ).fetchone()
                if not doctor:
                    raise HTTPException(status_code=422, detail=f"Unknown dentist {observation.doctor_staff_code}")
                doctor_id = doctor["id"]
            connection.execute(
                """
                INSERT INTO procedure_duration_observations (
                    batch_id, procedure_id, doctor_id, service_date,
                    scheduled_minutes, actual_minutes, outcome
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (batch_id, procedure["id"], doctor_id, observation.service_date,
                 observation.scheduled_minutes, observation.actual_minutes, observation.outcome),
            )
            affected.add(str(procedure["id"]))
        ready = _refresh_calibration_recommendations(
            connection, affected, source_batch_id=str(batch_id)
        )
        append_audit(
            connection, actor_id=user["id"], event_type="calibration.imported",
            entity_type="calibration_batch", entity_id=str(batch_id),
            correlation_id=str(uuid.uuid4()),
            details={"row_count": len(body.rows), "contains_phi": False},
        )
    return {
        "batch_id": str(batch_id),
        "row_count": len(body.rows),
        "status": "staged",
        "recommendations_ready": len(ready),
        "minimum_sample_size": max(5, settings.calibration_min_samples),
    }


@app.get("/api/calibration")
def list_calibration(
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT p.code AS procedure_code, p.name, p.policy_version,
                   COALESCE(ph.standard_minutes, p.duration_minutes
                       + p.preparation_minutes + p.cleanup_minutes) AS active_standard_minutes,
                   COALESCE(ph.complex_minutes, p.duration_minutes
                       + p.preparation_minutes + p.cleanup_minutes) AS active_complex_minutes,
                   COALESCE(o.sample_size, 0) AS observed_sample_size,
                   COALESCE(o.evidence_source, 'none') AS evidence_source,
                   c.sample_size, c.standard_minutes, c.complex_minutes,
                   c.computed_at, c.applied_at
              FROM procedures p
              LEFT JOIN LATERAL (
                  SELECT sum(duration_minutes)::integer AS standard_minutes,
                         sum(COALESCE(complex_duration_minutes, duration_minutes))::integer
                             AS complex_minutes
                    FROM procedure_phase_templates
                   WHERE procedure_id = p.id AND active
              ) ph ON true
              LEFT JOIN LATERAL (
                  SELECT count(*)::integer AS sample_size,
                         CASE
                           WHEN count(*) = 0 THEN 'none'
                           WHEN count(*) FILTER (WHERE source = 'native') > 0
                            AND count(*) FILTER (WHERE source = 'import') > 0 THEN 'native_and_imported'
                           WHEN count(*) FILTER (WHERE source = 'native') > 0 THEN 'native'
                           ELSE 'imported'
                         END AS evidence_source
                    FROM procedure_duration_observations
                   WHERE procedure_id = p.id AND outcome = 'completed'
                     AND actual_minutes IS NOT NULL
              ) o ON true
              LEFT JOIN calibration_recommendations c ON c.procedure_id = p.id
             WHERE p.active
             ORDER BY p.name
            """
        ).fetchall()
    minimum = max(5, settings.calibration_min_samples)
    procedures = []
    recommendations = []
    for row in rows:
        item = dict(row)
        observed = int(item["observed_sample_size"])
        if item["applied_at"]:
            item["calibration_status"] = "approved"
        elif item["standard_minutes"] is not None and int(item["sample_size"]) >= minimum:
            item["calibration_status"] = "recommendation_ready"
        elif observed:
            item["calibration_status"] = "collecting"
        else:
            item["calibration_status"] = "defaults_active"
        item["samples_needed"] = max(minimum - observed, 0)
        item["confidence"] = "strong" if observed >= 50 else "moderate" if observed >= minimum else "insufficient"
        procedures.append(item)
        if item["standard_minutes"] is not None and int(item["sample_size"]) >= minimum:
            recommendations.append(item)
    return {
        "procedures": procedures,
        "recommendations": recommendations,
        "defaults_active": True,
        "data_required_for_scheduling": False,
        "automatic_observations_enabled": True,
        "minimum_sample_size": minimum,
        "auto_applied": False,
        "required_fields": ["procedure_code", "service_date", "scheduled_minutes", "actual_minutes", "outcome"],
        "prohibited_fields": ["patient_name", "mrn", "date_of_birth", "phone", "address"],
    }


def _scaled_phase_minutes(values: list[int], target: int) -> list[int]:
    total = sum(values)
    if total <= 0:
        raise ValueError("phase total must be positive")
    scaled = [max(5, round(value * target / total / 5) * 5) for value in values]
    difference = target - sum(scaled)
    scaled[-1] += difference
    if scaled[-1] < 5:
        deficit = 5 - scaled[-1]
        scaled[-1] = 5
        for index in range(len(scaled) - 2, -1, -1):
            available = max(0, scaled[index] - 5)
            transfer = min(available, deficit)
            scaled[index] -= transfer
            deficit -= transfer
            if not deficit:
                break
        if deficit:
            raise ValueError("calibrated duration is too short for the configured phase count")
    return scaled


@app.post("/api/calibration/{procedure_code}/apply")
def apply_calibration(
    procedure_code: str,
    body: CalibrationApplyBody,
    user: dict = Depends(require_roles("administrator", "clinician")),
):
    with transaction() as connection:
        recommendation = connection.execute(
            """
            SELECT c.*, p.id AS procedure_id
              FROM calibration_recommendations c JOIN procedures p ON p.id = c.procedure_id
             WHERE p.code = %s FOR UPDATE
            """,
            (procedure_code,),
        ).fetchone()
        if not recommendation:
            raise HTTPException(status_code=404, detail="Calibration recommendation not found")
        if int(recommendation["sample_size"]) < max(5, settings.calibration_min_samples):
            raise HTTPException(
                status_code=409,
                detail="Calibration recommendation does not meet the configured evidence threshold",
            )
        phases = connection.execute(
            """
            SELECT id, duration_minutes, complex_duration_minutes
              FROM procedure_phase_templates
             WHERE procedure_id = %s AND active ORDER BY sequence
            """,
            (recommendation["procedure_id"],),
        ).fetchall()
        if not phases:
            raise HTTPException(status_code=409, detail="Procedure has no active phase policy")
        try:
            standard = _scaled_phase_minutes(
                [row["duration_minutes"] for row in phases], recommendation["standard_minutes"]
            )
            complex_values = [row["complex_duration_minutes"] or row["duration_minutes"] for row in phases]
            complex_scaled = _scaled_phase_minutes(complex_values, recommendation["complex_minutes"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        for row, standard_minutes, complex_minutes in zip(phases, standard, complex_scaled):
            connection.execute(
                """
                UPDATE procedure_phase_templates
                   SET duration_minutes = %s, complex_duration_minutes = %s WHERE id = %s
                """,
                (standard_minutes, complex_minutes, row["id"]),
            )
        connection.execute(
            "UPDATE procedures SET duration_minutes = %s, preparation_minutes = 0, cleanup_minutes = 0, policy_version = 'calibrated-approved' WHERE id = %s",
            (recommendation["standard_minutes"], recommendation["procedure_id"]),
        )
        connection.execute(
            """
            UPDATE calibration_recommendations SET applied_at = transaction_timestamp(),
                   applied_by = %s, approval_reason = %s WHERE procedure_id = %s
            """,
            (user["id"], body.approval_reason.strip(), recommendation["procedure_id"]),
        )
        if recommendation["source_batch_id"]:
            connection.execute(
                "UPDATE historical_import_batches SET status = 'applied' WHERE id = %s",
                (recommendation["source_batch_id"],),
            )
        append_audit(
            connection, actor_id=user["id"], event_type="calibration.approved",
            entity_type="procedure", entity_id=str(recommendation["procedure_id"]),
            correlation_id=str(uuid.uuid4()),
            details={"standard_minutes": recommendation["standard_minutes"],
                     "complex_minutes": recommendation["complex_minutes"],
                     "sample_size": recommendation["sample_size"]},
        )
    return {"procedure_code": procedure_code, "status": "applied"}


@app.get("/api/audit")
def audit_log(
    user: dict = Depends(require_roles("administrator", "auditor")),
):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT a.id, a.occurred_at, a.event_type, a.entity_type, a.entity_id,
                   a.outcome, u.display_name AS actor_name
              FROM audit_events a
              LEFT JOIN app_users u ON u.id = a.actor_id
             ORDER BY a.occurred_at DESC
             LIMIT 100
            """
        ).fetchall()
    return {
        "events": [
            {
                "id": str(row["id"]),
                "occurred_at": row["occurred_at"].isoformat(),
                "event_type": row["event_type"],
                "entity_type": row["entity_type"],
                "entity_id": str(row["entity_id"]) if row["entity_id"] else None,
                "outcome": row["outcome"],
                "actor_name": row["actor_name"] or "System",
            }
            for row in rows
        ]
    }
