"""Architecture boundary regression tests.

These tests guard the project rule that routers stay thin and call public
service APIs for business state changes and URL construction.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_exam_batch_router_uses_public_service_boundaries():
    source = _read("app/features/exams/router_exam_batch.py")

    assert "exam_batch_service._to_item" not in source
    assert "db.commit()" not in source


def test_material_router_does_not_import_private_url_builder():
    source = _read("app/features/materials/router.py")

    assert "_build_url" not in source


def test_p2_attribute_init_uses_resolved_student_id():
    source = _read("app/features/p2/router.py")

    assert "sid = resolve_accessible_student_id(db, user, student_id)" in source
    assert "attribute.init_attributes(db, sid, req.exam_scores)" in source
