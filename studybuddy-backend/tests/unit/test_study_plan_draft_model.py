"""StudyPlanDraft model 字段与表名测试。

default 值（status='pending'）是 SQL 级别默认，flush 时才应用，
实例化时不应用，故这里测传入值与表名；default 由 service/db 测试覆盖。
"""

from app.models.study_plan_draft import StudyPlanDraft


def test_study_plan_draft_fields_and_table():
    d = StudyPlanDraft(
        student_id=1,
        chat_session_id=10,
        draft_data={"title": "数学复习", "items": []},
        revision=1,
        status="pending",
    )
    assert d.__tablename__ == "study_plan_draft"
    assert d.status == "pending"
    assert d.created_plan_id is None
    assert d.revision == 1
    assert d.draft_data["title"] == "数学复习"
