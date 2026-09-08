BEGIN;

CREATE TABLE vacancy_recovery_chains (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_appointment_id uuid NOT NULL UNIQUE
        REFERENCES appointments(id) ON DELETE RESTRICT,
    current_doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    current_room_id uuid REFERENCES rooms(id) ON DELETE RESTRICT,
    current_starts_at timestamptz NOT NULL,
    current_ends_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'stopped')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    step_count integer NOT NULL DEFAULT 0 CHECK (step_count >= 0),
    started_by uuid NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
    started_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    ended_by uuid REFERENCES app_users(id) ON DELETE RESTRICT,
    ended_at timestamptz,
    stop_reason text,
    CHECK (current_ends_at > current_starts_at),
    CHECK (
        (status = 'active' AND ended_by IS NULL AND ended_at IS NULL AND stop_reason IS NULL)
        OR
        (status <> 'active' AND ended_by IS NOT NULL AND ended_at IS NOT NULL
         AND length(btrim(stop_reason)) >= 10)
    )
);

CREATE TABLE vacancy_recovery_offers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id uuid NOT NULL REFERENCES vacancy_recovery_chains(id) ON DELETE RESTRICT,
    chain_version integer NOT NULL CHECK (chain_version > 0),
    appointment_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    recommendation_id uuid NOT NULL UNIQUE
        REFERENCES recommendation_snapshots(id) ON DELETE RESTRICT,
    old_lock_version integer NOT NULL CHECK (old_lock_version >= 0),
    old_doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    old_room_id uuid REFERENCES rooms(id) ON DELETE RESTRICT,
    old_starts_at timestamptz NOT NULL,
    old_ends_at timestamptz NOT NULL,
    target_doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    target_room_id uuid REFERENCES rooms(id) ON DELETE RESTRICT,
    target_starts_at timestamptz NOT NULL,
    target_ends_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'consumed', 'invalidated')),
    created_by uuid NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    CHECK (old_ends_at > old_starts_at),
    CHECK (target_ends_at > target_starts_at),
    CHECK (expires_at > created_at),
    CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
);

CREATE INDEX vacancy_recovery_offers_open_idx
    ON vacancy_recovery_offers (chain_id, chain_version, expires_at)
    WHERE status = 'open';

CREATE TABLE vacancy_recovery_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id uuid NOT NULL REFERENCES vacancy_recovery_chains(id) ON DELETE RESTRICT,
    sequence integer NOT NULL CHECK (sequence > 0),
    offer_id uuid NOT NULL UNIQUE REFERENCES vacancy_recovery_offers(id) ON DELETE RESTRICT,
    appointment_id uuid NOT NULL REFERENCES appointments(id) ON DELETE RESTRICT,
    reschedule_permission_id uuid NOT NULL UNIQUE
        REFERENCES reschedule_permissions(id) ON DELETE RESTRICT,
    vacancy_doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    vacancy_room_id uuid REFERENCES rooms(id) ON DELETE RESTRICT,
    vacancy_starts_at timestamptz NOT NULL,
    vacancy_ends_at timestamptz NOT NULL,
    released_doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    released_room_id uuid REFERENCES rooms(id) ON DELETE RESTRICT,
    released_starts_at timestamptz NOT NULL,
    released_ends_at timestamptz NOT NULL,
    permission_method text NOT NULL
        CHECK (permission_method IN ('phone', 'sms', 'in_person', 'portal')),
    permission_confirmed boolean NOT NULL CHECK (permission_confirmed),
    authorization_reason text NOT NULL CHECK (length(btrim(authorization_reason)) >= 10),
    moved_by uuid NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
    moved_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (chain_id, sequence),
    CHECK (vacancy_ends_at > vacancy_starts_at),
    CHECK (released_ends_at > released_starts_at),
    CHECK (released_starts_at > vacancy_starts_at)
);

CREATE FUNCTION validate_vacancy_recovery_chain_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    source appointments%ROWTYPE;
BEGIN
    SELECT * INTO source FROM appointments
     WHERE id = NEW.source_appointment_id FOR SHARE;
    IF source.id IS NULL OR source.status <> 'cancelled' THEN
        RAISE EXCEPTION 'vacancy recovery requires a cancelled appointment';
    END IF;
    IF source.doctor_id <> NEW.current_doctor_id
       OR source.room_id IS DISTINCT FROM NEW.current_room_id
       OR source.starts_at <> NEW.current_starts_at
       OR source.ends_at <> NEW.current_ends_at THEN
        RAISE EXCEPTION 'vacancy recovery must start from the exact cancelled slot';
    END IF;
    IF NEW.current_starts_at <= transaction_timestamp() THEN
        RAISE EXCEPTION 'vacancy recovery requires a future slot';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER vacancy_recovery_chain_insert_guard
BEFORE INSERT ON vacancy_recovery_chains
FOR EACH ROW EXECUTE FUNCTION validate_vacancy_recovery_chain_insert();

CREATE FUNCTION reject_vacancy_recovery_step_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'vacancy recovery steps are append-only';
END;
$$;

CREATE TRIGGER vacancy_recovery_steps_no_update
BEFORE UPDATE ON vacancy_recovery_steps
FOR EACH ROW EXECUTE FUNCTION reject_vacancy_recovery_step_mutation();

CREATE TRIGGER vacancy_recovery_steps_no_delete
BEFORE DELETE ON vacancy_recovery_steps
FOR EACH ROW EXECUTE FUNCTION reject_vacancy_recovery_step_mutation();

COMMIT;
