BEGIN;

-- The exact override permission records the new appointment id. Enforce after
-- row insertion/update so that foreign-key attribution can occur in the same
-- transaction; any raised exception still rolls the appointment statement back.
DROP TRIGGER appointments_reserved_block_guard ON appointments;
CREATE TRIGGER appointments_reserved_block_guard
AFTER INSERT OR UPDATE OF doctor_id, procedure_id, room_id, starts_at, ends_at, status
ON appointments
FOR EACH ROW EXECUTE FUNCTION enforce_reserved_blocks_on_appointment();

COMMIT;
