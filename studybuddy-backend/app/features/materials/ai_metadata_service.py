"""素材 AI 元数据：name/tags/summary 生成，失败不阻塞识别"""
import json
from pydantic import BaseModel
from app.core import ai_service
from app.prompts import render

class MaterialMetadata(BaseModel):
    name: str
    tags: list[str]
    summary: str

async def generate_material_metadata(markdown: str, filename: str) -> MaterialMetadata | None:
    if not markdown or not markdown.strip():
        return None
    try:
        prompt = render("material_vision/material_metadata", filename=filename, markdown=markdown[:4000])
        resp = await ai_service.call_llm(
            messages=[{"role": "user", "content": prompt}],
            system="你是素材元数据助手，只输出 JSON",
            max_tokens=300,
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return None
        content = getattr(getattr(choices[0], "message", None), "content", None)
        if not isinstance(content, str) or not content.strip():
            return None
        # 提取 JSON
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(content[start:end+1])
        name = str(data.get("name") or "").strip()[:30]
        tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
        tags = list(dict.fromkeys(tags))[:5]  # 去重上限 5
        summary = str(data.get("summary") or "").strip()[:80]
        if not name and not tags and not summary:
            return None
        return MaterialMetadata(name=name, tags=tags, summary=summary)
    except Exception:
        return None
