"""兴趣空间最小跑通测试。

覆盖：注册/登录鉴权、资源搜索工具 handler、chat 路由（mock LLM）。
LLM 真实调用放 live 用例（tests/live/），本地 mock 保证 CI 可跑。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.features.agent import agent_core
from hobby.database import Base, get_db
from hobby.hobby_tools import handle_search_resource
from hobby.main import app

# SQLite 下 BIGINT 主键不会自动递增（只有 INTEGER PRIMARY KEY 才是 rowid），
# 编译时把 BigInteger 映射成 INTEGER，保证测试库自增正常（MySQL 不受影响）。
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):
    return "INTEGER"


# 用 SQLite 内存库跑测试，隔离本地 MySQL；共享同一个连接保证所有测试看到同一份数据
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def _db_engine():
    Base.metadata.create_all(engine)
    yield engine


@pytest.fixture()
def db(_db_engine):
    session = TestingSession()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _register(client) -> dict:
    import uuid

    resp = client.post(
        "/api/auth/register",
        json={"username": f"user{uuid.uuid4().hex[:8]}", "password": "secret123"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------- auth ----------


def test_register_duplicate(client, fresh_user):
    resp = client.post(
        "/api/auth/register",
        json={"username": fresh_user["display_name"], "password": "secret123"},
    )
    assert resp.status_code == 409


# ---------- chat 路由（mock LLM，不真实调用）----------


def test_chat_returns_reply(client, db):
    # mock 掉 LLM：返回纯文本回复
    async def fake_call_llm(messages, tools=None, system=None, max_tokens=4096):
        class _Choice:
            class _Msg:
                content = "好呀，我们一起练唱歌。先定个七天试学的最终作品吧！"
                tool_calls = None

            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()

    original = agent_core.ai_service.call_llm
    agent_core.ai_service.call_llm = fake_call_llm
    try:
        token = _register(client)["access_token"]
        resp = client.post(
            "/api/chat/",
            json={"message": "我想学唱歌"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert "唱歌" in resp.json()["reply"]
    finally:
        agent_core.ai_service.call_llm = original


# 每个测试独立注册用户名，避免共享库残留
@pytest.fixture()
def fresh_user(client, db):
    return _register(client)


def test_register_and_login(client, fresh_user):
    data = fresh_user
    resp = client.post(
        "/api/auth/login",
        json={"username": data["display_name"], "password": "secret123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == data["user_id"]


def test_login_wrong_password(client, fresh_user):
    resp = client.post(
        "/api/auth/login",
        json={"username": fresh_user["display_name"], "password": "wrong"},
    )
    assert resp.status_code == 401


def test_chat_llm_failure_degrades(client, db):
    """LLM 重试耗尽抛 RuntimeError 时，chat 应降级提示而非 500（P1 修复验证）。"""

    async def boom(messages, tools=None, system=None, max_tokens=4096):
        raise RuntimeError("LLM 重试耗尽")

    original = agent_core.ai_service.call_llm
    agent_core.ai_service.call_llm = boom
    try:
        token = _register(client)["access_token"]
        resp = client.post(
            "/api/chat/",
            json={"message": "我想学唱歌"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert "稍后再试" in resp.json()["reply"]
    finally:
        agent_core.ai_service.call_llm = original


def test_chat_requires_auth(client):
    resp = client.post("/api/chat/", json={"message": "hi"})
    assert resp.status_code in (401, 403)


def _asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


asyncio_run = _asyncio_run


# ---------- 资源搜索工具（复用底座 B站搜索，不落库）----------

def test_search_resource_returns_candidates(db, monkeypatch):
    """mock 底座 B站搜索：返回候选列表给 AI 推荐（不落库）。"""

    async def fake_search(keyword):
        return [
            {
                "bvid": "BV1xx",
                "title": "唱歌气息练习教程",
                "author": "某UP主",
                "play": 12345,
                "url": "https://www.bilibili.com/video/BV1xx",
                "desc": "气息练习讲解",
                "danmaku_sample": ["讲得好", "有用"],
            },
            {
                "bvid": "BV1yy",
                "title": "发声技巧入门",
                "author": "另一UP",
                "play": 800,
                "url": "https://www.bilibili.com/video/BV1yy",
                "desc": "入门教学",
                "danmaku_sample": [],
            },
        ]

    import app.features.question_bank.bili_search_service as bss

    monkeypatch.setattr(bss, "search_and_enrich", fake_search)
    result = asyncio_run(handle_search_resource({"keyword": "唱歌 气息练习 教程"}, db, 1))
    assert result["ok"] is True
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["title"] == "唱歌气息练习教程"
    assert result["candidates"][0]["url"].startswith("https://www.bilibili.com/")


def test_search_resource_empty_keyword(db):
    result = asyncio_run(handle_search_resource({"keyword": "  "}, db, 1))
    assert result["ok"] is False
    assert "关键词" in result["error"]


def test_search_resource_no_result(db, monkeypatch):
    async def fake_search(keyword):
        return []

    import app.features.question_bank.bili_search_service as bss

    monkeypatch.setattr(bss, "search_and_enrich", fake_search)
    result = asyncio_run(handle_search_resource({"keyword": "不存在的兴趣"}, db, 1))
    assert result["ok"] is False
    assert "没搜到" in result["error"]


def test_search_resource_failure_degrades(db, monkeypatch):
    """外部搜索异常必须结构化返回，不让 AI 声称成功、不抛 500。"""

    async def fake_search(keyword):
        raise RuntimeError("B站 API 挂了")

    import app.features.question_bank.bili_search_service as bss

    monkeypatch.setattr(bss, "search_and_enrich", fake_search)
    result = asyncio_run(handle_search_resource({"keyword": "唱歌"}, db, 1))
    assert result["ok"] is False
    assert "不可用" in result["error"]
