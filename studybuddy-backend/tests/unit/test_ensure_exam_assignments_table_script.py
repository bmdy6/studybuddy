from scripts.ensure_exam_assignments_table import ensure_exam_assignments_table


class _FakeResult:
    def __init__(self, exists: bool):
        self._exists = exists

    def first(self):
        return ("exam_assignments",) if self._exists else None


class _FakeSession:
    def __init__(self, exists: bool):
        self.exists = exists
        self.statements: list[str] = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "SHOW TABLES LIKE 'exam_assignments'" in sql:
            return _FakeResult(self.exists)
        return _FakeResult(True)

    def commit(self):
        self.committed = True


def test_ensure_exam_assignments_table_creates_missing_table():
    session = _FakeSession(exists=False)

    created = ensure_exam_assignments_table(lambda: session)

    assert created is True
    assert session.committed is True
    assert any("CREATE TABLE IF NOT EXISTS exam_assignments" in sql for sql in session.statements)


def test_ensure_exam_assignments_table_is_idempotent_when_table_exists():
    session = _FakeSession(exists=True)

    created = ensure_exam_assignments_table(lambda: session)

    assert created is False
    assert session.committed is True
    assert any("CREATE TABLE IF NOT EXISTS exam_assignments" in sql for sql in session.statements)
