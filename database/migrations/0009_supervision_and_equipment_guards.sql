BEGIN;

CREATE FUNCTION enforce_doctor_active_visit_capacity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    configured_limit integer;
    overlapping_visits integer;
BEGIN
    IF NEW.status NOT IN ('held', 'confirmed') THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.doctor_id::text, 0));
    SELECT max_active_rooms INTO configured_limit FROM doctors WHERE id = NEW.doctor_id;
    SELECT count(*) INTO overlapping_visits
      FROM appointments a
     WHERE a.doctor_id = NEW.doctor_id
       AND a.status IN ('held', 'confirmed')
       AND a.id <> NEW.id
       AND tstzrange(a.starts_at, a.ends_at, '[)')
           && tstzrange(NEW.starts_at, NEW.ends_at, '[)');
    IF overlapping_visits >= configured_limit THEN
        RAISE EXCEPTION 'dentist active-room supervision limit exceeded';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER appointments_doctor_active_visit_capacity
BEFORE INSERT OR UPDATE OF doctor_id, starts_at, ends_at, status ON appointments
FOR EACH ROW EXECUTE FUNCTION enforce_doctor_active_visit_capacity();

CREATE FUNCTION validate_equipment_unit_number()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    configured_quantity integer;
BEGIN
    SELECT quantity INTO configured_quantity FROM equipment
     WHERE id = NEW.equipment_id AND active;
    IF configured_quantity IS NULL OR NEW.unit_number > configured_quantity THEN
        RAISE EXCEPTION 'equipment unit exceeds configured capacity';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER appointment_equipment_unit_capacity
BEFORE INSERT OR UPDATE OF equipment_id, unit_number
ON appointment_equipment_reservations
FOR EACH ROW EXECUTE FUNCTION validate_equipment_unit_number();

COMMIT;
