BEGIN;

ALTER TABLE appointments DROP CONSTRAINT appointment_flow_order;
ALTER TABLE appointments
    ADD CONSTRAINT appointment_flow_order CHECK (
        (seated_at IS NULL OR checked_in_at IS NOT NULL)
        AND (seated_at IS NULL OR seated_at >= checked_in_at)
        AND (
            completed_at IS NULL
            OR (seated_at IS NULL AND checked_in_at IS NULL)
            OR completed_at >= COALESCE(seated_at, checked_in_at)
        )
    );

COMMIT;
