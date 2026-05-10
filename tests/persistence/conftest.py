"""Shared fixtures for the persistence test suite.

The ``postgres_url`` fixture wraps the ``POSTGRES_TEST_URL`` env var
with database lifecycle management: if the named database does not
exist on the target server, it is created; after the test, the
database is dropped (with all client connections terminated first).

CREATE / DROP DATABASE require connecting to a different database
on the same server -- we use ``postgres`` (the conventional
maintenance DB) and AUTOCOMMIT isolation since neither statement
runs inside a transaction.

Tests that just want a usable URL declare ``postgres_url`` as a
parameter; pytest skips them automatically when ``POSTGRES_TEST_URL``
is unset.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url


@pytest.fixture
def postgres_url() -> Iterator[str]:
    raw = os.environ.get("POSTGRES_TEST_URL")
    if not raw:
        pytest.skip("POSTGRES_TEST_URL not set")

    url = make_url(raw)
    db_name = url.database
    if not db_name:
        pytest.fail("POSTGRES_TEST_URL must include a database name")

    maintenance_url = url.set(database="postgres")
    admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    # Create if missing. ``CREATE DATABASE`` has no IF NOT EXISTS
    # variant in Postgres; check pg_database first.
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": db_name},
            ).scalar()
            if not exists:
                # Identifier interpolation: db_name comes from the
                # operator's own POSTGRES_TEST_URL, so quoting is
                # purely for safety against unusual identifiers.
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin.dispose()

    try:
        yield raw
    finally:
        # Tear down: terminate any lingering client connections so
        # the DROP can succeed, then drop the database.
        admin = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :n AND pid <> pg_backend_pid()"
                    ),
                    {"n": db_name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        finally:
            admin.dispose()
