from datetime import date

from sqlalchemy.orm import Session

from .schemas.learning_flow import LearningFlowEntry
from app.features.p2 import study_plan
from app.features.error_book.service import get_error_book_by_subject


def get_review_flow_entry(
    db: Session,
    student_id: int,
    *,
    error_id: int | None = None,
    knowledge_tag: str | None = None,
) -> LearningFlowEntry:
    """Build a trusted review prompt from an owned error or a knowledge tag."""
    normalized_tag = (knowledge_tag or "").strip()
    if (error_id is None) == (not normalized_tag):
        raise ValueError("必须且只能指定一道错题或一个知识点")

    questions = [
        (group.subject, question)
        for group in get_error_book_by_subject(db, student_id)
        for type_group in group.type_groups
        for question in type_group.questions
    ]
    if error_id is not None:
        match = next(((subject, question) for subject, question in questions if question.error_id == error_id), None)
        if match is None:
            raise ValueError("错题不存在")
        subject, question = match
        tags = "、".join(question.knowledge_tags) or "未标注"
        return LearningFlowEntry(
            kind="review_error",
            title=f"复习一道{subject}错题",
            description=question.stem,
            primary_label="开始复习",
            prompt=(
                "请带我复习下面这道错题。先分析我可能的错因，再出一道同类题让我作答；"
                "不要直接标记为已完成或已掌握，也不要直接生成或保存正式笔记。\n"
                f"来源：错题本\n错题 ID：{question.error_id}\n知识点：{tags}\n"
                f"题干：{question.stem}\n我的错误答案：{question.student_answer or '未作答'}\n"
                f"正确答案：{question.correct_answer or '未提供'}"
            ),
            source_type="error_book",
            source_id=question.error_id,
            evidence=[*question.knowledge_tags, f"错过 {question.error_count} 次"],
        )

    related = [
        (subject, question)
        for subject, question in questions
        if normalized_tag in question.knowledge_tags
    ]
    related.sort(key=lambda item: item[1].error_count, reverse=True)
    question = related[0][1] if related else None
    error_context = (
        f"关联错题 ID：{question.error_id}\n关联错题题干：{question.stem}"
        if question
        else "当前没有关联错题。不要猜测或编造错题 ID。"
    )
    return LearningFlowEntry(
        kind="review_knowledge",
        title=f"复习知识点「{normalized_tag}」",
        description=question.stem if question else "从概念检查和一道基础练习开始。",
        primary_label="开始复习",
        prompt=(
            "请带我复习下面这个知识点。先用一个问题检查我的理解，再根据回答继续；"
            "不要直接标记为已完成或已掌握，也不要直接生成或保存正式笔记。\n"
            f"来源：知识地图\n知识点：{normalized_tag}\n{error_context}"
        ),
        source_type="learning_map",
        source_id=question.error_id if question else None,
        evidence=[normalized_tag, *([f"错过 {question.error_count} 次"] if question else [])],
    )


def get_learning_flow_entry(db: Session, student_id: int) -> LearningFlowEntry:
    from app.models.user import User

    student = db.get(User, student_id)
    student_mode = getattr(student, "mode", "study") if student else "study"
    reminders = study_plan.list_due_study_plan_reminders(
        db,
        [student_id],
        archive_stale=False,
        mode=student_mode,
    )
    # 产品规则：首页「继续学习」只展示今天的计划（planned_date == 今天）。
    # 逾期/历史计划不上首页（可去「管理计划」查看归档），今天没有计划则直接空态，不自动推错题。
    today = date.today()
    today_reminders = [r for r in reminders if r.planned_date == today.isoformat()]
    if today_reminders:
        reminder = today_reminders[0]
        return LearningFlowEntry(
            kind="continue_plan",
            title=f"继续「{reminder.title}」",
            description=f"先完成「{reminder.first_todo_title}」",
            primary_label="继续学习",
            prompt=(
                f"我想继续学习计划「{reminder.title}」，先完成「{reminder.first_todo_title}」。"
                "请根据这份已确认计划带我开始学习。"
            ),
            source_type="study_plan",
            source_id=reminder.plan_id,
            item_id=reminder.first_todo_item_id,
            evidence=[
                "今天",
                f"{reminder.todo_count} 个待完成任务",
                f"{reminder.todo_minutes} 分钟",
            ],
        )

    # 今天没有计划：空态引导，让用户自己告诉助手想学什么。
    return LearningFlowEntry(
        kind="empty",
        title="今天想先学什么",
        description="告诉助手一道不会的题、一个知识点，或者今天的计划。",
        primary_label="开始学习",
        prompt="",
        source_type=None,
        source_id=None,
        evidence=[],
    )
