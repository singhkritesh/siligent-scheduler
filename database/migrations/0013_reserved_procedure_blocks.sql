BEGIN;

CREATE TYPE reserved_block_status AS ENUM ('active', 'fulfilled', 'released');

CREATE TABLE reserved_procedure_blocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE RESTRICT,
    room_id uuid REFERENCES rooms(id) ON DELETE RESTRICT,
    equipment_id uuid REFERENCES equipment(id) ON DELETE RESTRICT,
    equipment_unit_number integer,
    reserved_during tstzrange NOT NULL,
    release_at timestamptz,
    status reserved_block_status NOT NULL DEFAULT 'active',
    reason text NOT NULL CHECK (length(btrim(reason)) >= 3),
    created_by uuid NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    fulfilled_by_appointment_id uuid REFERENCES appointments(id) ON DELETE RESTRICT,
    released_by uuid REFERENCES app_users(id) ON DELETE RESTRICT,
    released_at timestamptz,
    release_reason text,
    CHECK (NOT isempty(reserved_during)),
    CHECK ((equipment_id IS NULL) = (equipment_unit_number IS NULL)),
    CHECK (equipment_unit_number IS NULL OR equipment_unit_number > 0),
    CHECK (release_at IS NULL OR release_at < upper(reserved_during)),
    CHECK (
        (status = 'active' AND fulfilled_by_appointment_id IS NULL
                           AND released_by IS NULL AND released_at IS NULL)
        OR (status = 'fulfilled' AND fulfilled_by_appointment_id IS NOT NULL
                              AND released_by IS NULL AND released_at IS NULL)
        OR (status = 'released' AND fulfilled_by_appointment_id IS NULL
                             AND released_at IS NOT NULL
                             AND length(btrim(release_reason)) >= 3)
    )
);

ALTER TABLE reserved_procedure_blocks
    ADD CONSTRAINT reserved_blocks_doctor_no_overlap
    EXCLUDE USING gist (
        doctor_id WITH =,
        reserved_during WITH &&
    ) WHERE (status = 'active');

ALTER TABLE reserved_procedure_blocks
    ADD CONSTRAINT reserved_blocks_room_no_overlap
    EXCLUDE USING gist (
        room_id WITH =,
        reserved_during WITH &&
    ) WHERE (room_id IS NOT NULL AND status = 'active');

ALTER TABLE reserved_procedure_blocks
    ADD CONSTRAINT reserved_blocks_equipment_no_overlap
    EXCLUDE USING gist (
        equipment_id WITH =,
        equipment_unit_number WITH =,
        reserved_during WITH &&
    ) WHERE (equipment_id IS NOT NULL AND status = 'active');

CREATE TABLE reserved_block_override_permissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    block_id uuid NOT NULL REFERENCES reserved_procedure_blocks(id) ON DELETE RESTRICT,
    recommendation_id uuid NOT NULL REFERENCES recommendation_snapshots(id) ON DELETE RESTRICT,
    scheduling_request_id uuid NOT NULL REFERENCES scheduling_requests(id) ON DELETE RESTRICT,
    doctor_id uuid NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
    procedure_id uuid NOT NULL REFERENCES procedures(id) ON DELETE RESTRICT,
    room_id uuid NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    granted_by uuid NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
    reason text NOT NULL CHECK (length(btrim(reason)) >= 10),
    granted_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    appointment_id uuid REFERENCES appointments(id) ON DELETE RESTRICT,
    revoked_at timestamptz,
    UNIQUE (block_id, recommendation_id),
    CHECK (ends_at > starts_at),
    CHECK (expires_at > granted_at),
    CHECK (used_at IS NULL OR revoked_at IS NULL),
    CHECK ((used_at IS NULL) = (appointment_id IS NULL))
);

ALTER TABLE recommendation_snapshots
    ADD COLUMN reserved_block_conflicts jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN requires_reserved_block_override boolean NOT NULL DEFAULT false;

