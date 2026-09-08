BEGIN;

CREATE FUNCTION validate_equipment_quantity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    highest_reserved_unit integer;
BEGIN
    SELECT COALESCE(max(unit_number), 0) INTO highest_reserved_unit
      FROM appointment_equipment_reservations
     WHERE equipment_id = NEW.id AND active;
    IF NEW.quantity < highest_reserved_unit THEN
        RAISE EXCEPTION 'equipment quantity is below an active reserved unit';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER equipment_quantity_change_guard
BEFORE UPDATE OF quantity ON equipment
FOR EACH ROW EXECUTE FUNCTION validate_equipment_quantity_change();

CREATE FUNCTION validate_doctor_capacity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    highest_concurrency integer;
BEGIN
    IF NEW.max_active_rooms >= OLD.max_active_rooms THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id::text, 0));
    SELECT COALESCE(max((
        SELECT count(*) FROM appointments concurrent
         WHERE concurrent.doctor_id = NEW.id
           AND concurrent.status IN ('held', 'confirmed')
           AND concurrent.starts_at <= anchor.starts_at
           AND concurrent.ends_at > anchor.starts_at
    )), 0)
      INTO highest_concurrency
      FROM appointments anchor
     WHERE anchor.doctor_id = NEW.id
       AND anchor.status IN ('held', 'confirmed');
    IF NEW.max_active_rooms < highest_concurrency THEN
        RAISE EXCEPTION 'dentist capacity is below current concurrent visits';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER doctor_capacity_change_guard
BEFORE UPDATE OF max_active_rooms ON doctors
FOR EACH ROW EXECUTE FUNCTION validate_doctor_capacity_change();

COMMIT;
