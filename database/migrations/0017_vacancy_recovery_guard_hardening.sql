BEGIN;

CREATE FUNCTION validate_vacancy_recovery_step_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    chain_row vacancy_recovery_chains%ROWTYPE;
    offer_row vacancy_recovery_offers%ROWTYPE;
    appointment_row appointments%ROWTYPE;
    permission_row reschedule_permissions%ROWTYPE;
BEGIN
    SELECT * INTO chain_row FROM vacancy_recovery_chains
     WHERE id = NEW.chain_id FOR UPDATE;
    SELECT * INTO offer_row FROM vacancy_recovery_offers
     WHERE id = NEW.offer_id FOR UPDATE;
    SELECT * INTO appointment_row FROM appointments
     WHERE id = NEW.appointment_id FOR SHARE;
    SELECT * INTO permission_row FROM reschedule_permissions
     WHERE id = NEW.reschedule_permission_id FOR SHARE;

    IF chain_row.id IS NULL OR chain_row.status <> 'active'
       OR NEW.sequence <> chain_row.step_count + 1 THEN
        RAISE EXCEPTION 'vacancy recovery step requires the next active chain sequence';
    END IF;
    IF offer_row.id IS NULL OR offer_row.status <> 'open'
       OR offer_row.expires_at <= transaction_timestamp()
       OR offer_row.chain_id <> NEW.chain_id
       OR offer_row.chain_version <> chain_row.version
       OR offer_row.appointment_id <> NEW.appointment_id THEN
        RAISE EXCEPTION 'vacancy recovery step requires its current open offer';
    END IF;
    IF offer_row.target_doctor_id <> chain_row.current_doctor_id
       OR offer_row.target_room_id IS DISTINCT FROM chain_row.current_room_id
       OR offer_row.target_starts_at <> chain_row.current_starts_at
       OR offer_row.target_ends_at > chain_row.current_ends_at
       OR NEW.vacancy_doctor_id <> chain_row.current_doctor_id
       OR NEW.vacancy_room_id IS DISTINCT FROM chain_row.current_room_id
       OR NEW.vacancy_starts_at <> chain_row.current_starts_at
       OR NEW.vacancy_ends_at <> chain_row.current_ends_at THEN
        RAISE EXCEPTION 'vacancy recovery step must fill the exact current vacancy';
    END IF;
    IF NEW.released_doctor_id <> offer_row.old_doctor_id
       OR NEW.released_room_id IS DISTINCT FROM offer_row.old_room_id
       OR NEW.released_starts_at <> offer_row.old_starts_at
       OR NEW.released_ends_at <> offer_row.old_ends_at THEN
        RAISE EXCEPTION 'vacancy recovery step must release the selected appointment old slot';
    END IF;
    IF appointment_row.id IS NULL OR appointment_row.status <> 'confirmed'
       OR appointment_row.doctor_id <> offer_row.target_doctor_id
       OR appointment_row.room_id IS DISTINCT FROM offer_row.target_room_id
       OR appointment_row.starts_at <> offer_row.target_starts_at
       OR appointment_row.ends_at <> offer_row.target_ends_at THEN
        RAISE EXCEPTION 'vacancy recovery appointment was not moved to the exact offer';
    END IF;
    IF permission_row.id IS NULL OR permission_row.used_at IS NULL
       OR permission_row.revoked_at IS NOT NULL
       OR permission_row.appointment_id <> NEW.appointment_id
       OR permission_row.granted_by <> NEW.moved_by
       OR permission_row.old_doctor_id <> offer_row.old_doctor_id
       OR permission_row.old_room_id IS DISTINCT FROM offer_row.old_room_id
       OR permission_row.old_starts_at <> offer_row.old_starts_at
       OR permission_row.old_ends_at <> offer_row.old_ends_at
       OR permission_row.new_doctor_id <> offer_row.target_doctor_id
       OR permission_row.new_room_id IS DISTINCT FROM offer_row.target_room_id
       OR permission_row.new_starts_at <> offer_row.target_starts_at
       OR permission_row.new_ends_at <> offer_row.target_ends_at THEN
        RAISE EXCEPTION 'vacancy recovery step requires its exact consumed permission';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER vacancy_recovery_steps_insert_guard
