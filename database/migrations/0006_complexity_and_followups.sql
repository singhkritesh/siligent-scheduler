BEGIN;

ALTER TABLE procedure_phase_templates
    ADD COLUMN complex_duration_minutes integer CHECK (complex_duration_minutes > 0);

UPDATE procedure_phase_templates
   SET complex_duration_minutes = CEIL(duration_minutes * 1.25 / 5.0)::integer * 5
 WHERE complex_duration_minutes IS NULL;

ALTER TABLE waitlist_entries
    ADD COLUMN predecessor_appointment_id uuid REFERENCES appointments(id) ON DELETE RESTRICT,
    ADD COLUMN relationship text
        CHECK (relationship IN ('followup', 'lab_return', 'treatment_plan')),
    ADD CONSTRAINT waitlist_link_pair CHECK (
        (predecessor_appointment_id IS NULL) = (relationship IS NULL)
    );

CREATE UNIQUE INDEX waitlist_one_linked_followup
    ON waitlist_entries (predecessor_appointment_id, procedure_id)
    WHERE predecessor_appointment_id IS NOT NULL
      AND status IN ('active', 'offered', 'scheduled');

COMMIT;
