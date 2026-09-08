BEGIN;

ALTER TABLE doctors
    ADD COLUMN max_active_rooms smallint NOT NULL DEFAULT 3
        CHECK (max_active_rooms BETWEEN 1 AND 8);

CREATE TABLE provider_shift_overrides (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    shift_date date NOT NULL,
    status text NOT NULL CHECK (status IN ('scheduled', 'off', 'cover')),
    local_start time,
    local_end time,
    covering_for_provider_id uuid REFERENCES providers(id) ON DELETE RESTRICT,
    notes text,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (provider_id, shift_date),
    CHECK (
        (status = 'off' AND local_start IS NULL AND local_end IS NULL)
        OR (status IN ('scheduled', 'cover') AND local_start IS NOT NULL
            AND local_end IS NOT NULL AND local_end > local_start)
    ),
    CHECK ((status = 'cover') = (covering_for_provider_id IS NOT NULL)),
    CHECK (covering_for_provider_id IS NULL OR covering_for_provider_id <> provider_id)
);

ALTER TABLE appointments
    ADD COLUMN arrival_type text NOT NULL DEFAULT 'scheduled'
        CHECK (arrival_type IN ('scheduled', 'walk_in')),
    ADD COLUMN checked_in_at timestamptz,
    ADD COLUMN seated_at timestamptz,
    ADD COLUMN completed_at timestamptz,
    ADD CONSTRAINT appointment_flow_order CHECK (
        (seated_at IS NULL OR checked_in_at IS NOT NULL)
        AND (seated_at IS NULL OR seated_at >= checked_in_at)
        AND (completed_at IS NULL OR completed_at >= COALESCE(seated_at, checked_in_at, starts_at))
    );

ALTER TABLE scheduling_requests
    ADD COLUMN walk_in boolean NOT NULL DEFAULT false;

ALTER TABLE recommendation_snapshots
    ADD COLUMN equipment_plan jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE appointment_equipment_reservations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    equipment_id uuid NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
    unit_number integer NOT NULL CHECK (unit_number > 0),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true,
    UNIQUE (appointment_id, equipment_id, unit_number),
    CHECK (ends_at > starts_at)
);

ALTER TABLE appointment_equipment_reservations
    ADD CONSTRAINT appointment_equipment_unit_no_overlap
    EXCLUDE USING gist (
        equipment_id WITH =,
        unit_number WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    ) WHERE (active);

CREATE OR REPLACE FUNCTION guard_confirmed_equipment_reservation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    appointment_status_value appointment_status;
    permission_id_text text;
    permission_matches boolean := false;
BEGIN
    SELECT status INTO appointment_status_value
      FROM appointments
     WHERE id = COALESCE(NEW.appointment_id, OLD.appointment_id);
    IF appointment_status_value = 'confirmed' AND TG_OP IN ('UPDATE', 'DELETE') THEN
        permission_id_text := current_setting('siligent.reschedule_permission_id', true);
        IF permission_id_text IS NOT NULL AND permission_id_text <> '' THEN
            SELECT EXISTS (
                SELECT 1 FROM reschedule_permissions
                 WHERE id = permission_id_text::uuid
                   AND appointment_id = COALESCE(NEW.appointment_id, OLD.appointment_id)
                   AND used_at IS NOT NULL AND revoked_at IS NULL
                   AND expires_at > transaction_timestamp()
            ) INTO permission_matches;
        END IF;
        IF NOT permission_matches THEN
            RAISE EXCEPTION 'confirmed equipment reservations require exact reschedule permission';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER appointment_equipment_confirmed_guard
BEFORE UPDATE OR DELETE ON appointment_equipment_reservations
FOR EACH ROW EXECUTE FUNCTION guard_confirmed_equipment_reservation();

CREATE TABLE waitlist_contact_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    waitlist_entry_id uuid NOT NULL REFERENCES waitlist_entries(id) ON DELETE RESTRICT,
    channel text NOT NULL CHECK (channel IN ('phone', 'sms', 'in_person')),
    outcome text NOT NULL CHECK (
        outcome IN ('no_answer', 'left_message', 'offered', 'accepted', 'declined')
    ),
    incentive_offered text,
    created_by uuid NOT NULL REFERENCES app_users(id),
    attempted_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE historical_import_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name text NOT NULL,
    row_count integer NOT NULL CHECK (row_count >= 0),
    status text NOT NULL DEFAULT 'staged' CHECK (status IN ('staged', 'applied', 'rejected')),
    imported_by uuid NOT NULL REFERENCES app_users(id),
    imported_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE procedure_duration_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id uuid NOT NULL REFERENCES historical_import_batches(id) ON DELETE RESTRICT,
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE RESTRICT,
    doctor_id uuid REFERENCES doctors(id) ON DELETE RESTRICT,
    service_date date NOT NULL,
    scheduled_minutes integer NOT NULL CHECK (scheduled_minutes > 0),
    actual_minutes integer CHECK (actual_minutes > 0),
    outcome text NOT NULL CHECK (outcome IN ('completed', 'cancelled', 'no_show'))
);

CREATE TABLE calibration_recommendations (
    procedure_id uuid PRIMARY KEY REFERENCES procedures(id) ON DELETE CASCADE,
    sample_size integer NOT NULL CHECK (sample_size > 0),
    standard_minutes integer NOT NULL CHECK (standard_minutes > 0),
    complex_minutes integer NOT NULL CHECK (complex_minutes >= standard_minutes),
    computed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    source_batch_id uuid NOT NULL REFERENCES historical_import_batches(id) ON DELETE RESTRICT,
    applied_at timestamptz,
    applied_by uuid REFERENCES app_users(id),
    approval_reason text,
    CHECK ((applied_at IS NULL) = (applied_by IS NULL)),
    CHECK (approval_reason IS NULL OR length(btrim(approval_reason)) >= 10)
);

CREATE INDEX provider_shift_date_idx ON provider_shift_overrides (shift_date, provider_id);
CREATE INDEX waitlist_contact_entry_idx ON waitlist_contact_attempts (waitlist_entry_id, attempted_at DESC);
CREATE INDEX duration_observation_procedure_idx ON procedure_duration_observations (procedure_id, outcome, service_date);
CREATE INDEX equipment_reservation_window_idx
    ON appointment_equipment_reservations (starts_at, ends_at) WHERE active;

COMMIT;
