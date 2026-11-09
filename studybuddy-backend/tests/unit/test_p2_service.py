"""p2 域单元测试（兴趣/反馈/推荐/属性/画像/学习计划持久化）。

覆盖：
- add_interest：新增 + 去重
- submit_feedback：写入 + 查询
- save_recommendation + mark_clicked
- init_attributes：大考成绩折算属性值
- get_latest_attributes + get_attribute_history（成长曲线）
"""

import pytest
from datetime import date

from app.features.p2.schemas import ProfileOnboardingRequest, StudyPlanItemInput, UpdateProfileRequest
from app.features.p2 import attribute, feedback, interests, profile, recommendation, study_plan
from app.models.p2 import StudyPlan


class TestInterest:
    def test_add_interest_manual_approved(self, db):
        result = interests.add_interest(db, student_id=2, tag="篮球", source="manual")
        assert result.tag == "篮球"
        assert result.approved is True

    def test_add_interest_inferred_not_approved(self, db):
        result = interests.add_interest(db, student_id=2, tag="游戏", source="inferred")
        assert result.approved is False

    def test_confirm_interest(self, db):
        result = interests.add_interest(db, student_id=2, tag="科普", source="inferred")
        confirmed = interests.confirm_interest(db, result.id, student_id=2)
        assert confirmed is not None
        assert confirmed.approved is True

    def test_remove_interest(self, db):
        result = interests.add_interest(db, student_id=2, tag="不感兴趣", source="inferred")
        assert interests.remove_interest(db, result.id, student_id=2) is True
        interest_items = interests.list_interests(db, student_id=2)
        assert all(item.id != result.id for item in interest_items)

    def test_add_interest_dedup(self, db):
        interests.add_interest(db, student_id=2, tag="天文", source="manual")
        result2 = interests.add_interest(db, student_id=2, tag="天文", source="manual")
        # 不重复创建
        interest_items = interests.list_interests(db, student_id=2)
        tags = [i.tag for i in interest_items]
        assert tags.count("天文") <= 1

    def test_manual_interest_confirms_existing_pending_interest(self, db):
        tag = "冷启动待确认兴趣-唱歌"
        pending = interests.add_interest(db, student_id=2, tag=tag, source="inferred")
        assert pending.approved is False

        confirmed = interests.add_interest(db, student_id=2, tag=tag, source="manual")

        assert confirmed.approved is True
        assert confirmed.source == "manual"

    def test_list_interests(self, db):
        interests.add_interest(db, student_id=2, tag="音乐", source="manual")
        interest_items = interests.list_interests(db, student_id=2)
        assert any(i.tag == "音乐" for i in interest_items)


class TestFeedback:
    def test_submit_and_list(self, db):
        feedback.submit_feedback(db, student_id=2, feedback_type="duration", content="背了30个单词")
        items = feedback.list_feedback(db, student_id=2)
        assert any("单词" in f.content for f in items)


