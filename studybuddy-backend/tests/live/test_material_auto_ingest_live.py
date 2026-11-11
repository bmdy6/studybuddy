"""素材懒识别 live 测试：上传只落库（pending），首次读取触发真实 MiMo 视觉转 MD 并缓存。"""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.material import Material
from app.models.user import User
from app.features.materials import extraction_service, service as material_service


TEST_IMAGE = Path(__file__).resolve().parents[3] / "studybuddy-promo" / "screenshots" / "03-exam-taking.png"


@pytest.mark.live
def test_material_upload_lazy_recognizes_real_image(db, tmp_path, monkeypatch) -> None:
    """真实图片：上传只落库（pending 不识别），首次 ensure_extraction 转 MD 并缓存，文件级去重仍在上传时生效。"""
    if not TEST_IMAGE.exists():
        pytest.skip(f"测试图片不存在: {TEST_IMAGE}")

    student = db.get(User, 2)
    assert student is not None
    image_bytes = TEST_IMAGE.read_bytes()
    upload_root = tmp_path / "uploads"
    target = upload_root / "materials" / "live-material.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(material_service, "_PROJECT_ROOT", str(tmp_path))

    def save_local(data: bytes, _ext: str) -> str:
        target.write_bytes(data)
        return "local:materials/live-material.png"

    started = time.perf_counter()
    with patch.object(material_service, "upload_file", side_effect=save_local):
        first = asyncio.run(
            material_service.upload_material_async(
                db,
                image_bytes,
                "png",
                "live 懒识别素材",
                "image",
                [],
                student,
            )
        )
        # 上传不再同步识别：状态留 pending，无 Markdown
        material = db.get(Material, first.material_id)
        assert material is not None
        assert material.recognition_status == "pending"
        assert not (material.recognized_markdown or "").strip()

        # 文件级去重仍在上传时生效：同 SHA 第二次上传命中已有素材
        duplicate = asyncio.run(
            material_service.upload_material_async(
                db,
                image_bytes,
                "png",
                "live 重复素材",
                "image",
                [],
                student,
            )
        )
        assert duplicate.is_duplicate is True
        assert duplicate.material_id == first.material_id

        # 首次读取触发懒识别（read_material 内部即调 ensure_extraction）
        asyncio.run(extraction_service.ensure_extraction(db, first.material_id, student, force=False))
    elapsed = time.perf_counter() - started

    db.refresh(material)
    assert material.recognition_status in {"recognized", "needs_review"}
    assert (material.recognized_markdown or "").strip()
    assert material.recognition_provider
    print(
        f"\n[素材懒识别] 状态={material.recognition_status} "
        f"provider={material.recognition_provider} 耗时={elapsed:.1f}s"
    )
