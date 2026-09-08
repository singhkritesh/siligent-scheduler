\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    actor_id uuid;
    patient_id_value uuid;
    second_patient_id_value uuid;
    third_patient_id_value uuid;
    fourth_patient_id_value uuid;
    fifth_patient_id_value uuid;
    doctor_id_value uuid;
    provider_id_value uuid;
    procedure_id_value uuid;
    alternate_procedure_id_value uuid;
    room_id_value uuid;
    second_room_id_value uuid;
    third_room_id_value uuid;
    fourth_room_id_value uuid;
    appointment_id_value uuid;
    second_appointment_id_value uuid;
    reserved_block_id_value uuid;
    permission_id_value uuid;
    audit_id_value uuid;
    equipment_id_value uuid;
    second_equipment_id_value uuid;
    old_start timestamptz := '2027-01-12 14:00:00+00';
    old_end timestamptz := '2027-01-12 15:00:00+00';
    new_start timestamptz := '2027-01-13 14:00:00+00';
    new_end timestamptz := '2027-01-13 15:00:00+00';
    error_message text;
BEGIN
    INSERT INTO app_users (external_subject, display_name, role)
    VALUES ('test-scheduler', 'Synthetic Scheduler', 'scheduler')
    RETURNING id INTO actor_id;

    INSERT INTO patients (
        medical_record_number,
        display_name,
        created_by
    ) VALUES (
        'SYNTHETIC-0001',
        'Synthetic Patient',
        actor_id
    ) RETURNING id INTO patient_id_value;

    INSERT INTO doctors (staff_code, display_name, specialty)
    VALUES ('SYNTH-D01', 'Synthetic Doctor', 'general')
    RETURNING id INTO doctor_id_value;

    INSERT INTO providers (staff_code, display_name, role, doctor_id)
    VALUES ('SYNTH-D01', 'Synthetic Doctor', 'doctor', doctor_id_value)
    RETURNING id INTO provider_id_value;

    INSERT INTO procedures (
        code,
        name,
        duration_minutes,
        policy_version
    ) VALUES (
        'SYNTH-P01',
        'Synthetic Procedure',
        60,
        'test-v1'
    ) RETURNING id INTO procedure_id_value;

    INSERT INTO rooms (code, name)
    VALUES ('SYNTH-R01', 'Synthetic Room')
    RETURNING id INTO room_id_value;

    INSERT INTO rooms (code, name)
    VALUES ('SYNTH-R02', 'Synthetic Room Two')
    RETURNING id INTO second_room_id_value;

    INSERT INTO appointments (
        patient_id,
        procedure_id,
        doctor_id,
        room_id,
        starts_at,
        ends_at,
        practice_timezone,
        status,
        created_by
    ) VALUES (
        patient_id_value,
        procedure_id_value,
        doctor_id_value,
        room_id_value,
        old_start,
        old_end,
        'America/New_York',
        'confirmed',
        actor_id
    ) RETURNING id INTO appointment_id_value;

    BEGIN
        UPDATE appointments
           SET starts_at = new_start,
               ends_at = new_end
         WHERE id = appointment_id_value;
        RAISE EXCEPTION 'test failed: confirmed appointment moved without permission';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM NOT LIKE '%requires explicit reschedule permission%' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO reschedule_permissions (
        appointment_id,
        old_doctor_id,
        new_doctor_id,
        old_room_id,
        new_room_id,
        old_starts_at,
        old_ends_at,
        new_starts_at,
        new_ends_at,
        granted_by,
        reason,
        expires_at
    ) VALUES (
        appointment_id_value,
        doctor_id_value,
        doctor_id_value,
        room_id_value,
        room_id_value,
        old_start,
        old_end,
        new_start,
        new_end,
        actor_id,
        'Synthetic authorized reschedule test',
        transaction_timestamp() + interval '10 minutes'
    ) RETURNING id INTO permission_id_value;

    PERFORM set_config(
        'siligent.reschedule_permission_id',
        permission_id_value::text,
        true
    );

    UPDATE appointments
       SET starts_at = new_start,
           ends_at = new_end
     WHERE id = appointment_id_value;

    IF NOT EXISTS (
        SELECT 1
          FROM appointments
         WHERE id = appointment_id_value
           AND starts_at = new_start
           AND ends_at = new_end
           AND lock_version = 1
    ) THEN
        RAISE EXCEPTION 'test failed: authorized move was not applied';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM reschedule_permissions
         WHERE id = permission_id_value
           AND used_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'test failed: reschedule permission was not consumed';
    END IF;

    INSERT INTO appointment_phases (
        appointment_id, sequence, phase_code, phase_name, role,
        provider_id, starts_at, ends_at
    ) VALUES (
        appointment_id_value, 1, 'synthetic-doctor', 'Synthetic doctor phase',
        'doctor', provider_id_value, new_start, new_end
    );

    PERFORM set_config('siligent.reschedule_permission_id', '', true);
    BEGIN
        UPDATE appointment_phases
           SET starts_at = starts_at + interval '5 minutes'
         WHERE appointment_id = appointment_id_value;
        RAISE EXCEPTION 'test failed: confirmed phase changed without exact permission';
    EXCEPTION
        WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF error_message <> 'confirmed appointment phases require exact reschedule permission' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO equipment (code, name, quantity)
    VALUES ('SYNTH-E01', 'Synthetic Equipment', 1)
    RETURNING id INTO equipment_id_value;

    INSERT INTO appointment_equipment_reservations (
        appointment_id, equipment_id, unit_number, starts_at, ends_at
    ) VALUES (
        appointment_id_value, equipment_id_value, 1, new_start, new_end
    );

    BEGIN
        INSERT INTO appointment_equipment_reservations (
            appointment_id, equipment_id, unit_number, starts_at, ends_at
        ) VALUES (
            appointment_id_value, equipment_id_value, 2, new_start, new_end
        );
        RAISE EXCEPTION 'test failed: equipment reservation exceeded configured quantity';
    EXCEPTION
        WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF error_message <> 'equipment unit exceeds configured capacity' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        UPDATE appointment_equipment_reservations
           SET starts_at = starts_at + interval '5 minutes'
         WHERE appointment_id = appointment_id_value;
        RAISE EXCEPTION 'test failed: confirmed equipment changed without exact permission';
    EXCEPTION
        WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF error_message <> 'confirmed equipment reservations require exact reschedule permission' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO equipment (code, name, quantity)
    VALUES ('SYNTH-E02', 'Synthetic Equipment Two', 2)
    RETURNING id INTO second_equipment_id_value;
    INSERT INTO appointment_equipment_reservations (
        appointment_id, equipment_id, unit_number, starts_at, ends_at
    ) VALUES (
        appointment_id_value, second_equipment_id_value, 2, new_start, new_end
    );
    BEGIN
        UPDATE equipment SET quantity = 1 WHERE id = second_equipment_id_value;
        RAISE EXCEPTION 'test failed: equipment quantity dropped below active unit';
    EXCEPTION
        WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF error_message <> 'equipment quantity is below an active reserved unit' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO patients (medical_record_number, display_name, created_by)
    VALUES ('SYNTHETIC-0002', 'Synthetic Patient Two', actor_id)
    RETURNING id INTO second_patient_id_value;

    INSERT INTO appointments (
        patient_id, procedure_id, doctor_id, room_id, starts_at, ends_at,
        practice_timezone, status, created_by
    ) VALUES (
        second_patient_id_value, procedure_id_value, doctor_id_value,
        second_room_id_value, new_start + interval '30 minutes',
        new_end + interval '30 minutes', 'America/New_York', 'confirmed', actor_id
    ) RETURNING id INTO second_appointment_id_value;

    BEGIN
        INSERT INTO appointment_phases (
            appointment_id, sequence, phase_code, phase_name, role,
            provider_id, starts_at, ends_at
        ) VALUES (
            second_appointment_id_value, 1, 'synthetic-doctor', 'Overlapping doctor phase',
            'doctor', provider_id_value, new_start + interval '30 minutes',
            new_end + interval '30 minutes'
        );
        RAISE EXCEPTION 'test failed: overlapping provider phase was accepted';
    EXCEPTION
        WHEN exclusion_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO appointments (
            patient_id,
            procedure_id,
            doctor_id,
            room_id,
            starts_at,
            ends_at,
            practice_timezone,
            status,
            created_by
        ) VALUES (
            patient_id_value,
            procedure_id_value,
            doctor_id_value,
            room_id_value,
            new_start + interval '30 minutes',
            new_end + interval '30 minutes',
            'America/New_York',
            'confirmed',
            actor_id
        );
        RAISE EXCEPTION 'test failed: overlapping appointment was accepted';
    EXCEPTION
        WHEN exclusion_violation THEN
            NULL;
    END;

    INSERT INTO patients (medical_record_number, display_name, created_by)
    VALUES ('SYNTHETIC-0003', 'Synthetic Patient Three', actor_id)
    RETURNING id INTO third_patient_id_value;
    INSERT INTO patients (medical_record_number, display_name, created_by)
    VALUES ('SYNTHETIC-0004', 'Synthetic Patient Four', actor_id)
    RETURNING id INTO fourth_patient_id_value;
    INSERT INTO rooms (code, name) VALUES ('SYNTH-R03', 'Synthetic Room Three')
    RETURNING id INTO third_room_id_value;
    INSERT INTO rooms (code, name) VALUES ('SYNTH-R04', 'Synthetic Room Four')
    RETURNING id INTO fourth_room_id_value;

    INSERT INTO appointments (
        patient_id, procedure_id, doctor_id, room_id, starts_at, ends_at,
        practice_timezone, status, created_by
    ) VALUES (
        third_patient_id_value, procedure_id_value, doctor_id_value,
        third_room_id_value, new_start + interval '30 minutes',
        new_end + interval '30 minutes', 'America/New_York', 'confirmed', actor_id
    );

    BEGIN
        UPDATE doctors SET max_active_rooms = 2 WHERE id = doctor_id_value;
        RAISE EXCEPTION 'test failed: dentist capacity dropped below active concurrency';
    EXCEPTION
        WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF error_message <> 'dentist capacity is below current concurrent visits' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO appointments (
            patient_id, procedure_id, doctor_id, room_id, starts_at, ends_at,
            practice_timezone, status, created_by
        ) VALUES (
            fourth_patient_id_value, procedure_id_value, doctor_id_value,
            fourth_room_id_value, new_start + interval '30 minutes',
            new_end + interval '30 minutes', 'America/New_York', 'confirmed', actor_id
        );
        RAISE EXCEPTION 'test failed: dentist supervision limit was exceeded';
    EXCEPTION
        WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            IF error_message <> 'dentist active-room supervision limit exceeded' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO patients (medical_record_number, display_name, created_by)
    VALUES ('SYNTHETIC-0005', 'Synthetic Patient Five', actor_id)
    RETURNING id INTO fifth_patient_id_value;

    INSERT INTO procedures (code, name, duration_minutes, policy_version)
    VALUES ('SYNTH-P02', 'Synthetic Alternate Procedure', 60, 'test-v1')
    RETURNING id INTO alternate_procedure_id_value;

    INSERT INTO reserved_procedure_blocks (
        doctor_id, procedure_id, room_id, reserved_during, reason, created_by
    ) VALUES (
        doctor_id_value, procedure_id_value, room_id_value,
        tstzrange('2030-01-15 14:00:00+00', '2030-01-15 15:00:00+00', '[)'),
        'Synthetic protected procedure capacity', actor_id
    ) RETURNING id INTO reserved_block_id_value;

    BEGIN
        UPDATE reserved_procedure_blocks
           SET release_reason = 'Forged history'
         WHERE id = reserved_block_id_value;
        RAISE EXCEPTION 'test failed: reserved-block history changed without authorization';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'reserved procedure block status change requires exact authorization' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        INSERT INTO appointments (
            patient_id, procedure_id, doctor_id, room_id, starts_at, ends_at,
            practice_timezone, status, created_by
        ) VALUES (
            fifth_patient_id_value, alternate_procedure_id_value,
            doctor_id_value, room_id_value,
            '2030-01-15 14:00:00+00', '2030-01-15 15:00:00+00',
            'America/New_York', 'confirmed', actor_id
        );
        RAISE EXCEPTION 'test failed: nonmatching appointment used reserved capacity';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'appointment conflicts with a reserved procedure block' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO appointments (
        patient_id, procedure_id, doctor_id, room_id, starts_at, ends_at,
        practice_timezone, status, created_by
    ) VALUES (
        fifth_patient_id_value, procedure_id_value, doctor_id_value, room_id_value,
        '2030-01-15 14:00:00+00', '2030-01-15 15:00:00+00',
        'America/New_York', 'confirmed', actor_id
    );

    PERFORM set_config(
        'siligent.reserved_block_change_id', reserved_block_id_value::text, true
    );
    UPDATE reserved_procedure_blocks
       SET status = 'released', released_by = actor_id,
           released_at = transaction_timestamp(),
           release_reason = 'Synthetic authorized release'
     WHERE id = reserved_block_id_value;

    BEGIN
        DELETE FROM reserved_procedure_blocks WHERE id = reserved_block_id_value;
        RAISE EXCEPTION 'test failed: reserved procedure block deletion was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'reserved procedure blocks cannot be deleted' THEN
                RAISE;
            END IF;
    END;

    INSERT INTO audit_events (
        actor_id,
        event_type,
        entity_type,
        entity_id,
        correlation_id,
        outcome,
        details,
        event_hash
    ) VALUES (
        actor_id,
        'appointment.rescheduled',
        'appointment',
        appointment_id_value,
        gen_random_uuid(),
        'success',
        jsonb_build_object('permission_id', permission_id_value),
        digest('synthetic audit event', 'sha256')
    ) RETURNING id INTO audit_id_value;

    BEGIN
        UPDATE audit_events
           SET outcome = 'failure'
         WHERE id = audit_id_value;
        RAISE EXCEPTION 'test failed: audit event update was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'audit events are append-only' THEN
                RAISE;
            END IF;
    END;

    BEGIN
        DELETE FROM audit_events WHERE id = audit_id_value;
        RAISE EXCEPTION 'test failed: audit event deletion was accepted';
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'audit events are append-only' THEN
                RAISE;
            END IF;
    END;

    RAISE NOTICE 'database invariant tests passed';
END;
$$;

ROLLBACK;
