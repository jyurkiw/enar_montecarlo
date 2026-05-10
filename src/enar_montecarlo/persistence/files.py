"""SHA-256-keyed actor file storage with content-addressed dedup."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from enar_montecarlo.persistence.schema import ActorFile
from enar_montecarlo.persistence.sessions import PersistenceContext


def canonical_sha256(content: dict[str, Any]) -> str:
    """SHA-256 of canonical-JSON-serialized content (sorted keys, tight separators).

    Public so sims can derive the same ``actor_file_id`` value the
    framework will assign during ``store_file``, allowing sim hooks to
    emit events with FK-valid ``actor_file_id`` references without the
    framework having to thread the SHAs through hook signatures.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_utc_naive() -> datetime:
    """Naive UTC datetime for the schema's tz-less DateTime column."""
    return datetime.now(UTC).replace(tzinfo=None)


def _upsert_stmt(
    session: Session,
    sha: str,
    filename: str,
    content: dict[str, Any],
) -> Any:
    dialect = session.get_bind().dialect.name
    payload: dict[str, Any] = {
        "sha256": sha,
        "original_filename": filename,
        "content_json": content,
        "first_seen_at": _now_utc_naive(),
    }
    stmt: Any
    if dialect == "postgresql":
        stmt = pg_insert(ActorFile).values(**payload)
    else:
        stmt = sqlite_insert(ActorFile).values(**payload)
    return stmt.on_conflict_do_nothing(index_elements=["sha256"])


def store_file(
    ctx: PersistenceContext,
    content: dict[str, Any],
    original_filename: str,
) -> str:
    """Insert ``content`` (or skip if its SHA-256 is already present) and
    return the SHA-256.

    The first filename ingested for a given content wins; subsequent
    re-ingestions under different filenames are no-ops at the DB layer.
    """
    sha = canonical_sha256(content)
    if ctx.postgres is not None:
        ctx.postgres.execute(_upsert_stmt(ctx.postgres, sha, original_filename, content))
        ctx.postgres.commit()
    ctx.sqlite.execute(_upsert_stmt(ctx.sqlite, sha, original_filename, content))
    ctx.sqlite.commit()
    return sha