class TestStudyPlan:
    def test_create_rejects_blank_title_before_database_write(self):
        with pytest.raises(ValueError, match="学习计划名称不能为空"):
            study_plan.create_study_plan(
                object(),
                student_id=2,
                title="   ",
                items=[StudyPlanItemInput(title="复习一般过去时", minutes=10)],
            )

    def test_create_with_description_persists(self, db):
        plan = study_plan.create_study_plan(
            db,
            student_id=2,
            title="英语时态补漏",
            items=[StudyPlanItemInput(title="复盘错题", minutes=15)],
            description="参考最近 3 道时态错题，弟弟要求先补一般过去时",
            context_refs={"error_ids": [10, 11]},
        )
        assert plan.description == "参考最近 3 道时态错题，弟弟要求先补一般过去时"
        assert plan.context_refs == {"error_ids": [10, 11]}
        assert plan.revision == 1

    def test_carry_over_copies_unfinished_items_and_archives_source(self, db):
        source = study_plan.create_study_plan(
            db,
            student_id=2,
            title="旧英语计划",
            items=[
                StudyPlanItemInput(title="已完成语法", minutes=10),
                StudyPlanItemInput(title="继续做题", minutes=15),
                StudyPlanItemInput(title="待复述", minutes=20),
            ],
            planned_date="2026-08-10",
            focus="一般过去时",
        )
        from app.models.p2 import StudyPlanItem

        items = db.query(StudyPlanItem).filter(StudyPlanItem.plan_id == source.id).order_by(StudyPlanItem.sort_order).all()
        items[0].status = "done"
        items[1].status = "in_progress"
        db.commit()

        carried = study_plan.carry_over_study_plan(db, student_id=2, source_plan_id=source.id, created_by=2)

        assert carried.planned_date == date.today().isoformat()
        assert carried.title == "继续：旧英语计划"
        assert carried.focus == "一般过去时"
        assert carried.source_plan_id == source.id
        assert [item.title for item in carried.items] == ["继续做题", "待复述"]
        assert all(item.status == "todo" for item in carried.items)
        fresh_source = db.get(StudyPlan, source.id)
        assert fresh_source is not None
        assert fresh_source.status == "archived"

    def test_carry_over_is_idempotent_for_repeated_confirmation(self, db):
        source = study_plan.create_study_plan(
            db,
            student_id=2,
            title="可继续的旧计划",
            items=[StudyPlanItemInput(title="未完成任务", minutes=15)],
            planned_date="2026-08-10",
        )

        first = study_plan.carry_over_study_plan(db, student_id=2, source_plan_id=source.id, created_by=2)
        second = study_plan.carry_over_study_plan(db, student_id=2, source_plan_id=source.id, created_by=2)

        assert second.id == first.id
        assert db.query(StudyPlan).filter(StudyPlan.source_plan_id == source.id).count() == 1

    def test_carry_over_rejects_other_student_and_empty_source(self, db):
        from app.models.p2 import StudyPlanItem
        from app.models.user import User

        other = User(username="carry-over-other", password_hash="test", role="student", display_name="other")
        db.add(other)
        db.flush()
        other_id = other.id
        other_plan = study_plan.create_study_plan(
            db,
            student_id=other_id,
            title="别人的计划",
            items=[StudyPlanItemInput(title="任务", minutes=10)],
            planned_date="2026-08-10",
        )
        with pytest.raises(PermissionError, match="无权"):
            study_plan.carry_over_study_plan(db, student_id=2, source_plan_id=other_plan.id, created_by=2)

        empty = study_plan.create_study_plan(
            db,
            student_id=2,
            title="已完成计划",
            items=[StudyPlanItemInput(title="完成", minutes=10)],
            planned_date="2026-08-10",
        )
        item = db.query(StudyPlanItem).filter(StudyPlanItem.plan_id == empty.id).one()
        item.status = "done"
        db.commit()
        with pytest.raises(ValueError, match="没有可沿用"):
            study_plan.carry_over_study_plan(db, student_id=2, source_plan_id=empty.id, created_by=2)
        fresh_empty = db.get(StudyPlan, empty.id)
        assert fresh_empty is not None
        assert fresh_empty.status == "active"
    def test_update_study_plan_changes_fields_and_bumps_revision(self, db):
        plan = study_plan.create_study_plan(
            db,
            student_id=2,
            title="英语计划",
            items=[StudyPlanItemInput(title="背单词", minutes=10)],
        )
        updated = study_plan.update_study_plan(
            db, plan.id, title="英语时态计划", description="补时态", revision=1
        )
        assert updated.title == "英语时态计划"
        assert updated.description == "补时态"
        assert updated.revision == 2

    def test_update_study_plan_rejects_stale_revision(self, db):
        plan = study_plan.create_study_plan(
            db,
            student_id=2,
            title="计划",
            items=[StudyPlanItemInput(title="任务", minutes=10)],
        )
        study_plan.update_study_plan(db, plan.id, title="第一次改", revision=1)
        with pytest.raises(ValueError, match="计划已被修改"):
            study_plan.update_study_plan(db, plan.id, title="第二次改", revision=1)

    def test_update_study_plan_handler_rejects_other_student_plan(self, db):
        """学生不能改别人的计划（越权防护，U-041 补丁）。"""
        import asyncio

        from app.features.agent.handlers.learning import _handle_update_study_plan
        from app.models.user import User
        from app.utils.security import hash_password

        other = User(
            username="other-plan-owner",
            password_hash=hash_password("x"),
            role="student",
            display_name="other",
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        plan = study_plan.create_study_plan(
            db,
            student_id=other.id,
            title="别人的计划",
            items=[StudyPlanItemInput(title="任务", minutes=10)],
        )
        # 学生 2 试图改别人的计划
        result = asyncio.run(
            _handle_update_study_plan(
                {"plan_id": plan.id, "revision": 1, "title": "篡改"},
                role="student",
                db=db,
                teacher_id=2,
            )
        )
        assert "error" in result
        assert "无权" in result["error"]
        # 计划未被改
        from app.models.p2 import StudyPlan

        fresh = db.get(StudyPlan, plan.id)
        assert fresh is not None
        assert fresh.title == "别人的计划"


class TestRecommendation:
    def test_save_and_list(self, db):
        recommendation.save_recommendation(
            db,
            student_id=2,
            title="定语从句讲解",
            url="https://bilibili.com/video/BV1xxx",
            reason="针对薄弱点",
            related_interests=["英语"],
        )
        recs = recommendation.list_recommendations(db, student_id=2)
        assert any("定语从句" in r.title for r in recs)

    def test_mark_clicked(self, db):
        rec = recommendation.save_recommendation(db, student_id=2, title="测试视频", url="https://example.com")
        ok = recommendation.mark_clicked(db, rec.id)
        assert ok is True
        recs = recommendation.list_recommendations(db, student_id=2)
        clicked = [r for r in recs if r.id == rec.id]
        if clicked:
            assert clicked[0].clicked is True

    def test_recommendation_boundary_defaults(self, db):
        boundary = recommendation.get_recommendation_boundary(db, student_id=2)
        assert boundary.allowed_platforms == ["bilibili"]
        assert boundary.blocked_keywords == []
        assert boundary.daily_limit == 3

    def test_update_recommendation_boundary(self, db):
        boundary = recommendation.update_recommendation_boundary(
            db,
            student_id=2,
            allowed_platforms=["bilibili"],
            blocked_keywords=["游戏直播", "抽卡"],
            daily_limit=1,
            allow_entertainment_interests=True,
            updated_by=1,
        )
        assert boundary.blocked_keywords == ["游戏直播", "抽卡"]
        assert boundary.daily_limit == 1
        assert boundary.allow_entertainment_interests is True

    def test_recommendation_boundary_blocks_keyword(self, db):
        recommendation.update_recommendation_boundary(
            db,
            student_id=2,
            allowed_platforms=["bilibili"],
            blocked_keywords=["游戏直播"],
            daily_limit=3,
            allow_entertainment_interests=False,
        )
        reason = recommendation.check_recommendation_allowed(db, 2, "bilibili", "英语 游戏直播")
        assert reason == "家长推荐边界已屏蔽关键词：游戏直播"

    def test_recommendation_boundary_blocks_daily_limit(self, db):
        recommendation.update_recommendation_boundary(
            db,
            student_id=2,
            allowed_platforms=["bilibili"],
            blocked_keywords=[],
            daily_limit=0,
            allow_entertainment_interests=False,
        )
        reason = recommendation.check_recommendation_allowed(db, 2, "bilibili", "英语语法")
        assert reason == "今天推荐资源已达到家长设置的上限：0 个"


class TestAttributes:
    def test_init_attributes_score_conversion(self, db):
        """大考成绩折算：60→60, 80→80, 100→100。"""
        result = attribute.init_attributes(
            db,
            student_id=2,
            exam_scores={
                "chinese": 85,
                "math": 90,
                "english": 78,
                "pe": 80,
            },
        )
        snap = result.snapshot
        assert snap["chinese"] == 85  # 60 + (85-60)*1.0
        assert snap["math"] == 90
        assert snap["engagement"] == 50  # 初始值
        assert snap["mastered_count"] == 0

    def test_get_latest_attributes(self, db):
        attribute.init_attributes(db, student_id=2, exam_scores={"math": 70})
        latest = attribute.get_latest_attributes(db, student_id=2)
        assert latest is not None
        assert latest.source == "init"

    def test_get_attribute_history(self, db):
        attribute.init_attributes(db, student_id=2, exam_scores={"math": 70})
        attribute.init_attributes(db, student_id=2, exam_scores={"math": 80})
        history = attribute.get_attribute_history(db, student_id=2)
        assert len(history) >= 2  # 两条快照

    def test_get_latest_returns_none_if_not_init(self, db):
        result = attribute.get_latest_attributes(db, student_id=999)
        assert result is None


class TestAttributeEvidence:
    """PR-08：无证据默认 60 分不再展示为真实能力分。

    snapshot 新增 subject_sources 标记每个能力项的证据来源：
    - exam_score：init_attributes 真实录入的大考成绩
    - manual_adjust：update_attributes 被 agent 微调叠加过
    - null：默认占位，无真实证据，前端展示「数据不足」
    """

    def test_init_marks_only_provided_subjects_as_exam_score(self, db):
        """只录入部分科目时，未录科目不应被标记为有证据。"""
        result = attribute.init_attributes(
            db,
            student_id=2,
            exam_scores={"chinese": 85, "math": 90},
        )
        sources = result.snapshot.get("subject_sources", {})
        assert sources.get("chinese") == "exam_score"
        assert sources.get("math") == "exam_score"
        # 未录入的科目不得标记为有证据
        assert sources.get("english") is None
        assert sources.get("pe") is None
        assert sources.get("engagement") is None

    def test_init_missing_subjects_not_filled_with_default_60(self, db):
        """未录入的科目不得写入误导性的 60 占位分。"""
        result = attribute.init_attributes(
            db,
            student_id=2,
            exam_scores={"math": 90},
        )
        snap = result.snapshot
        sources = snap.get("subject_sources", {})
        # math 有真实证据，保留折算分
        assert snap["math"] == 90
        assert sources["math"] == "exam_score"
        # 未录入科目：要么不写假分，要么写了但明确标记无证据
        for subject in ("chinese", "english", "pe", "engagement"):
            assert sources.get(subject) is None, f"{subject} 不应标记为有证据"

    def test_onboarding_does_not_create_attribute_evidence(self, db):
        """冷启动画像补全不产生能力分证据。"""
        from app.features.p2.schemas import ProfileOnboardingRequest

        req = ProfileOnboardingRequest(
            grade="八年级",
            semester="上册",
            interests=["篮球"],
        )
        profile.save_profile_onboarding(db, student_id=2, req=req, actor_role="student")
        latest = attribute.get_latest_attributes(db, student_id=2)
        assert latest is not None
        sources = latest.snapshot.get("subject_sources", {})
        # onboarding 不产生任何能力分证据
        for subject in ("chinese", "math", "english", "pe", "engagement"):
            assert sources.get(subject) is None, f"{subject} 不应来自 onboarding 证据"

    def test_update_attributes_marks_adjusted_fields_as_manual(self, db):
        """agent 微调过的字段视为有证据（manual_adjust）。"""
        attribute.init_attributes(db, student_id=2, exam_scores={"math": 90})
        result = attribute.update_attributes(
            db, student_id=2, delta={"english": 5}, reason="英语练习反馈"
        )
        sources = result.snapshot.get("subject_sources", {})
        assert sources.get("english") == "manual_adjust"
        # 原有 exam_score 证据保留
        assert sources.get("math") == "exam_score"
        # 未触及的科目仍无证据
        assert sources.get("chinese") is None

    def test_update_attributes_without_history_no_default_60(self, db):
        """无历史快照时微调，不得用全 60 基准起步伪造能力分。"""
        result = attribute.update_attributes(
            db, student_id=2, delta={"math": 5}, reason="首次练习反馈"
        )
        sources = result.snapshot.get("subject_sources", {})
        assert sources.get("math") == "manual_adjust"
        # 未触及科目不得标记为有证据
        assert sources.get("chinese") is None
        assert sources.get("english") is None
        assert sources.get("engagement") is None

    def test_old_snapshot_without_subject_sources_inferred_as_no_evidence(self, db):
        """旧快照没有 subject_sources 字段时，读取兼容推断为无证据（保守）。"""
        from app.models.p2 import StudentAttribute

        # 模拟一条旧数据：全 60，无 subject_sources
        db.add(
            StudentAttribute(
                student_id=2,
                snapshot={
                    "chinese": 60,
                    "math": 60,
                    "english": 60,
                    "pe": 60,
                    "engagement": 50,
                    "mastered_count": 0,
                },
                source="init",
            )
        )
        db.flush()
        latest = attribute.get_latest_attributes(db, student_id=2)
        assert latest is not None
        sources = latest.snapshot.get("subject_sources", {})
        # 旧 init 全 60 数据保守判为无证据，不恢复默认 60 作为真实分
        for subject in ("chinese", "math", "english", "pe", "engagement"):
            assert sources.get(subject) is None, f"旧无证据 {subject} 不应被推断为有证据"

    def test_history_returns_subject_sources(self, db):
        """成长曲线历史也带 subject_sources，前端可判断每个时间点是否有证据。"""
        attribute.init_attributes(db, student_id=2, exam_scores={"math": 90})
        attribute.update_attributes(db, student_id=2, delta={"math": 5}, reason="进步")
        history = attribute.get_attribute_history(db, student_id=2)
        assert len(history) >= 2
        for snap in history:
            assert "subject_sources" in snap.snapshot


class TestUpdateProfile:
    """update_profile：对话中学到明确事实时静默增量更新画像。"""

    def test_incremental_update_overwrites_provided_fields_only(self, db):
        """只覆盖传入字段，未传字段保留。"""
        profile.save_profile_onboarding(
            db,
            student_id=2,
            req=ProfileOnboardingRequest(grade="八年级", semester="上册"),
            actor_role="student",
        )
        profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(school="实验中学"),
            actor_role="student",
        )
        latest = attribute.get_latest_attributes(db, student_id=2)
        assert latest.snapshot.get("grade") == "八年级"
        assert latest.snapshot.get("school") == "实验中学"

    def test_add_interests_dedup_and_remove_by_tag(self, db):
        """add 走去重，remove 按 tag 删。"""
        profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(add_interests=["篮球", "篮球", "天文"]),
            actor_role="student",
        )
        tags = {i.tag for i in interests.list_interests(db, student_id=2)}
        assert tags == {"篮球", "天文"}
        profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(remove_interests=["篮球"]),
            actor_role="student",
        )
        tags = {i.tag for i in interests.list_interests(db, student_id=2)}
        assert tags == {"天文"}

    def test_does_not_write_learning_feedback(self, db):
        """静默更新不写 learning_feedback（避免重复调用堆重复反馈）。"""
        profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(
                grade="八年级",
                study_preferences={"preferred_time": "下午"},
            ),
            actor_role="student",
        )
        # 再次调用同样字段，feedback 仍不应被写入
        profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(grade="八年级"),
            actor_role="student",
        )
        assert feedback.list_feedback(db, student_id=2) == []

    def test_does_not_touch_capability_evidence(self, db):
        """不碰能力分与 subject_sources 证据。"""
        attribute.init_attributes(db, student_id=2, exam_scores={"math": 90})
        profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(grade="八年级", weak_subjects=["英语"]),
            actor_role="student",
        )
        latest = attribute.get_latest_attributes(db, student_id=2)
        sources = latest.snapshot.get("subject_sources", {})
        assert sources.get("math") == "exam_score"
        assert latest.snapshot.get("weak_subjects") == ["英语"]

    def test_returns_summary_clears_onboarding_when_required_fields_filled(self, db):
        """补齐冷启动必填（grade + weak_subjects，14fad7a 后 semester/preferences 不再必填）后 needs_onboarding 转 False。"""
        summary = profile.update_profile(
            db,
            student_id=2,
            req=UpdateProfileRequest(
                grade="八年级",
                weak_subjects=["英语"],
                study_preferences={"preferred_time": "下午"},
            ),
            actor_role="student",
        )
        assert summary.needs_onboarding is False


def test_update_profile_merges_textbook_versions(db):
    """M2 C：新增语文教材版本后原英语版本仍保留；同科目更新覆盖。"""
    profile.update_profile(
        db,
        student_id=2,
        req=UpdateProfileRequest(textbook_versions={"英语": "译林版"}),
        actor_role="student",
    )
    profile.update_profile(
        db,
        student_id=2,
        req=UpdateProfileRequest(textbook_versions={"语文": "人教版"}),
        actor_role="student",
    )
    latest = attribute.get_latest_attributes(db, student_id=2)
    assert latest.snapshot["textbook_versions"] == {"英语": "译林版", "语文": "人教版"}

    profile.update_profile(
        db,
        student_id=2,
        req=UpdateProfileRequest(textbook_versions={"语文": "部编版"}),
        actor_role="student",
    )
    latest = attribute.get_latest_attributes(db, student_id=2)
    assert latest.snapshot["textbook_versions"] == {"英语": "译林版", "语文": "部编版"}