BEFORE INSERT ON vacancy_recovery_steps
FOR EACH ROW EXECUTE FUNCTION validate_vacancy_recovery_step_insert();

CREATE FUNCTION guard_vacancy_recovery_offer_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'vacancy recovery offers cannot be deleted';
    END IF;
    IF OLD.status <> 'open'
       OR NEW.id <> OLD.id
       OR NEW.chain_id <> OLD.chain_id
       OR NEW.chain_version <> OLD.chain_version
       OR NEW.appointment_id <> OLD.appointment_id
       OR NEW.recommendation_id <> OLD.recommendation_id
       OR NEW.old_lock_version <> OLD.old_lock_version
       OR NEW.old_doctor_id <> OLD.old_doctor_id
       OR NEW.old_room_id IS DISTINCT FROM OLD.old_room_id
       OR NEW.old_starts_at <> OLD.old_starts_at
       OR NEW.old_ends_at <> OLD.old_ends_at
       OR NEW.target_doctor_id <> OLD.target_doctor_id
       OR NEW.target_room_id IS DISTINCT FROM OLD.target_room_id
       OR NEW.target_starts_at <> OLD.target_starts_at
       OR NEW.target_ends_at <> OLD.target_ends_at
       OR NEW.created_by <> OLD.created_by
       OR NEW.created_at <> OLD.created_at
       OR NEW.expires_at <> OLD.expires_at
       OR NEW.status NOT IN ('consumed', 'invalidated') THEN
        RAISE EXCEPTION 'vacancy recovery offer snapshot is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER vacancy_recovery_offers_update_guard
BEFORE UPDATE ON vacancy_recovery_offers
FOR EACH ROW EXECUTE FUNCTION guard_vacancy_recovery_offer_mutation();

CREATE TRIGGER vacancy_recovery_offers_no_delete
BEFORE DELETE ON vacancy_recovery_offers
FOR EACH ROW EXECUTE FUNCTION guard_vacancy_recovery_offer_mutation();

CREATE FUNCTION guard_vacancy_recovery_chain_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'vacancy recovery chains cannot be deleted';
    END IF;
    IF OLD.status <> 'active'
       OR NEW.id <> OLD.id
       OR NEW.source_appointment_id <> OLD.source_appointment_id
       OR NEW.started_by <> OLD.started_by
       OR NEW.started_at <> OLD.started_at
       OR NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'vacancy recovery chain history is immutable';
    END IF;
    IF NEW.status = 'active' THEN
        IF NEW.step_count <> OLD.step_count + 1
           OR NEW.ended_by IS NOT NULL OR NEW.ended_at IS NOT NULL
           OR NEW.stop_reason IS NOT NULL
           OR NOT EXISTS (
               SELECT 1 FROM vacancy_recovery_steps s
                WHERE s.chain_id = NEW.id AND s.sequence = NEW.step_count
                  AND s.released_doctor_id = NEW.current_doctor_id
                  AND s.released_room_id IS NOT DISTINCT FROM NEW.current_room_id
                  AND s.released_starts_at = NEW.current_starts_at
                  AND s.released_ends_at = NEW.current_ends_at
           ) THEN
            RAISE EXCEPTION 'active vacancy recovery chain must advance by its next recorded step';
        END IF;
    ELSIF NEW.status = 'stopped' THEN
        IF NEW.step_count <> OLD.step_count
           OR NEW.current_doctor_id <> OLD.current_doctor_id
           OR NEW.current_room_id IS DISTINCT FROM OLD.current_room_id
           OR NEW.current_starts_at <> OLD.current_starts_at
           OR NEW.current_ends_at <> OLD.current_ends_at THEN
            RAISE EXCEPTION 'stopping vacancy recovery cannot change its vacancy';
        END IF;
    ELSE
        RAISE EXCEPTION 'vacancy recovery chain may only remain active or stop';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER vacancy_recovery_chains_update_guard
BEFORE UPDATE ON vacancy_recovery_chains
FOR EACH ROW EXECUTE FUNCTION guard_vacancy_recovery_chain_mutation();

CREATE TRIGGER vacancy_recovery_chains_no_delete
BEFORE DELETE ON vacancy_recovery_chains
FOR EACH ROW EXECUTE FUNCTION guard_vacancy_recovery_chain_mutation();

COMMIT;
