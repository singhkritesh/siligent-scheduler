from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=settings.database_host,
        port=settings.database_port,
        dbname=settings.database_name,
        user=settings.database_user,
        password=settings.database_password,
        row_factory=dict_row,
    )


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    with connect() as connection:
        with connection.transaction():
            yield connection


def run_migrations() -> None:
    migration_dir = Path(settings.migration_dir)
    migrations = sorted(migration_dir.glob("*.sql"))
    if not migrations:
        raise RuntimeError(f"no database migrations found in {migration_dir}")

    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename text PRIMARY KEY,
                checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT transaction_timestamp()
            )
            """
        )
        for path in migrations:
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            existing = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE filename = %s",
                (path.name,),
            ).fetchone()
            if existing:
                if existing["checksum"] != checksum:
                    raise RuntimeError(f"applied migration changed: {path.name}")
                continue
            migration_body = re.sub(r"^\s*BEGIN;", "", sql, count=1, flags=re.IGNORECASE)
            migration_body = re.sub(
                r"COMMIT;\s*$", "", migration_body, count=1, flags=re.IGNORECASE
            )
            with connection.transaction():
                connection.execute(migration_body)
                connection.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )


def append_audit(
    connection: psycopg.Connection,
    *,
    actor_id: str | None,
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    correlation_id: str,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> None:
    safe_details = details or {}
    connection.execute("SELECT pg_advisory_xact_lock(731947)")
    previous = connection.execute(
        "SELECT event_hash FROM audit_events ORDER BY occurred_at DESC, id DESC LIMIT 1"
    ).fetchone()
    previous_hash = bytes(previous["event_hash"]) if previous else b""
    canonical = json.dumps(
        {
            "actor_id": actor_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "correlation_id": correlation_id,
            "outcome": outcome,
            "details": safe_details,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    event_hash = hashlib.sha256(previous_hash + canonical).digest()
    connection.execute(
        """
        INSERT INTO audit_events (
            actor_id, event_type, entity_type, entity_id, correlation_id,
            outcome, details, previous_hash, event_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            actor_id,
            event_type,
            entity_type,
            entity_id,
            correlation_id,
            outcome,
            json.dumps(safe_details),
            previous_hash or None,
            event_hash,
        ),
    )
