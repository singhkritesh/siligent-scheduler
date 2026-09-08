BEGIN;

-- History metadata is mutable only as part of an authorized active-to-terminal
-- transition. This prevents direct updates from forging release/fulfillment.
CREATE OR REPLACE FUNCTION guard_reserved_procedure_block_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    authorized_id text;
    history_changed boolean;
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

    history_changed := NEW.fulfilled_by_appointment_id IS DISTINCT FROM OLD.fulfilled_by_appointment_id
        OR NEW.released_by IS DISTINCT FROM OLD.released_by
        OR NEW.released_at IS DISTINCT FROM OLD.released_at
        OR NEW.release_reason IS DISTINCT FROM OLD.release_reason;

    IF NEW.status IS DISTINCT FROM OLD.status OR history_changed THEN
        authorized_id := current_setting('siligent.reserved_block_change_id', true);
        IF authorized_id IS NULL OR authorized_id = '' OR authorized_id::uuid <> OLD.id THEN
            RAISE EXCEPTION 'reserved procedure block status change requires exact authorization';
        END IF;
        IF NEW.status IS NOT DISTINCT FROM OLD.status
           OR OLD.status <> 'active'
           OR NEW.status NOT IN ('fulfilled', 'released') THEN
            RAISE EXCEPTION 'reserved procedure block status transition is invalid';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- Equipment may be the only protected resource that intersects a candidate.
-- Validate and atomically consume the exact permission in that case.
CREATE OR REPLACE FUNCTION enforce_reserved_equipment_block()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    appointment_row appointments%ROWTYPE;
    block_row reserved_procedure_blocks%ROWTYPE;
    permission_ids text;
    permission_row reserved_block_override_permissions%ROWTYPE;
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
        SELECT p.* INTO permission_row
          FROM reserved_block_override_permissions p
         WHERE permission_ids IS NOT NULL AND permission_ids <> ''
           AND p.id::text = ANY(string_to_array(permission_ids, ','))
           AND p.block_id = block_row.id
           AND p.scheduling_request_id = appointment_row.scheduling_request_id
           AND p.doctor_id = appointment_row.doctor_id
           AND p.procedure_id = appointment_row.procedure_id
           AND p.room_id = appointment_row.room_id
           AND p.starts_at = appointment_row.starts_at
           AND p.ends_at = appointment_row.ends_at
           AND p.revoked_at IS NULL
           AND p.expires_at > transaction_timestamp()
           AND (
               (p.used_at IS NULL AND p.appointment_id IS NULL)
               OR (p.used_at IS NOT NULL AND p.appointment_id = NEW.appointment_id)
           )
         FOR UPDATE;
        IF permission_row.id IS NULL THEN
            RAISE EXCEPTION 'equipment unit conflicts with a reserved procedure block';
        END IF;
        IF permission_row.used_at IS NULL THEN
            UPDATE reserved_block_override_permissions
               SET used_at = transaction_timestamp(), appointment_id = NEW.appointment_id
             WHERE id = permission_row.id;
        END IF;
        permission_row := NULL;
    END LOOP;
    RETURN NEW;
END;
$$;

COMMIT;
