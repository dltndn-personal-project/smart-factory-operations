"""db/schema.sql을 실제 이미지의 initdb로 적용한 결과 (docs/spec/08-verification.md 3.6절, C-03, A-08)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from .conftest import DbContainer

SCHEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"

pytestmark = pytest.mark.docker

EXPECTED_TABLES = {
    "schema_info",
    "sensor_chunk",
    "line_status_change",
    "product",
    "inspection",
    "equipment_state",
    "alarm",
    "control",
}


def _objects(db: DbContainer) -> dict:
    with db.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        }
        views = {r[0] for r in conn.execute("SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")}
        hypertables = {
            r[0]
            for r in conn.execute(
                "SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema = 'public'"
            )
        }
        schema_rows = conn.execute("SELECT component, version FROM schema_info").fetchall()
    return {"tables": tables, "views": views, "hypertables": hypertables, "schema_rows": schema_rows}


def _assert_schema(db: DbContainer) -> None:
    got = _objects(db)
    assert got["tables"] == EXPECTED_TABLES
    assert got["views"] == {"defect_result"}
    assert got["hypertables"] == {"sensor_chunk"}
    assert got["schema_rows"] == [("factory-operations", 1)]


def test_schema_objects(timescale_db: DbContainer) -> None:
    _assert_schema(timescale_db)


def test_schema_reapply(timescale_db: DbContainer) -> None:
    res = timescale_db.psql(SCHEMA_SQL)
    assert res.returncode == 0, res.stderr.decode(errors="replace")
    _assert_schema(timescale_db)
