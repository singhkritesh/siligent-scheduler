BEGIN;

CREATE TABLE local_credentials (
    user_id uuid PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    username text NOT NULL,
    password_salt bytea NOT NULL,
    password_hash bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    password_changed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until timestamptz
);

CREATE UNIQUE INDEX local_credentials_username_lower_idx
    ON local_credentials (lower(username));

CREATE TABLE user_sessions (
    token_hash bytea PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);

CREATE INDEX user_sessions_active_user_idx
    ON user_sessions (user_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE room_working_hours (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id uuid NOT NULL REFERENCES rooms(id),
    weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    local_start time NOT NULL,
    local_end time NOT NULL,
    effective_from date NOT NULL,
    effective_through date,
    CHECK (local_end > local_start),
    CHECK (effective_through IS NULL OR effective_through >= effective_from)
);

CREATE TABLE procedure_room_eligibility (
    procedure_id uuid NOT NULL REFERENCES procedures(id),
    room_id uuid NOT NULL REFERENCES rooms(id),
    PRIMARY KEY (procedure_id, room_id)
);

CREATE TABLE recommendation_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduling_request_id uuid NOT NULL REFERENCES scheduling_requests(id),
    reschedules_appointment_id uuid REFERENCES appointments(id),
    doctor_id uuid NOT NULL REFERENCES doctors(id),
    room_id uuid NOT NULL REFERENCES rooms(id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    score integer NOT NULL,
    explanation jsonb NOT NULL,
    created_by uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    CHECK (ends_at > starts_at),
    CHECK (expires_at > created_at)
);

CREATE INDEX recommendation_snapshots_request_idx
    ON recommendation_snapshots (scheduling_request_id, created_at);

COMMIT;

