"""Tests for the SQLAlchemy schema.

Creates the schema in an in-memory SQLite, then introspects via
``sqlite_master`` to confirm tables, primary keys, indexes, and
constraints match DESIGN section 8.1 / 8.3.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session

from enar_montecarlo.persistence.schema import (
    ActorFile,
    Base,
    Effect,
    Resolution,
    Run,
    Value,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:")
    # Enable FK enforcement on SQLite (off by default).
    with eng.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


# --- table presence ----------------------------------------------------------


def test_all_tables_created(engine: Engine) -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert tables == {"actor_files", "runs", "values", "resolutions", "effects"}


# --- primary keys ------------------------------------------------------------


def test_actor_files_pk_is_sha256(engine: Engine) -> None:
    insp = inspect(engine)
    pk = insp.get_pk_constraint("actor_files")
    assert pk["constrained_columns"] == ["sha256"]


def test_runs_pk_is_run_id(engine: Engine) -> None:
    insp = inspect(engine)
    pk = insp.get_pk_constraint("runs")
    assert pk["constrained_columns"] == ["run_id"]


def test_values_pk_is_id(engine: Engine) -> None:
    insp = inspect(engine)
    pk = insp.get_pk_constraint("values")
    assert pk["constrained_columns"] == ["id"]


def test_resolutions_pk_is_composite(engine: Engine) -> None:
    insp = inspect(engine)
    pk = insp.get_pk_constraint("resolutions")
    assert pk["constrained_columns"] == ["run_id", "iteration_num", "event_seq"]


def test_effects_pk_is_composite(engine: Engine) -> None:
    insp = inspect(engine)
    pk = insp.get_pk_constraint("effects")
    assert pk["constrained_columns"] == ["run_id", "iteration_num", "event_seq"]


# --- foreign keys ------------------------------------------------------------


def test_runs_actor_files_foreign_keys(engine: Engine) -> None:
    insp = inspect(engine)
    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in insp.get_foreign_keys("runs")
    }
    assert fks["attacker_file_id"] == "actor_files"
    assert fks["defender_file_id"] == "actor_files"


def test_resolutions_foreign_keys(engine: Engine) -> None:
    insp = inspect(engine)
    fks = {
        (fk["constrained_columns"][0], fk["referred_table"])
        for fk in insp.get_foreign_keys("resolutions")
    }
    assert ("run_id", "runs") in fks
    assert ("actor_file_id", "actor_files") in fks
    assert ("target_file_id", "actor_files") in fks
    assert ("outcome_id", "values") in fks


def test_effects_foreign_keys(engine: Engine) -> None:
    insp = inspect(engine)
    fks = {
        (fk["constrained_columns"][0], fk["referred_table"])
        for fk in insp.get_foreign_keys("effects")
    }
    assert ("run_id", "runs") in fks
    assert ("actor_file_id", "actor_files") in fks
    assert ("effect_type_id", "values") in fks
    assert ("damage_type_id", "values") in fks
    assert ("source_branch_id", "values") in fks


# --- unique constraints ------------------------------------------------------


def test_values_has_unique_category_value(engine: Engine) -> None:
    insp = inspect(engine)
    uniques = insp.get_unique_constraints("values")
    cols = {tuple(u["column_names"]) for u in uniques}
    assert ("category", "value") in cols


# --- indexes -----------------------------------------------------------------


def test_resolutions_has_recommended_indexes(engine: Engine) -> None:
    insp = inspect(engine)
    idx_cols = {tuple(i["column_names"]) for i in insp.get_indexes("resolutions")}
    assert ("run_id", "iteration_num") in idx_cols
    assert ("outcome_id",) in idx_cols


def test_effects_has_recommended_indexes(engine: Engine) -> None:
    insp = inspect(engine)
    idx_cols = {tuple(i["column_names"]) for i in insp.get_indexes("effects")}
    assert ("run_id", "iteration_num") in idx_cols
    assert ("effect_type_id",) in idx_cols
    assert ("damage_type_id",) in idx_cols


# --- runtime sanity: round-trip a row ---------------------------------------


def test_can_insert_and_query_values(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(Value(category="outcome", value="hit"))
        session.commit()
        row = session.query(Value).filter_by(category="outcome", value="hit").one()
        assert row.id is not None


def test_unique_constraint_enforced(engine: Engine) -> None:
    from sqlalchemy.exc import IntegrityError

    with Session(engine) as session:
        session.add(Value(category="outcome", value="hit"))
        session.commit()
        session.add(Value(category="outcome", value="hit"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_models_importable() -> None:
    # Smoke check that the public surface is what other modules will use.
    assert Run.__tablename__ == "runs"
    assert ActorFile.__tablename__ == "actor_files"
    assert Value.__tablename__ == "values"
    assert Resolution.__tablename__ == "resolutions"
    assert Effect.__tablename__ == "effects"