CREATE FUNCTION validate_reserved_procedure_block_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    configured_quantity integer;
BEGIN
    IF NEW.status <> 'active' THEN
        RAISE EXCEPTION 'new reserved procedure blocks must be active';
    END IF;

    IF NEW.equipment_id IS NOT NULL THEN
        SELECT quantity INTO configured_quantity
          FROM equipment WHERE id = NEW.equipment_id AND active;
        IF configured_quantity IS NULL
           OR NEW.equipment_unit_number > configured_quantity THEN
            RAISE EXCEPTION 'reserved equipment unit exceeds configured capacity';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM procedure_equipment_requirements
             WHERE procedure_id = NEW.procedure_id
               AND equipment_id = NEW.equipment_id
        ) THEN
            RAISE EXCEPTION 'reserved equipment is not required by the selected procedure';
        END IF;
    END IF;

    IF EXISTS (
        SELECT 1 FROM appointments a
         WHERE a.status IN ('held', 'confirmed')
           AND (a.doctor_id = NEW.doctor_id
                OR (NEW.room_id IS NOT NULL AND a.room_id = NEW.room_id))
           AND tstzrange(a.starts_at, a.ends_at, '[)') && NEW.reserved_during
    ) OR EXISTS (
        SELECT 1 FROM appointment_equipment_reservations er
         WHERE NEW.equipment_id IS NOT NULL
           AND er.active
           AND er.equipment_id = NEW.equipment_id
           AND er.unit_number = NEW.equipment_unit_number
           AND tstzrange(er.starts_at, er.ends_at, '[)') && NEW.reserved_during
    ) THEN
        RAISE EXCEPTION 'reserved block conflicts with an existing appointment';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER reserved_procedure_blocks_insert_guard
BEFORE INSERT ON reserved_procedure_blocks
FOR EACH ROW EXECUTE FUNCTION validate_reserved_procedure_block_insert();

CREATE FUNCTION guard_reserved_procedure_block_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    authorized_id text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'reserved procedure blocks cannot be deleted';
    END IF;

    IF NEW.doctor_id IS DISTINCT FROM OLD.doctor_id
       OR NEW.procedure_id IS DISTINCT FROM OLD.procedure_id
       OR NEW.room_id IS DISTINCT FROM OLD.room_id
       OR NEW.equipment_id IS DISTINCT FROM OLD.equipment_id
       OR NEW.equipment_unit_number IS DISTINCT FROM OLD.equipment_unit_number
       OR NEW.reserved_during IS DISTINCT FROM OLD.reserved_during
       OR NEW.release_at IS DISTINCT FROM OLD.release_at
       OR NEW.reason IS DISTINCT FROM OLD.reason
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'reserved procedure block identity is immutable; release and replace it';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        authorized_id := current_setting('siligent.reserved_block_change_id', true);
        IF authorized_id IS NULL OR authorized_id = '' OR authorized_id::uuid <> OLD.id THEN
            RAISE EXCEPTION 'reserved procedure block status change requires exact authorization';
        END IF;
        IF OLD.status <> 'active' OR NEW.status NOT IN ('fulfilled', 'released') THEN
            RAISE EXCEPTION 'reserved procedure block status transition is invalid';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER reserved_procedure_blocks_change_guard
BEFORE UPDATE OR DELETE ON reserved_procedure_blocks
FOR EACH ROW EXECUTE FUNCTION guard_reserved_procedure_block_change();

CREATE FUNCTION enforce_reserved_blocks_on_appointment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    block_row reserved_procedure_blocks%ROWTYPE;
    permission_ids text;
    permission_id uuid;
