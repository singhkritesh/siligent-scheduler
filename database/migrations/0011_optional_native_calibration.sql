BEGIN;

ALTER TABLE procedure_duration_observations
    ALTER COLUMN batch_id DROP NOT NULL,
    ADD COLUMN appointment_id uuid REFERENCES appointments(id) ON DELETE RESTRICT,
    ADD COLUMN source text NOT NULL DEFAULT 'import'
        CHECK (source IN ('import', 'native')),
    ADD CONSTRAINT procedure_duration_observation_source CHECK (
        (source = 'import' AND batch_id IS NOT NULL AND appointment_id IS NULL)
        OR (source = 'native' AND batch_id IS NULL AND appointment_id IS NOT NULL)
    ),
    ADD CONSTRAINT procedure_duration_observation_appointment_unique UNIQUE (appointment_id);

ALTER TABLE calibration_recommendations
    ALTER COLUMN source_batch_id DROP NOT NULL;

CREATE INDEX duration_observation_source_idx
    ON procedure_duration_observations (source, procedure_id, service_date);

COMMIT;
