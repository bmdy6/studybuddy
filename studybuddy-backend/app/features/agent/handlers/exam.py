"""Agent 试卷/错题/作业批改工具处理器。

拆自 app/core/agent_loop.py。create_exam 出题落库、query_error_book 错题本查询、
import_errors_process/grade 错题导入解析判分、grade/recognize/save_graded_homework_photo
拍题批改链路。_can_access_exam_batch/_load_exam_batch_photos/_get_exam_batch_photo_paths
是 exam 专用辅助（照片批次权限/加载路径）。
依赖方向：单向依赖 context（_resolve_tool_student_id）+ core.ai_service（更稳定 #2）
+ features.exams/materials（同层业务）。error_book/batch_service/access_service/photo_grading
等在函数内按需 import（避免顶层耦合）。
"""
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core import ai_service
from app.core.grading import grade
from app.prompts import load
from app.features.exams.schemas.exam import ExamImportRequest
from app.features.exams.service import create_practice_exam, import_exam
from app.features.materials.markdown_extraction_service import extract_llm_message_text
from app.utils.image import encode_image_for_vision
from ..context import _resolve_tool_student_id

logger = logging.getLogger(__name__)


async def _handle_grade_light_answer(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """对话轻练判分（MVP-A）：复用 core.grading 确定性判分引擎，纯计算零落库。

    轻练硬边界：不建考试记录、不进错题本、不算成绩/掌握度/进步——
    本工具不写任何表；判分与试卷链路共用同一引擎保证一致性（SOL 方案要求）。
    """
    if role != "student":
        raise PermissionError("只有学生能使用对话轻练判分")
    _resolve_tool_student_id(args, role, db, teacher_id)  # 学生永远只用自己
    q = args.get("question") or {}
    student_answer = str(args.get("student_answer") or "")
    try:
        question = _LightQuestion(
            score=float(q.get("score") or 0),
            answer_json=q.get("answer"),
            type=q.get("type"),
            options=q.get("options") or [],
        )
        rule = _LightRule(**q["grading"])
    except (KeyError, TypeError, ValueError) as e:
        return {"error": f"题目或判分规则不完整，请重新出题：{e}"}
    result = grade(student_answer, question, rule)
    return {
        "is_correct": result.is_correct,
        "score": result.score,
        "max_score": question.score,
        "detail": result.detail,
        "needs_manual": result.needs_manual,
    }


class _LightQuestion:
    """core.grading.Question Protocol 的轻量实现（无 DB 依赖）。"""

    def __init__(self, score: float, answer_json: Any, type: str | None, options: list[str]):
        self.score = score
        self.answer_json = answer_json
        self.type = type
        self.options = options


class _LightRule:
    """core.grading.GradingRule Protocol 的轻量实现（无 DB 依赖）。"""

    def __init__(self, rule_type: str, matcher: str, match_params: dict | None = None):
        self.rule_type = rule_type
        self.matcher = matcher
        self.match_params = match_params or {}


async def _handle_create_exam(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    if role != "teacher":
        raise PermissionError("只有老师/家长才能出题")
    try:
        req = ExamImportRequest(**args)
    except Exception as e:  # noqa: BLE001
        return {"error": f"试卷格式不合法，请重试：{e}"}
    result = import_exam(db, req, teacher_id, status="published")
    return {"exam_id": result.exam_id, "title": result.title, "question_count": result.question_count}


async def _handle_create_practice_exam(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """学生自练卷：出卷 + 自动分发给自己 + 关联 plan_item（U-045）。"""
    if role != "student":
        raise PermissionError("只有学生能出自练卷")
    # 自练卷默认 immediate（做完一题立即对错），与工具描述/prompt 一致；
    # AI 未显式传 feedback_mode 时 ExamImportRequest schema 默认 after_submit，这里兜底修正。
    practice_args = {**args, "feedback_mode": args.get("feedback_mode") or "immediate"}
    try:
        req = ExamImportRequest(**practice_args)
    except Exception as e:  # noqa: BLE001
        return {"error": f"试卷格式不合法，请重试：{e}"}
    plan_item_id_raw = args.get("plan_item_id")
    try:
        plan_item_id = int(plan_item_id_raw) if plan_item_id_raw else None
    except (TypeError, ValueError):
        return {"error": "计划项 id 不合法"}
    try:
        return create_practice_exam(db, teacher_id, req, plan_item_id)
    except PermissionError as e:
        return {"error": str(e)}
    except ValueError as e:
        return {"error": str(e)}



async def _handle_query_practice_exam_result(
    args: dict[str, Any], role: str, db: Session, teacher_id: int
) -> dict[str, Any]:
    """按计划项读取学生最近一次已提交自练卷结果，供任务老师复盘。"""
    if role != "student":
        raise PermissionError("只有学生能查询自己的自练卷结果")
    from app.features.exams.grading_service import get_exam_record_result
    from app.models.exam_assignment import ExamAssignment
    from app.models.exam_record import ExamRecord
    from app.models.user import User

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    try:
        plan_item_id = int(args.get("plan_item_id"))
    except (TypeError, ValueError):
        return {"error": "计划项 id 不合法"}

    record = (
        db.query(ExamRecord)
        .join(ExamAssignment, ExamAssignment.exam_id == ExamRecord.exam_id)
        .filter(
            ExamAssignment.student_id == sid,
            ExamAssignment.plan_item_id == plan_item_id,
            ExamAssignment.status != "cancelled",
            ExamRecord.student_id == sid,
            ExamRecord.status.in_(["submitted", "graded"]),
        )
        .order_by(ExamRecord.submitted_at.desc(), ExamRecord.id.desc())
        .first()
    )
    if not record:
        return {"error": "这个任务还没有正式提交的自练卷结果"}
    student = db.get(User, sid)
    result = get_exam_record_result(db, record.id, student)
    answers = [answer.model_dump() for answer in result.answers]
    graded_answers = [answer for answer in answers if answer["is_correct"] is not None]
    pending_count = len(answers) - len(graded_answers)
    feedback_hidden = result.feedback_mode == "hidden"
    correct_count = None if feedback_hidden else sum(answer["is_correct"] is True for answer in graded_answers)
    if feedback_hidden:
        summary = "已读取正式自练卷结果；答案与判分暂未公开"
    else:
        summary = f"已读取正式自练卷结果：已判 {len(graded_answers)} 题，答对 {correct_count} 题"
        if pending_count:
            summary += f"，另有 {pending_count} 题待批改"
    return {
        "exam_id": result.exam_id,
        "exam_record_id": result.exam_record_id,
        "plan_item_id": plan_item_id,
        "title": result.exam_title,
        "status": result.status,
        "feedback_mode": result.feedback_mode,
        "total_score": result.total_score,
        "correct_count": correct_count,
        "graded_count": len(graded_answers),
        "pending_count": pending_count,
        "question_count": len(answers),
        "answers": answers,
        "summary": summary,
    }


async def _handle_query_error_book(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查询错题本：复用 error_book.service.get_error_book。"""
    from app.features.error_book.service import get_error_book

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    tag = args.get("subject")  # 复用 subject 参数做 tag 过滤
    try:
        groups = get_error_book(db, sid, tag)
    except Exception as e:
        return {"error": str(e)}

    # 转成 agent 易读摘要（题干截断避免爆 token）
    # 跨分组去重：同一题关联多个 tag 时，按 tag 展开会重复，这里只保留首次出现（问题2）
    seen_qids: set[int] = set()
    items = []
    for g in groups[:5]:  # 最多 5 组
        qs = []
        for q in g.questions:
            if q.question_id in seen_qids:
                continue
            seen_qids.add(q.question_id)
            qs.append(
                {
                    "stem": q.stem[:80],
                    "your": q.student_answer[:40],
                    "correct": q.correct_answer[:40],
                    "wrong_times": q.error_count,
                }
            )
            if len(qs) >= 3:
                break
        if qs:
            items.append({"tag": g.tag, "count": g.error_count, "questions": qs})
    total_unique = len(seen_qids)
    return {
        "groups": items,
        "summary": f"共 {len(groups)} 个知识点有错题，去重后 {total_unique} 道题",
    }



async def _handle_import_errors_process(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """处理错题导入批次：合成 PDF + 视觉解析每题作答。

    哥哥在前端上传照片建批次后发来 batch_id，agent 调此工具跑 synthesize+parse。
    解析失败返回 fallback_hint，agent 据此引导哥哥口述题目走纯文本入本。
    """
    from app.features.exams import batch_service as exam_batch_service

    batch_id = args.get("batch_id")
    if not batch_id:
        return {"error": "缺少 batch_id"}
    batch = exam_batch_service.get_batch(db, int(batch_id))
    if not batch:
        return {"error": f"批次 {batch_id} 不存在"}

    # 合成 PDF（留档，失败不阻塞解析）
    try:
        exam_batch_service.synthesize_pdf(db, batch)
    except Exception:  # noqa: BLE001  合成失败不影响解析
        logger.warning("错题导入合成 PDF 失败：batch_id=%s", batch_id, exc_info=True)

    # 视觉解析
    try:
        result = await exam_batch_service.parse_photos_with_vision(db, batch)
    except Exception as e:  # noqa: BLE001  视觉失败回退手动
        return {
            "error": f"视觉解析失败：{e}",
            "fallback_hint": "解析没成功，请哥哥在对话里口述每题的作答，我直接帮你入错题本（不需要照片）。",
            "batch_id": batch_id,
        }

    batch.status = "parsed"
    db.commit()

    questions = [{"no": q.no, "answer": q.answer, "score": q.score} for q in result.questions]
    if not questions:
        return {
            "error": "未识别到题目（照片可能不清楚或非试卷）",
            "fallback_hint": "没识别到题目，请哥哥在对话里口述每题的作答，我直接帮你入错题本。",
            "batch_id": batch_id,
        }
    return {
        "batch_id": batch_id,
        "questions": questions,
        "summary": f"已解析 {len(questions)} 道题，请哥哥确认判分模式（有老师分数？有标准答案？都没有？）",
    }


async def _handle_import_errors_grade(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """对已解析的错题导入批次判分并入错题本。家长和学生都可调（错题本是学生自己的）。

    三模式：has_score(传 manual_scores) / no_score_has_answer(传 standard_answers) /
    no_score_no_answer(都不传，全部判错让用户复核）。
    不传 parsed_questions 则后端重新解析。
    """
    from app.features.exams import batch_service as exam_batch_service

    batch_id = args.get("batch_id")
    grade_mode = args.get("grade_mode", "no_score_no_answer")
    if grade_mode not in ("has_score", "no_score_has_answer", "no_score_no_answer"):
        return {"error": f"grade_mode 非法：{grade_mode}"}
    if not batch_id:
        return {"error": "缺少 batch_id"}
    batch = exam_batch_service.get_batch(db, int(batch_id))
    if not batch:
        return {"error": f"批次 {batch_id} 不存在"}

    # 不传 parsed_questions 就重新解析（grade_service 内部会重新 parse）
    parsed_questions = args.get("parsed_questions")
    parsed = None
    if parsed_questions:
        parsed = [exam_batch_service.ParsedQuestion(**q) for q in parsed_questions]

    manual_scores = args.get("manual_scores")
    standard_answers = args.get("standard_answers")

    try:
        result = exam_batch_service.grade_and_save_errors(
            db,
            batch,
            parsed or [],
            grade_mode,
            manual_scores,
            standard_answers,
        )
    except Exception as e:  # noqa: BLE001  判分失败可重试
        return {"error": f"判分失败：{e}", "batch_id": batch_id, "retryable": True}
    return result


def _can_access_exam_batch(db: Session, role: str, user_id: int, student_id: int) -> bool:
    """Agent 工具访问批次时复用学生/家长边界。"""
    if role == "student":
        return user_id == student_id
    from app.core.auth import access_service

    return access_service.teacher_can_access_student(db, user_id, student_id)


def _load_exam_batch_photos(batch: Any) -> list[dict[str, Any]]:
    """读取批次照片为 OpenAI vision content。"""
    content: list[dict[str, Any]] = []
    for photo in _get_exam_batch_photo_paths(batch):
        content.append(encode_image_for_vision(photo))
    return content


def _get_exam_batch_photo_paths(batch: Any) -> list[str]:
    """读取批次原始照片路径，供外部 OCR 和视觉模型复用。"""
    import os

    from app.features.exams import batch_service as exam_batch_service

    folder = batch.folder_name or f"batch_{batch.id}"
    folder_path = os.path.join(exam_batch_service.UPLOAD_ROOT, folder)
    if not os.path.isdir(folder_path):
        return []
    return sorted(
        os.path.join(folder_path, filename)
        for filename in os.listdir(folder_path)
        if filename.lower().endswith((".jpg", ".jpeg", ".png"))
    )


async def _handle_grade_homework_photo(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """对拍题批改批次逐题给出答案、错因和知识点，不自动入错题本。"""
    from app.features.exams import batch_service as exam_batch_service, photo_grading_service

    batch_id = args.get("batch_id")
    if not batch_id:
        return {"error": "缺少 batch_id"}
    batch = exam_batch_service.get_batch(db, int(batch_id))
    if not batch:
        return {"error": f"批次 {batch_id} 不存在"}
    if not _can_access_exam_batch(db, role, teacher_id, batch.student_id):
        return {"error": "无权访问该拍题批改批次"}

    try:
        exam_batch_service.synthesize_pdf(db, batch)
    except Exception:  # noqa: BLE001  留档失败不阻塞批改
        logger.warning("拍题批改合成 PDF 失败：batch_id=%s", batch_id, exc_info=True)

    confirmed_markdown = str(args.get("confirmed_markdown") or "").strip()
    if not confirmed_markdown:
        confirmed_questions = exam_batch_service.confirmed_review_to_parsed_questions(batch)
        if confirmed_questions:
            confirmed_markdown = "\n".join(
                f"{q.no}. 学生确认作答：{q.answer}" for q in confirmed_questions
            )
    content: list[dict[str, Any]]
    if confirmed_markdown:
        content = [
            {
                "type": "text",
                "text": (
                    "下面是用户已经确认过的拍题 Markdown 识别稿。请基于这份确认稿逐题批改，"
                    "自行判断学科 subject，给出题目、学生作答、正确答案、是否正确、错误点、知识点和简短讲解。"
                    "如果确认稿中包含用户对学生作答的修正，先按修正后的作答批改；"
                    "返回 JSON 前不需要输出复述文本，但 questions[].student_answer 必须来自 confirmed_markdown。"
                    "如果正确答案仍不确定，confidence=low 且 needs_review=true。"
                    '只返回JSON：{"subject":"识别出的学科","questions":[{"no":"题号","stem":"题目内容或摘要","student_answer":"学生作答",'
                    '"correct_answer":"正确答案，不确定则空字符串","is_correct":false,'
                    '"error_point":"错因或空字符串","knowledge_tags":["学科","知识点"],'
                    '"explanation":"简短讲解","confidence":"high|medium|low","needs_review":true}]}'
                    f"\n\nMarkdown识别稿：\n{confirmed_markdown}"
                ),
            }
        ]
    else:
        content = _load_exam_batch_photos(batch)

    if not content:
        return {
            "error": "该批次没有可批改的照片",
            "fallback_hint": "请重新上传清晰的题目照片，或直接把题目和你的答案发给我。",
            "batch_id": batch_id,
        }

    if not confirmed_markdown:
        content.append(
            {
                "type": "text",
                "text": load("exam_vision/homework_grading"),
            }
        )

    try:
        resp = await ai_service.call_llm(messages=[{"role": "user", "content": content}], max_tokens=4000)
        raw = extract_llm_message_text(resp.choices[0].message)
        result = photo_grading_service.normalize_photo_grading_result(raw)
    except Exception as e:  # noqa: BLE001  视觉失败回退手动
        return {
            "error": f"拍题批改失败：{e}",
            "fallback_hint": "照片批改没成功，请把题目和你的答案打出来，我可以继续逐题批改。",
            "batch_id": batch_id,
        }

    batch.status = "parsed"
    db.commit()
    return {
        "batch_id": batch.id,
        "subject": result.subject,
        "questions": [q.model_dump() for q in result.questions],
        "summary": f"已批改 {len(result.questions)} 道题。请先核对，确认后我再把错题保存进错题本。",
    }


async def _handle_recognize_homework_photo_markdown(
    args: dict[str, Any], role: str, db: Session, teacher_id: int
) -> dict[str, Any]:
    """把拍题批改批次先识别成 Markdown，让用户确认后再批改。"""
    from app.features.exams import batch_service as exam_batch_service
    from app.features.exams.answer_review_parser import extract_answer_review_items
    from app.features.materials import markdown_extraction_service

    batch_id = args.get("batch_id")
    if not batch_id:
        return {"error": "缺少 batch_id"}
    batch = exam_batch_service.get_batch(db, int(batch_id))
    if not batch:
        return {"error": f"批次 {batch_id} 不存在"}
    if not _can_access_exam_batch(db, role, teacher_id, batch.student_id):
        return {"error": "无权访问该拍题批改批次"}

    try:
        exam_batch_service.synthesize_pdf(db, batch)
    except Exception:  # noqa: BLE001  留档失败不阻塞识别
        logger.warning("拍题批改合成 PDF 失败：batch_id=%s", batch_id, exc_info=True)

    photo_paths = _get_exam_batch_photo_paths(batch)
    if not photo_paths:
        return {
            "error": "该批次没有可识别的照片",
            "fallback_hint": "请重新上传清晰的题目照片，或直接把题目和你的答案发给我。",
            "batch_id": batch_id,
        }

    try:
        result = await markdown_extraction_service.recognize_images_to_markdown(
            photo_paths, mode="homework_photo"
        )
        review_items = extract_answer_review_items(result.markdown)
        review_state = exam_batch_service.build_answer_review_state(batch, result.markdown, review_items)
    except Exception as e:  # noqa: BLE001  视觉失败回退手动
        return {
            "error": f"图片识别失败：{e}",
            "fallback_hint": "照片识别没成功，请重新上传更清晰的图片，或把题目和你的答案打出来。",
            "batch_id": batch_id,
        }

    batch.status = "parsed"
    db.commit()
    return {
        "batch_id": batch.id,
        "recognized_markdown": result.markdown,
        "confidence": result.confidence,
        "uncertain_points": result.uncertain_points,
        "content_type": result.content_type,
        "recognition_provider": result.provider,
        "recognition_elapsed_ms": result.elapsed_ms,
        "recognition_warnings": result.warnings,
        "answer_review_state": review_state.model_dump(mode="json"),
        "summary": "已识别为 Markdown。请先核对题目和作答，确认后我再逐题批改。",
        "next_step": "如果识别无误，请回复“确认识别稿并批改”；如果有错，请直接指出第几题哪里识别错了。",
    }


async def _handle_save_graded_homework_errors(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """保存用户确认的拍题错题。"""
    from app.features.exams.schemas.photo_grading import PhotoGradingQuestion
    from app.features.exams import batch_service as exam_batch_service, photo_grading_service

    batch_id = args.get("batch_id")
    if not batch_id:
        return {"error": "缺少 batch_id"}
    batch = exam_batch_service.get_batch(db, int(batch_id))
    if not batch:
        return {"error": f"批次 {batch_id} 不存在"}
    if not _can_access_exam_batch(db, role, teacher_id, batch.student_id):
        return {"error": "无权保存该拍题批改错题"}

    raw_questions = args.get("questions") or []
    questions = [PhotoGradingQuestion(**q) for q in raw_questions]
    if not questions:
        return {"error": "没有要保存的错题", "batch_id": batch_id}
    return photo_grading_service.save_confirmed_homework_errors(db, batch, questions, subject=args.get("subject"))
