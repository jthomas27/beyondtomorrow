"""Offline checks for explicit, checksum-protected schema application."""
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.storage.migrate import apply_migrations


def connection(previous=None):
    conn = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=previous)
    return conn


async def test_apply_records_checksum_and_skips_applied_sql(tmp_path):
    sql = "CREATE TABLE example(id INTEGER);"
    (tmp_path / "0001.sql").write_text(sql)
    conn = connection()
    assert await apply_migrations(conn, tmp_path) == ["0001.sql"]
    conn.execute.assert_any_await(sql)
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    conn.execute.assert_any_await(
        "INSERT INTO pipeline_schema_migrations(version, checksum) VALUES ($1, $2)",
        "0001.sql", checksum,
    )
    existing = connection(checksum)
    assert await apply_migrations(existing, tmp_path) == []
    assert not any(call.args[0] == sql for call in existing.execute.await_args_list)


async def test_changed_applied_migration_aborts_transaction(tmp_path):
    (tmp_path / "0001.sql").write_text("SELECT 1;")
    conn = connection("different-checksum")
    with pytest.raises(RuntimeError, match="modified"):
        await apply_migrations(conn, tmp_path)
    assert conn.transaction.return_value.__aexit__.await_args.args[0] is RuntimeError
    assert not any(call.args[0] == "SELECT 1;" for call in conn.execute.await_args_list)
