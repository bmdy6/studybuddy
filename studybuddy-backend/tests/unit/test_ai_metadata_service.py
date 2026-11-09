import pytest
from app.features.materials.ai_metadata_service import generate_material_metadata

@pytest.mark.asyncio
async def test_generate_success(monkeypatch):
    async def fake_call_llm(**kwargs):
        class R:
            choices = [type("C", (), {"message": type("M", (), {"content": '{"name": "一次函数", "tags": ["函数"], "summary": "摘要"}'})()})()]
        return R()
    monkeypatch.setattr("app.features.materials.ai_metadata_service.ai_service.call_llm", fake_call_llm)
    res = await generate_material_metadata("markdown 内容", "file.pdf")
    assert res and res.name == "一次函数"

@pytest.mark.asyncio
async def test_generate_fail_returns_none(monkeypatch):
    async def fake_fail(**kwargs):
        raise RuntimeError("LLM fail")
    monkeypatch.setattr("app.features.materials.ai_metadata_service.ai_service.call_llm", fake_fail)
    res = await generate_material_metadata("md", "f.pdf")
    assert res is None
