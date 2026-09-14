BEGIN;

-- A practice user may be explicitly linked to one dentist provider.  The link
-- is optional for non-dentist clinical users and preserves all historical rows.
ALTER TABLE app_users
    ADD COLUMN provider_id uuid UNIQUE REFERENCES providers(id) ON DELETE RESTRICT;

CREATE FUNCTION enforce_dentist_user_link()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    provider_role_value provider_role;
BEGIN
    IF NEW.provider_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.role <> 'clinician' THEN
        RAISE EXCEPTION 'a linked dentist account must use the clinician role';
    END IF;
    SELECT role INTO provider_role_value FROM providers WHERE id = NEW.provider_id;
    IF provider_role_value IS DISTINCT FROM 'doctor'::provider_role THEN
        RAISE EXCEPTION 'a linked account must reference a dentist provider';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER app_users_dentist_link_guard
BEFORE INSERT OR UPDATE OF provider_id, role ON app_users
FOR EACH ROW EXECUTE FUNCTION enforce_dentist_user_link();

CREATE INDEX app_users_provider_idx ON app_users (provider_id)
    WHERE provider_id IS NOT NULL;

COMMIT;
