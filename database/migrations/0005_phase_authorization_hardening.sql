BEGIN;

CREATE OR REPLACE FUNCTION guard_confirmed_appointment_phase()
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
                   AND used_at IS NOT NULL
                   AND revoked_at IS NULL
                   AND expires_at > transaction_timestamp()
            ) INTO permission_matches;
        END IF;
        IF NOT permission_matches THEN
            RAISE EXCEPTION 'confirmed appointment phases require exact reschedule permission';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

COMMIT;
