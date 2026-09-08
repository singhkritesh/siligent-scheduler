BEGIN;

CREATE TYPE provider_role AS ENUM ('doctor', 'hygienist', 'assistant');
ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'no_show';

ALTER TABLE procedures
    ADD COLUMN production_cents integer NOT NULL DEFAULT 0 CHECK (production_cents >= 0),
    ADD COLUMN default_difficulty text NOT NULL DEFAULT 'standard'
        CHECK (default_difficulty IN ('standard', 'complex'));

ALTER TABLE rooms
    ADD COLUMN category text NOT NULL DEFAULT 'general',
    ADD COLUMN turnover_minutes integer NOT NULL DEFAULT 10 CHECK (turnover_minutes >= 0);

ALTER TABLE scheduling_requests
    ADD COLUMN difficulty text NOT NULL DEFAULT 'standard'
        CHECK (difficulty IN ('standard', 'complex')),
    ADD COLUMN waitlist_consent boolean NOT NULL DEFAULT false;

CREATE TABLE providers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_code text NOT NULL UNIQUE,
    display_name text NOT NULL,
    role provider_role NOT NULL,
    doctor_id uuid UNIQUE REFERENCES doctors(id) ON DELETE RESTRICT,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK ((role = 'doctor') = (doctor_id IS NOT NULL))
);

INSERT INTO providers (staff_code, display_name, role, doctor_id)
SELECT staff_code, display_name, 'doctor', id FROM doctors
ON CONFLICT (staff_code) DO NOTHING;

CREATE TABLE provider_working_hours (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id uuid NOT NULL REFERENCES providers(id),
    weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    local_start time NOT NULL,
    local_end time NOT NULL,
    effective_from date NOT NULL,
    effective_through date,
    CHECK (local_end > local_start),
    CHECK (effective_through IS NULL OR effective_through >= effective_from)
);

INSERT INTO provider_working_hours (
    provider_id, weekday, local_start, local_end, effective_from, effective_through
)
SELECT p.id, h.weekday, h.local_start, h.local_end, h.effective_from, h.effective_through
  FROM doctor_working_hours h
  JOIN providers p ON p.doctor_id = h.doctor_id;

CREATE TABLE provider_unavailability (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id uuid NOT NULL REFERENCES providers(id),
    unavailable_during tstzrange NOT NULL,
    reason_code text NOT NULL,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (NOT isempty(unavailable_during))
);

INSERT INTO provider_unavailability (provider_id, unavailable_during, reason_code, created_by)
SELECT p.id, u.unavailable_during, u.reason_code, u.created_by
  FROM doctor_unavailability u
  JOIN providers p ON p.doctor_id = u.doctor_id;

CREATE TABLE procedure_phase_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    sequence smallint NOT NULL CHECK (sequence > 0),
    code text NOT NULL,
    name text NOT NULL,
    required_role text NOT NULL
        CHECK (required_role IN ('doctor', 'hygienist', 'assistant', 'room')),
    duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
    active boolean NOT NULL DEFAULT true,
    UNIQUE (procedure_id, sequence),
    UNIQUE (procedure_id, code)
);

CREATE TABLE provider_procedure_preferences (
    provider_id uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    preference smallint NOT NULL DEFAULT 0 CHECK (preference BETWEEN -10 AND 10),
    PRIMARY KEY (provider_id, procedure_id)
);

CREATE TABLE provider_daily_targets (
    provider_id uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    target_cents integer NOT NULL CHECK (target_cents >= 0),
    effective_from date NOT NULL,
    effective_through date,
    PRIMARY KEY (provider_id, weekday, effective_from),
    CHECK (effective_through IS NULL OR effective_through >= effective_from)
);

CREATE TABLE procedure_role_production_share (
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    role provider_role NOT NULL,
    basis_points integer NOT NULL CHECK (basis_points BETWEEN 0 AND 10000),
    PRIMARY KEY (procedure_id, role)
);

CREATE TABLE emergency_capacity_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    local_start time NOT NULL,
    local_end time NOT NULL,
    slots_per_doctor smallint NOT NULL DEFAULT 1 CHECK (slots_per_doctor BETWEEN 1 AND 4),
    release_hours_before integer NOT NULL DEFAULT 2 CHECK (release_hours_before BETWEEN 0 AND 72),
    active boolean NOT NULL DEFAULT true,
    UNIQUE (weekday, local_start, local_end),
    CHECK (local_end > local_start)
);

ALTER TABLE recommendation_snapshots
    ADD COLUMN phase_plan jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN production_cents integer NOT NULL DEFAULT 0 CHECK (production_cents >= 0);

