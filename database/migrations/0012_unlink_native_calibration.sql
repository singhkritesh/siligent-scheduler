BEGIN;

ALTER TABLE procedure_duration_observations
    DROP CONSTRAINT procedure_duration_observation_source,
    DROP CONSTRAINT procedure_duration_observation_appointment_unique,
    DROP COLUMN appointment_id,
    ADD CONSTRAINT procedure_duration_observation_source CHECK (
        (source = 'import' AND batch_id IS NOT NULL)
        OR (source = 'native' AND batch_id IS NULL)
    );

COMMIT;
