"""路由必须走统一的「可访问学生」校验，不接受前端直接传入的 student_id。

不需要数据库：验证的是依赖注入装配（旧实现直接信任 student_id，本用例会失败）。
带 DB 的端到端越权用例见 test_router_authz.py（需要本机 MySQL，与其他用例一致）。
"""

from app.features.memory import router as memory_router


def _patch(monkeypatch, sid: int = 7):
    seen: dict = {}

    def fake_resolve(db, user, student_id):
        seen["resolve_arg"] = student_id
        return sid

    monkeypatch.setattr(memory_router, "resolve_accessible_student_id", fake_resolve)
    return seen


def test_search_uses_resolved_student(monkeypatch):
    seen = _patch(monkeypatch)
    monkeypatch.setattr(memory_router, "search_workspace_memory", lambda db, student_id, q, k: seen.setdefault("used", student_id))
    memory_router.api_search(q="定语从句", student_id=123, k=5, db=object(), user=object())
    assert seen["resolve_arg"] == 123
    assert seen["used"] == 7


def test_create_relations_uses_resolved_student(monkeypatch):
    seen = _patch(monkeypatch)
    monkeypatch.setattr(memory_router, "create_relations", lambda db, student_id, items: seen.setdefault("used", student_id))
    memory_router.api_create_relations([], student_id=123, db=object(), user=object())
    assert seen["resolve_arg"] == 123
    assert seen["used"] == 7


def test_list_relations_uses_resolved_student(monkeypatch):
    seen = _patch(monkeypatch)
    monkeypatch.setattr(memory_router, "list_relations", lambda db, student_id, source_type, source_id: seen.setdefault("used", student_id))
    memory_router.api_list_relations(student_id=123, source_type="note", source_id=1, db=object(), user=object())
    assert seen["resolve_arg"] == 123
    assert seen["used"] == 7
