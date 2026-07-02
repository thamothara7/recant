"""Apply db/migrations/*.sql in filename order, tracked in schema_migrations.

Statements are split on semicolons at end of line: one statement per terminating
semicolon, no procedural ($$) bodies allowed in migration files.
"""

import os
import pathlib
import sys

import psycopg

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def statements(sql_text: str) -> list[str]:
    stmts: list[str] = []
    buf: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                stmts.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        stmts.append(tail)
    return stmts


def main() -> None:
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name STRING PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            print(f"applying {path.name}", file=sys.stderr)
            for stmt in statements(path.read_text()):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,)
            )


if __name__ == "__main__":
    main()