BEGIN
    IF NEW.status NOT IN ('held', 'confirmed') THEN
        RETURN NEW;
    END IF;

    FOR block_row IN
        SELECT b.* FROM reserved_procedure_blocks b
         WHERE b.status = 'active'
           AND (b.release_at IS NULL OR b.release_at > transaction_timestamp())
           AND (b.doctor_id = NEW.doctor_id
                OR (b.room_id IS NOT NULL AND b.room_id = NEW.room_id))
           AND b.reserved_during && tstzrange(NEW.starts_at, NEW.ends_at, '[)')
         FOR UPDATE
    LOOP
        IF block_row.doctor_id = NEW.doctor_id
           AND block_row.procedure_id = NEW.procedure_id
           AND block_row.reserved_during @> tstzrange(NEW.starts_at, NEW.ends_at, '[)')
           AND (block_row.room_id IS NULL OR block_row.room_id = NEW.room_id) THEN
            CONTINUE;
        END IF;

        permission_ids := current_setting(
            'siligent.reserved_block_override_permission_ids', true
        );
        SELECT p.id INTO permission_id
          FROM reserved_block_override_permissions p
         WHERE permission_ids IS NOT NULL AND permission_ids <> ''
           AND p.id::text = ANY(string_to_array(permission_ids, ','))
           AND p.block_id = block_row.id
           AND p.scheduling_request_id = NEW.scheduling_request_id
           AND p.doctor_id = NEW.doctor_id
           AND p.procedure_id = NEW.procedure_id
           AND p.room_id = NEW.room_id
           AND p.starts_at = NEW.starts_at
           AND p.ends_at = NEW.ends_at
           AND p.used_at IS NULL AND p.revoked_at IS NULL
           AND p.expires_at > transaction_timestamp()
         FOR UPDATE;
        IF permission_id IS NULL THEN
            RAISE EXCEPTION 'appointment conflicts with a reserved procedure block';
        END IF;
        UPDATE reserved_block_override_permissions
           SET used_at = transaction_timestamp(), appointment_id = NEW.id
         WHERE id = permission_id;
        permission_id := NULL;
    END LOOP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER appointments_reserved_block_guard
BEFORE INSERT OR UPDATE OF doctor_id, procedure_id, room_id, starts_at, ends_at, status
ON appointments
FOR EACH ROW EXECUTE FUNCTION enforce_reserved_blocks_on_appointment();

CREATE FUNCTION enforce_reserved_equipment_block()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    appointment_row appointments%ROWTYPE;
    block_row reserved_procedure_blocks%ROWTYPE;
    permission_ids text;
    permission_id uuid;
BEGIN
    IF NOT NEW.active THEN
        RETURN NEW;
    END IF;
    SELECT * INTO appointment_row FROM appointments WHERE id = NEW.appointment_id;
    IF appointment_row.status NOT IN ('held', 'confirmed') THEN
        RETURN NEW;
    END IF;

    FOR block_row IN
        SELECT b.* FROM reserved_procedure_blocks b
         WHERE b.status = 'active'
           AND (b.release_at IS NULL OR b.release_at > transaction_timestamp())
           AND b.equipment_id = NEW.equipment_id
           AND b.equipment_unit_number = NEW.unit_number
           AND b.reserved_during && tstzrange(NEW.starts_at, NEW.ends_at, '[)')
         FOR UPDATE
    LOOP
        IF block_row.doctor_id = appointment_row.doctor_id
           AND block_row.procedure_id = appointment_row.procedure_id
           AND block_row.reserved_during @> tstzrange(appointment_row.starts_at, appointment_row.ends_at, '[)')
           AND (block_row.room_id IS NULL OR block_row.room_id = appointment_row.room_id) THEN
            CONTINUE;
        END IF;

        permission_ids := current_setting(
            'siligent.reserved_block_override_permission_ids', true
        );
        SELECT p.id INTO permission_id
          FROM reserved_block_override_permissions p
         WHERE permission_ids IS NOT NULL AND permission_ids <> ''
           AND p.id::text = ANY(string_to_array(permission_ids, ','))
           AND p.block_id = block_row.id
           AND p.appointment_id = NEW.appointment_id
           AND p.used_at IS NOT NULL AND p.revoked_at IS NULL
           AND p.expires_at > transaction_timestamp()
         FOR UPDATE;
        IF permission_id IS NULL THEN
            RAISE EXCEPTION 'equipment unit conflicts with a reserved procedure block';
        END IF;
        permission_id := NULL;
    END LOOP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER appointment_equipment_reserved_block_guard
BEFORE INSERT OR UPDATE OF equipment_id, unit_number, starts_at, ends_at, active
ON appointment_equipment_reservations
FOR EACH ROW EXECUTE FUNCTION enforce_reserved_equipment_block();

CREATE INDEX reserved_blocks_window_idx
    ON reserved_procedure_blocks USING gist (reserved_during)
    WHERE status = 'active';
CREATE INDEX reserved_block_override_recommendation_idx
    ON reserved_block_override_permissions (recommendation_id, expires_at);

COMMIT;
