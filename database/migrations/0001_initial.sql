BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_role AS ENUM (
    'administrator',
    'scheduler',
    'clinician',
    'auditor'
);

CREATE TYPE request_status AS ENUM (
    'pending',
    'scheduled',
    'closed',
    'cancelled'
);

CREATE TYPE clinical_priority AS ENUM (
    'routine',
    'priority',
    'urgent',
    'manual_review'
);

CREATE TYPE appointment_status AS ENUM (
    'proposed',
    'held',
    'confirmed',
    'completed',
    'cancelled'
);

CREATE TABLE practice_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    practice_name text NOT NULL,
    timezone text NOT NULL,
    scheduling_horizon_days integer NOT NULL DEFAULT 365
        CHECK (scheduling_horizon_days BETWEEN 1 AND 366),
    hold_duration_minutes integer NOT NULL DEFAULT 10
        CHECK (hold_duration_minutes BETWEEN 1 AND 120),
    policy_version text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE app_users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_subject text NOT NULL UNIQUE,
    display_name text NOT NULL,
    role user_role NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE patients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    medical_record_number text NOT NULL UNIQUE,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE doctors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_code text NOT NULL UNIQUE,
    display_name text NOT NULL,
    specialty text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE procedures (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    required_specialty text,
    duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
    preparation_minutes integer NOT NULL DEFAULT 0
        CHECK (preparation_minutes >= 0),
    cleanup_minutes integer NOT NULL DEFAULT 0
        CHECK (cleanup_minutes >= 0),
    active boolean NOT NULL DEFAULT true,
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE rooms (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE equipment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    quantity integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE doctor_procedure_qualifications (
    doctor_id uuid NOT NULL REFERENCES doctors(id),
    procedure_id uuid NOT NULL REFERENCES procedures(id),
    effective_from date NOT NULL,
    effective_through date,
    approved_by uuid NOT NULL REFERENCES app_users(id),
    PRIMARY KEY (doctor_id, procedure_id, effective_from),
    CHECK (effective_through IS NULL OR effective_through >= effective_from)
);

CREATE TABLE procedure_equipment_requirements (
    procedure_id uuid NOT NULL REFERENCES procedures(id),
    equipment_id uuid NOT NULL REFERENCES equipment(id),
    quantity integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
    PRIMARY KEY (procedure_id, equipment_id)
);

CREATE TABLE doctor_working_hours (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id uuid NOT NULL REFERENCES doctors(id),
    weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    local_start time NOT NULL,
    local_end time NOT NULL,
    effective_from date NOT NULL,
    effective_through date,
    CHECK (local_end > local_start),
    CHECK (effective_through IS NULL OR effective_through >= effective_from)
);

CREATE TABLE doctor_unavailability (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id uuid NOT NULL REFERENCES doctors(id),
    unavailable_during tstzrange NOT NULL,
    reason_code text NOT NULL,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (NOT isempty(unavailable_during))
);

CREATE TABLE practice_closures (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    closed_during tstzrange NOT NULL,
    reason_code text NOT NULL,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (NOT isempty(closed_during))
);

CREATE TABLE scheduling_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES patients(id),
    procedure_id uuid REFERENCES procedures(id),
    condition_summary text,
    normalized_intake jsonb NOT NULL DEFAULT '{}'::jsonb,
    normalization_model_id text,
    normalization_confidence numeric(5,4)
        CHECK (
            normalization_confidence IS NULL
            OR normalization_confidence BETWEEN 0 AND 1
        ),
    staff_confirmed_intake boolean NOT NULL DEFAULT false,
    priority clinical_priority NOT NULL DEFAULT 'manual_review',
    earliest_date date,
    target_date date,
    latest_date date,
    status request_status NOT NULL DEFAULT 'pending',
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (
        earliest_date IS NULL OR latest_date IS NULL OR earliest_date <= latest_date
    ),
    CHECK (
        target_date IS NULL OR earliest_date IS NULL OR target_date >= earliest_date
    ),
    CHECK (
        target_date IS NULL OR latest_date IS NULL OR target_date <= latest_date
    )
);

CREATE TABLE patient_availability (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduling_request_id uuid NOT NULL
        REFERENCES scheduling_requests(id) ON DELETE CASCADE,
    available_during tstzrange NOT NULL,
    preference_weight smallint NOT NULL DEFAULT 0
        CHECK (preference_weight BETWEEN -100 AND 100),
    CHECK (NOT isempty(available_during))
);

CREATE TABLE appointments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduling_request_id uuid REFERENCES scheduling_requests(id),
    patient_id uuid NOT NULL REFERENCES patients(id),
    procedure_id uuid NOT NULL REFERENCES procedures(id),
    doctor_id uuid NOT NULL REFERENCES doctors(id),
    room_id uuid REFERENCES rooms(id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    practice_timezone text NOT NULL,
    status appointment_status NOT NULL DEFAULT 'proposed',
    hold_expires_at timestamptz,
    lock_version integer NOT NULL DEFAULT 0 CHECK (lock_version >= 0),
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (ends_at > starts_at),
    CHECK (
        (status = 'held' AND hold_expires_at IS NOT NULL)
        OR (status <> 'held' AND hold_expires_at IS NULL)
    )
);

ALTER TABLE appointments
    ADD CONSTRAINT appointments_doctor_no_overlap
    EXCLUDE USING gist (
        doctor_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    ) WHERE (status IN ('held', 'confirmed'));

ALTER TABLE appointments
    ADD CONSTRAINT appointments_patient_no_overlap
    EXCLUDE USING gist (
        patient_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    ) WHERE (status IN ('held', 'confirmed'));

ALTER TABLE appointments
    ADD CONSTRAINT appointments_room_no_overlap
    EXCLUDE USING gist (
        room_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    ) WHERE (room_id IS NOT NULL AND status IN ('held', 'confirmed'));

CREATE TABLE appointment_equipment (
    appointment_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    equipment_id uuid NOT NULL REFERENCES equipment(id),
    quantity integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
    PRIMARY KEY (appointment_id, equipment_id)
);

CREATE TABLE reschedule_permissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id uuid NOT NULL REFERENCES appointments(id),
    old_doctor_id uuid NOT NULL REFERENCES doctors(id),
    new_doctor_id uuid NOT NULL REFERENCES doctors(id),
    old_room_id uuid REFERENCES rooms(id),
    new_room_id uuid REFERENCES rooms(id),
    old_starts_at timestamptz NOT NULL,
    old_ends_at timestamptz NOT NULL,
    new_starts_at timestamptz NOT NULL,
    new_ends_at timestamptz NOT NULL,
    granted_by uuid NOT NULL REFERENCES app_users(id),
    reason text NOT NULL CHECK (length(btrim(reason)) >= 10),
    granted_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    revoked_at timestamptz,
    CHECK (old_ends_at > old_starts_at),
    CHECK (new_ends_at > new_starts_at),
    CHECK (expires_at > granted_at),
    CHECK (used_at IS NULL OR revoked_at IS NULL)
);

CREATE UNIQUE INDEX reschedule_permissions_one_open_per_appointment
    ON reschedule_permissions (appointment_id)
    WHERE used_at IS NULL AND revoked_at IS NULL;

CREATE TABLE appointment_status_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id uuid NOT NULL REFERENCES appointments(id),
    previous_status appointment_status,
    new_status appointment_status NOT NULL,
    actor_id uuid NOT NULL REFERENCES app_users(id),
    reason_code text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id uuid REFERENCES app_users(id),
    event_type text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid,
    correlation_id uuid NOT NULL,
    source_address inet,
    outcome text NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    previous_hash bytea,
    event_hash bytea NOT NULL
);

CREATE INDEX scheduling_requests_queue_idx
    ON scheduling_requests (priority, created_at)
    WHERE status = 'pending';

CREATE INDEX appointments_calendar_idx
    ON appointments (starts_at, ends_at)
    WHERE status IN ('held', 'confirmed');

CREATE INDEX audit_events_entity_idx
    ON audit_events (entity_type, entity_id, occurred_at);

COMMIT;

