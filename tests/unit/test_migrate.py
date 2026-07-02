from db.migrate import statements


def test_splits_on_terminating_semicolons():
    sql = """
-- a comment
CREATE TABLE a (
    x INT8,
    y STRING
);

CREATE INDEX a_x ON a (x);
"""
    got = statements(sql)
    assert len(got) == 2
    assert got[0].startswith("CREATE TABLE a")
    assert got[1] == "CREATE INDEX a_x ON a (x)"


def test_ignores_blank_and_comment_only_input():
    assert statements("-- nothing here\n\n") == []


def test_keeps_trailing_statement_without_semicolon():
    assert statements("SELECT 1") == ["SELECT 1"]
