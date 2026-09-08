BEGIN;

CREATE FUNCTION reject_audit_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only';
END;
$$;

CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();

CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();

CREATE FUNCTION guard_locked_appointment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    permission_id_text text;
    matched_permission_id uuid;
BEGIN
    IF OLD.status IN ('completed', 'cancelled') AND (
        NEW.patient_id IS DISTINCT FROM OLD.patient_id
        OR NEW.procedure_id IS DISTINCT FROM OLD.procedure_id
        OR NEW.doctor_id IS DISTINCT FROM OLD.doctor_id
        OR NEW.room_id IS DISTINCT FROM OLD.room_id
        OR NEW.starts_at IS DISTINCT FROM OLD.starts_at
        OR NEW.ends_at IS DISTINCT FROM OLD.ends_at
    ) THEN
        RAISE EXCEPTION 'completed or cancelled appointment history cannot be changed';
    END IF;

    IF OLD.status = 'confirmed' AND (
        NEW.patient_id IS DISTINCT FROM OLD.patient_id
        OR NEW.procedure_id IS DISTINCT FROM OLD.procedure_id
    ) THEN
        RAISE EXCEPTION 'patient and procedure cannot be replaced on a confirmed appointment';
    END IF;

    IF OLD.status = 'confirmed' AND (
        NEW.doctor_id IS DISTINCT FROM OLD.doctor_id
        OR NEW.room_id IS DISTINCT FROM OLD.room_id
        OR NEW.starts_at IS DISTINCT FROM OLD.starts_at
        OR NEW.ends_at IS DISTINCT FROM OLD.ends_at
    ) THEN
        permission_id_text := current_setting(
            'siligent.reschedule_permission_id',
            true
        );

        IF permission_id_text IS NULL OR permission_id_text = '' THEN
            RAISE EXCEPTION 'confirmed appointment requires explicit reschedule permission';
        END IF;

        SELECT id
          INTO matched_permission_id
          FROM reschedule_permissions
         WHERE id = permission_id_text::uuid
           AND appointment_id = OLD.id
           AND old_doctor_id = OLD.doctor_id
           AND new_doctor_id = NEW.doctor_id
           AND old_room_id IS NOT DISTINCT FROM OLD.room_id
           AND new_room_id IS NOT DISTINCT FROM NEW.room_id
           AND old_starts_at = OLD.starts_at
           AND old_ends_at = OLD.ends_at
           AND new_starts_at = NEW.starts_at
           AND new_ends_at = NEW.ends_at
           AND used_at IS NULL
           AND revoked_at IS NULL
           AND expires_at > transaction_timestamp()
         FOR UPDATE;

        IF matched_permission_id IS NULL THEN
            RAISE EXCEPTION 'reschedule permission is missing, expired, used, revoked, or does not match the proposed move';
        END IF;

        UPDATE reschedule_permissions
           SET used_at = transaction_timestamp()
         WHERE id = matched_permission_id;

        NEW.lock_version := OLD.lock_version + 1;
    ELSIF NEW.lock_version IS DISTINCT FROM OLD.lock_version THEN
        RAISE EXCEPTION 'appointment lock version is managed by the database';
    END IF;

    NEW.updated_at := transaction_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER appointments_guard_locked_changes
BEFORE UPDATE ON appointments
FOR EACH ROW EXECUTE FUNCTION guard_locked_appointment();

CREATE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := transaction_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER app_users_set_updated_at
BEFORE UPDATE ON app_users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER patients_set_updated_at
BEFORE UPDATE ON patients
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER doctors_set_updated_at
BEFORE UPDATE ON doctors
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER procedures_set_updated_at
BEFORE UPDATE ON procedures
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER scheduling_requests_set_updated_at
BEFORE UPDATE ON scheduling_requests
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

