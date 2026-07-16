"""The read-only SQL surface is the agent's safety boundary, so pin it hard:
only single read statements pass validation, the executor issues SET TRANSACTION
READ ONLY, and wide/opaque columns are truncated. No database: a fake connection."""

import pytest

from agent.readonly_sql import ReadOnlySQL, UnsafeQuery, validate


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM beliefs",
        "select content from beliefs limit 5",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW TABLES",
        "EXPLAIN SELECT * FROM beliefs",
        "  SELECT 1 ;  ",  # trailing semicolon is stripped
    ],
)
def test_validate_allows_reads(sql):
    assert validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO beliefs VALUES (1)",
        "UPDATE beliefs SET status = 'active'",
        "DELETE FROM beliefs",
        "DROP TABLE beliefs",
        "ALTER TABLE beliefs ADD COLUMN x INT",
        "TRUNCATE beliefs",
        "GRANT ALL ON beliefs TO x",
        "SELECT 1; DROP TABLE beliefs",  # stacked statement
        "",
        "   ",
    ],
)
def test_validate_rejects_writes_and_stacked(sql):
    with pytest.raises(UnsafeQuery):
        validate(sql)


class _FakeCursor:
    def __init__(self, cols, rows):
        self.description = [type("D", (), {"name": c}) for c in cols] if cols else None
        self._rows = rows

    def fetchmany(self, n):
        return self._rows[:n]


class _FakeConn:
    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.executed: list[str] = []

    def transaction(self):
        outer = self

        class _T:
            def __enter__(self):
                return None

            def __exit__(self, *a):
                return False

        return _T()

    def execute(self, sql, *a):
        self.executed.append(sql)
        if sql.strip().upper().startswith("SET TRANSACTION"):
            return _FakeCursor([], [])
        return _FakeCursor(self.cols, self.rows)


def test_execute_sets_read_only_and_shapes_rows():
    fake = _FakeConn(
        ["belief_id", "content", "embedding"],
        [(b"\xab\xcd", "hello", [0.1] * 1024), ("id2", "x" * 500, None)],
    )
    tool = ReadOnlySQL(conn_factory=lambda: fake, max_rows=10)
    out = tool.run("SELECT belief_id, content, embedding FROM beliefs")

    # DB-enforced read-only was issued before the query.
    assert fake.executed[0].strip() == "SET TRANSACTION READ ONLY"
    assert out["columns"] == ["belief_id", "content", "embedding"]
    # bytes -> hex, embedding omitted, long string truncated.
    assert out["rows"][0]["belief_id"] == "abcd"
    assert out["rows"][0]["embedding"] == "<vector omitted>"
    assert out["rows"][1]["content"].endswith("...")
    assert out["truncated"] is False


def test_execute_flags_truncation_at_row_cap():
    fake = _FakeConn(["n"], [(i,) for i in range(50)])
    tool = ReadOnlySQL(conn_factory=lambda: fake, max_rows=5)
    out = tool.run("SELECT n FROM generate_series(1,50) n")
    assert len(out["rows"]) == 5
    assert out["truncated"] is True


def test_run_rejects_write_before_touching_db():
    fake = _FakeConn(["n"], [])
    tool = ReadOnlySQL(conn_factory=lambda: fake)
    with pytest.raises(UnsafeQuery):
        tool.run("DELETE FROM beliefs")
    assert fake.executed == []  # never reached the connection