ALTER TABLE appointments DROP CONSTRAINT appointments_doctor_no_overlap;

CREATE TABLE appointment_phases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    sequence smallint NOT NULL CHECK (sequence > 0),
    phase_code text NOT NULL,
    phase_name text NOT NULL,
    role text NOT NULL CHECK (role IN ('doctor', 'hygienist', 'assistant', 'room')),
    provider_id uuid REFERENCES providers(id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true,
    UNIQUE (appointment_id, sequence),
    CHECK (ends_at > starts_at),
    CHECK ((role = 'room') = (provider_id IS NULL))
);

ALTER TABLE appointment_phases
    ADD CONSTRAINT appointment_phases_provider_no_overlap
    EXCLUDE USING gist (
        provider_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    ) WHERE (provider_id IS NOT NULL AND active);

INSERT INTO appointment_phases (
    appointment_id, sequence, phase_code, phase_name, role,
    provider_id, starts_at, ends_at, active
)
SELECT a.id, 1, 'legacy-doctor', 'Legacy doctor reservation', 'doctor',
       p.id, a.starts_at, a.ends_at, a.status IN ('held', 'confirmed')
  FROM appointments a
  JOIN providers p ON p.doctor_id = a.doctor_id;

CREATE TABLE appointment_production_credits (
    appointment_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    provider_id uuid NOT NULL REFERENCES providers(id),
    amount_cents integer NOT NULL CHECK (amount_cents >= 0),
    PRIMARY KEY (appointment_id, provider_id)
);

CREATE TABLE waitlist_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id uuid NOT NULL REFERENCES patients(id),
    procedure_id uuid NOT NULL REFERENCES procedures(id),
    preferred_doctor_id uuid REFERENCES doctors(id),
    earliest_date date NOT NULL,
    latest_date date NOT NULL,
    local_start time NOT NULL,
    local_end time NOT NULL,
    priority clinical_priority NOT NULL DEFAULT 'routine',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'offered', 'scheduled', 'declined', 'expired')),
    notes text,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (latest_date >= earliest_date),
    CHECK (local_end > local_start)
);

CREATE INDEX waitlist_active_window_idx
    ON waitlist_entries (earliest_date, latest_date, priority)
    WHERE status = 'active';

ALTER TABLE scheduling_requests
    ADD COLUMN source_waitlist_id uuid REFERENCES waitlist_entries(id);

CREATE TABLE procedure_followup_rules (
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    followup_procedure_id uuid NOT NULL REFERENCES procedures(id),
    minimum_days integer NOT NULL CHECK (minimum_days >= 0),
    maximum_days integer NOT NULL CHECK (maximum_days >= minimum_days),
    reason text NOT NULL,
    PRIMARY KEY (procedure_id, followup_procedure_id)
);

CREATE TABLE appointment_links (
    predecessor_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    successor_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    relationship text NOT NULL CHECK (relationship IN ('followup', 'lab_return', 'treatment_plan')),
    minimum_days integer NOT NULL DEFAULT 0 CHECK (minimum_days >= 0),
    maximum_days integer,
    PRIMARY KEY (predecessor_id, successor_id),
    CHECK (predecessor_id <> successor_id),
    CHECK (maximum_days IS NULL OR maximum_days >= minimum_days)
);

CREATE FUNCTION guard_confirmed_appointment_phase()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    appointment_status_value appointment_status;
    permission_id_text text;
BEGIN
    SELECT status INTO appointment_status_value
      FROM appointments
     WHERE id = COALESCE(NEW.appointment_id, OLD.appointment_id);
    IF appointment_status_value = 'confirmed' AND TG_OP IN ('UPDATE', 'DELETE') THEN
        permission_id_text := current_setting('siligent.reschedule_permission_id', true);
        IF permission_id_text IS NULL OR permission_id_text = '' THEN
            RAISE EXCEPTION 'confirmed appointment phases require explicit reschedule permission';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER appointment_phases_confirmed_guard
BEFORE UPDATE OR DELETE ON appointment_phases
FOR EACH ROW EXECUTE FUNCTION guard_confirmed_appointment_phase();

CREATE INDEX appointment_phases_calendar_idx
    ON appointment_phases (starts_at, ends_at) WHERE active;
CREATE INDEX provider_working_hours_lookup_idx
    ON provider_working_hours (provider_id, weekday, effective_from);
CREATE INDEX provider_unavailability_lookup_idx
    ON provider_unavailability USING gist (provider_id, unavailable_during);

COMMIT;
