"""Agent 学习诊断/计划/笔记/反馈工具处理器。

拆自 app/core/agent_loop.py。query_diagnosis/learning_map 学情查询、recommend_resource/
search_paper_sources 资源推荐、record_feedback 反馈记录、create/query/archive_study_plan
学习计划、query_notes/feedback/recommendations 笔记反馈查询、save_note 笔记落库。
依赖方向：单向依赖 context（_resolve_tool_student_id/_is_wrong_reason_feedback）
+ features.p2/learning/question_bank（同层业务）。diagnosis/map/bili_search/note_service/
StudyPlanItemInput 在函数内按需 import。
"""
import asyncio
import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from app.models.user import User

from app.features.p2 import feedback, recommendation, study_plan
from app.features.question_bank import service as question_bank_service
from app.features.question_bank.schemas import SearchPaperSourcesRequest
from ..context import _is_wrong_reason_feedback, _resolve_tool_student_id


async def _handle_query_diagnosis(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查询学情诊断：复用 diagnosis_service.get_diagnosis。"""
    from app.features.learning.diagnosis_service import get_diagnosis

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    top_n = args.get("top_n", 10)
    try:
        result = get_diagnosis(db, sid, top_n)
    except ValueError as e:
        return {"error": str(e)}

    # 转成 agent 易读的摘要
    weak = [{"tag": w.tag, "wrong": w.wrong_count, "rate": f"{w.error_rate:.0%}", "mastered": w.mastered} for w in result.weak_points]
    mastered = result.mastered_tags
    return {
        "student": result.student_name,
        "weak_points": weak,
        "mastered_tags": mastered,
        "summary": f"薄弱 {len(weak)} 个知识点，已掌握 {len(mastered)} 个",
    }


async def _handle_query_learning_map(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查询学习地图：复用 learning_map_service 的聚合口径。"""
    from app.features.learning.map_service import build_learning_map, summarize_learning_map_for_agent

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    limit = max(1, min(int(args.get("limit") or 10), 30))
    result = build_learning_map(db, sid, limit=limit)
    nodes = [node.model_dump() if hasattr(node, "model_dump") else node.dict() for node in result.nodes]
    return {
        "student_id": result.student_id,
        "generated_at": result.generated_at,
        "summary": result.summary,
        "nodes": nodes,
        "agent_summary": summarize_learning_map_for_agent(result, limit=5),
    }



async def _handle_search_resource(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """兴趣模式资源搜索：复用底座 bili_search_service 真实搜 B站，不落库。

    search_hobby_resource 与学习空间的 recommend_resource 区别：
    - 兴趣场景（唱歌/乐器/口语等教程），纯推荐对话，不落 recommendation 表（无消费方）；
    - 搜索设施复用同一套（bili_search_service），不复制。
    """
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return {"error": "请提供搜索关键词 keyword"}
    try:
        # 底座：B站搜索+简介/弹幕预审（匿名，无需 Cookie）
        from app.features.question_bank.bili_search_service import search_and_enrich

        candidates = await search_and_enrich(keyword)
    except Exception as exc:  # noqa: BLE001 - 外部搜索失败必须结构化返回，不吞
        logger.warning("兴趣资源搜索失败 keyword=%s: %s", keyword, exc)
        return {"error": "资源搜索暂时不可用，请稍后再试或换个关键词"}
    if not candidates:
        return {"error": "没搜到合适的视频，换个关键词试试", "keyword": keyword}
    return {
        "keyword": keyword,
        "candidates": [
            {
                "title": c["title"],
                "url": c["url"],
                "author": c["author"],
                "play": c["play"],
                "desc": c.get("desc", ""),
                "danmaku_sample": c.get("danmaku_sample", [])[:5],
            }
            for c in candidates
        ],
        "summary": f"已搜到 {len(candidates)} 个候选，推荐 1-2 个并附完整链接",
    }


async def _handle_recommend_resource(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """推荐资源：用关键词搜 B站具体视频，自动落库播放量最高的一个，返回候选列表（问题8）。

    agent 只提供 keyword，后端调 bili_search_service 搜出 Top3 具体视频，
    落库播放量最高的那个，并把候选返回给 agent 供其在回复里展示。
    """
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    keyword = args.get("keyword", "")
    if not keyword:
        return {"error": "请提供搜索关键词 keyword"}
    boundary_error = recommendation.check_recommendation_allowed(db, sid, "bilibili", keyword)
    if boundary_error:
        return {
            "error": boundary_error,
            "keyword": keyword,
            "summary": "这次先不推荐新资源，可以改成讲解已有错题、复盘计划，或请家长调整推荐边界。",
        }

    # 搜 B站具体视频（按播放量降序）+ 补充简介/弹幕供预审（B站预审）
    from app.features.question_bank.bili_search_service import search_and_enrich

    candidates = await search_and_enrich(keyword)
    if not candidates:
        return {"error": "未搜到合适的 B站视频，请换个关键词或稍后再试", "keyword": keyword}

    # 落库播放量最高的一个（主推荐）
    top = candidates[0]
    reason = args.get("reason", f"针对「{keyword}」的权威讲解视频")
    rec = recommendation.save_recommendation(
        db,
        sid,
        top["title"],
        top["url"],
        reason=reason,
        platform="bilibili",
        related_interests=args.get("related_interests"),
    )
    return {
        "saved": True,
        "id": rec.id,
        "recommended": top,
        "candidates": [
            {
                "title": c["title"],
                "url": c["url"],
                "author": c["author"],
                "play": c["play"],
                "desc": c.get("desc", ""),
                "danmaku_sample": c.get("danmaku_sample", [])[:5],
            }
            for c in candidates
        ],
        "summary": f"已落库播放量最高的视频「{top['title']}」（{top['play']}播放），另返回 {len(candidates) - 1} 个候选",
    }


async def _handle_bilibili_course_assist(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """B站学习助手（闭环 POC）：仅学生可用，不落库。

    三种用法：url→合集目录/单集信息；url+read_content→单集内容感知（字幕优先，无则音频转写）；
    keyword→复用 search_and_enrich 返回 Top3 候选。结构化失败返回，不伪装成功。
    """
    if role != "student":
        raise PermissionError("只有学生能使用 B站学习助手")
    from app.features.question_bank.bilibili_assist_service import (
        fetch_course_directory,
        fetch_video_content,
        parse_bvid,
        parse_page_index,
    )

    url = (args.get("url") or "").strip()
    keyword = (args.get("keyword") or "").strip()
    if not url and not keyword:
        return {"error": "请提供 url 或 keyword 至少一个"}

    # keyword → 复用现有搜索（Top3 候选，含简介/弹幕采样）；15s 超时包装，避免拖慢对话轮
    if keyword:
        from app.features.question_bank.bili_search_service import search_and_enrich

        try:
            candidates = await asyncio.wait_for(search_and_enrich(keyword), timeout=15)
        except asyncio.TimeoutError:
            return {"error": "搜索超时，请稍后再试", "keyword": keyword}
        if not candidates:
            return {"error": "未搜到合适的 B站视频，请换个关键词或稍后再试", "keyword": keyword}
        return {
            "keyword": keyword,
            "candidates": candidates[:3],
            "summary": f"搜到 {len(candidates[:3])} 个候选视频（含简介/弹幕采样），请判断哪个匹配需求再给直链",
        }

    if not parse_bvid(url):
        return {"error": "invalid_url", "detail": "无法从输入解析出 BV 号"}
    directory = await fetch_course_directory(url)
    if not directory.get("ok"):
        return directory

    # url + read_content=true → 单集内容感知
    if args.get("read_content"):
        p_index = parse_page_index(url)
        content = await fetch_video_content(directory["bvid"], p_index=p_index)
        if not content.get("ok"):
            return {
                "error": content["error"],
                "bvid": directory["bvid"],
                "title": directory["title"],
                "episode_index": p_index,
            }
        episode_title = None
        episodes = directory.get("episodes") or []
        if 0 < p_index <= len(episodes):
            episode_title = episodes[p_index - 1]["title"]
        return {
            "bvid": directory["bvid"],
            "title": directory["title"],
            "episode_index": p_index,
            "episode_title": episode_title,
            "content": content,
            "summary": f"已读取第 {p_index} 集内容（来源：{content['source']}，{content['char_count']} 字）",
        }

    # url → 合集目录/单集信息
    return directory


async def _handle_search_paper_sources(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """搜索本地化试卷候选来源：仅家长可用。"""
    if role != "teacher":
        raise PermissionError("只有家长能采集试卷候选来源")
    try:
        req = SearchPaperSourcesRequest(**args)
    except Exception as e:  # noqa: BLE001
        return {"error": f"搜索参数不合法：{e}"}
    queries, papers = await question_bank_service.search_and_save_paper_sources(db, req, created_by=teacher_id)
    candidates = [question_bank_service.to_item(p).model_dump() for p in papers]
    return {
        "queries": queries,
        "saved_count": len(candidates),
        "candidates": candidates[:10],
        "summary": f"已保存 {len(candidates)} 个试卷候选来源；A/B 可优先人工确认，C 可作为内部候选/风格库，D 只保留搜索入口。",
    }


async def _handle_record_feedback(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """记录反馈：仅学生可用。"""
    if role != "student":
        raise PermissionError("只有学生能提交反馈")
    fb = feedback.submit_feedback(
        db,
        teacher_id,
        args["feedback_type"],
        args["content"],
        related_resource_id=args.get("related_resource_id"),
    )
    return {"id": fb.id, "saved": True}


async def _handle_create_study_plan(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """创建学习计划：两角色都可。student 只能给自己建，teacher 给绑定学生建。"""
    from app.features.p2.schemas import StudyPlanItemInput

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    raw_items = args.get("items") or []
    items = [StudyPlanItemInput(**item) for item in raw_items]
    planned_date = args.get("planned_date") or date.today().isoformat()
    try:
        if date.fromisoformat(planned_date) < date.today():
            planned_date = date.today().isoformat()
    except ValueError:
        planned_date = date.today().isoformat()
    try:
        student = db.get(User, sid)
        student_mode = getattr(student, "mode", "study") if student else "study"
        plan = study_plan.create_study_plan(
            db,
            sid,
            args.get("title") or "学习计划",
            items,
            focus=args.get("focus"),
            description=args.get("description"),
            context_refs=args.get("context_refs"),
            planned_date=planned_date,
            created_by=teacher_id,
            mode=student_mode,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    total_minutes = sum(item.minutes for item in plan.items)
    return {
        "id": plan.id,
        "title": plan.title,
        "focus": plan.focus,
        "planned_date": plan.planned_date,
        "item_count": len(plan.items),
        "total_minutes": total_minutes,
        "items": [item.model_dump() for item in plan.items],
        "saved": True,
        "summary": f"已创建学习计划「{plan.title}」，共 {len(plan.items)} 项，约 {total_minutes} 分钟",
    }


async def _handle_draft_study_plan(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """生成计划草案存 study_plan_draft，返回 draft_id 给前端展示确认卡。

    不直接建正式计划——学生必须在卡片上点'确认并创建'，后端原子校验+创建。
    """
    from app.features.agent import date_guard, study_plan_flow
    from app.features.p2.schemas import StudyPlanItemInput

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    student = db.get(User, sid)
    student_mode = getattr(student, "mode", "study") if student else "study"
    title = (args.get("title") or "").strip()
    if not title:
        return {"error": "学习计划名称不能为空"}
    try:
        items_input = [StudyPlanItemInput(**item) for item in (args.get("items") or [])]
    except Exception:
        return {"error": "任务格式不正确"}
    if not items_input:
        return {"error": "学习计划至少需要 1 个任务"}
    # 服务端日期硬边界：空/非法/过去回今天，未来保留；标题今日标签同步（M0）
    planned_date = date_guard.normalize_planned_date(args.get("planned_date"))
    title = date_guard.sync_today_label_in_title(title, planned_date)
    draft_data = {
        "title": title,
        "items": [item.model_dump() for item in items_input],
        "focus": args.get("focus"),
        "planned_date": planned_date,
        "description": args.get("description"),
        # M2 C：服务端生成的教材来源（context_refs.textbook_source）随草案保存，
        # 确认时原样传给正式计划；模型自填来源不可信，由守卫覆盖
        "context_refs": args.get("context_refs"),
    }
    draft = study_plan_flow.create_draft(db, sid, args.get("chat_session_id"), draft_data, teacher_id, mode=student_mode)
    total_minutes = sum(item.minutes for item in items_input)
    return {
        "draft_id": draft.id,
        "revision": draft.revision,
        # M1：会话归属/创建时间由服务端返回，前端不猜（created_at 标注 UTC）
        "chat_session_id": draft.chat_session_id,
        "created_at": draft.created_at.isoformat() + "Z" if draft.created_at else None,
        "expires_at": draft.expires_at.isoformat() if draft.expires_at else None,
        "title": title,
        "items": [item.model_dump() for item in items_input],
        "focus": args.get("focus"),
        "planned_date": planned_date,
        "item_count": len(items_input),
        "total_minutes": total_minutes,
        "drafted": True,
        "summary": f"已生成计划草案「{title}」，共 {len(items_input)} 项，约 {total_minutes} 分钟，等学生在卡片上确认并创建",
    }


async def _handle_update_study_plan(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """修改学习计划：两角色都可。归属校验 + 乐观锁 revision。"""
    plan_id = args.get("plan_id")
    if not plan_id:
        return {"error": "缺少 plan_id"}
    revision = args.get("revision")
    if revision is None:
        return {"error": "缺少 revision（计划版本号，查询计划时返回）"}
    try:
        plan_id_int = int(plan_id)
        revision_int = int(revision)
    except (TypeError, ValueError):
        return {"error": "plan_id 或 revision 不合法"}
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    from app.models.p2 import StudyPlan

    existing = db.get(StudyPlan, plan_id_int)
    if not existing:
        return {"error": "计划不存在"}
    if existing.student_id != sid:
        return {"error": "无权操作该计划"}
    try:
        plan = study_plan.update_study_plan(
            db,
            plan_id_int,
            title=args.get("title"),
            description=args.get("description"),
            planned_date=args.get("planned_date"),
            revision=revision_int,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    if not plan:
        return {"error": "计划不存在"}
    return {
        "id": plan.id,
        "title": plan.title,
        "description": plan.description,
        "revision": plan.revision,
        "updated": True,
        "summary": f"已修改学习计划「{plan.title}」",
    }


async def _handle_query_study_plans(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查询学习计划：两角色都可。

    M1（C2）：补充 as_of_date（服务端当前日期），逾期天数/提醒由服务端按该日期计算，
    模型不得根据聊天历史自行口算日期差。
    """
    from app.features.agent import date_guard

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    status = args.get("status", "active")
    topic = str(args.get("topic") or "").strip().lower()
    if role == "student" and status == "" and not topic:
        return {"error": "查询历史计划时必须提供 topic（当前科目或板块）"}
    st = db.get(User, sid)
    st_mode = getattr(st, "mode", "study") if st else "study"
    plans = study_plan.list_study_plans(db, sid, status=status, limit=10, mode=st_mode)
    if topic:
        plans = [
            plan
            for plan in plans
            if topic in " ".join(
                [
                    plan.title,
                    plan.focus or "",
                    plan.description or "",
                    *(item.title for item in plan.items),
                ]
            ).lower()
        ]
    overdue_count = sum(1 for plan in plans if plan.is_overdue)
    overdue_text = f"，其中 {overdue_count} 个已逾期" if overdue_count else ""
    reminders = [plan.reminder_message for plan in plans if plan.reminder_message]
    reminder_text = f"；提醒：{reminders[0]}" if reminders else ""
    return {
        "as_of_date": date_guard.local_today().isoformat(),
        "plans": [plan.model_dump() for plan in plans],
        "overdue_count": overdue_count,
        "reminders": reminders,
        "summary": f"找到 {len(plans)} 个{status or '全部'}学习计划{overdue_text}{reminder_text}",
    }


async def _handle_archive_study_plan(
    args: dict[str, Any], role: str, db: Session, teacher_id: int
) -> dict[str, Any]:
    """归档学习计划：保留历史，且只允许操作当前学生的计划。"""
    if not args.get("confirmed"):
        return {"error": "归档计划前需要用户明确确认"}
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    try:
        plan_id = int(args.get("plan_id") or 0)
    except (TypeError, ValueError):
        return {"error": "计划 id 不合法"}
    plan = study_plan.get_study_plan(db, plan_id)
    if not plan or plan.student_id != sid:
        return {"error": "无权归档该学习计划"}
    archived = study_plan.archive_study_plan(db, plan_id)
    if not archived:
        return {"error": "学习计划不存在"}
    return {
        "id": archived.id,
        "title": archived.title,
        "status": archived.status,
        "history_retained": True,
        "summary": f"已将学习计划「{archived.title}」移出当前计划，历史记录仍会保留",
    }



async def _handle_complete_task_item(
    args: dict[str, Any], role: str, db: Session, teacher_id: int
) -> dict[str, Any]:
    """评估并完成计划项（U-044）：委托共享 service 写完成判定 + 置 item status。

    passed -> done + completed_at；needs_retry -> 留 todo 重做；blocked -> in_progress。
    HTTP PATCH 与 Agent 工具共用 record_study_plan_item_assessment，不复制业务逻辑。
    """
    from app.features.p2.study_plan import record_study_plan_item_assessment

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    try:
        plan_item_id = int(args.get("plan_item_id") or 0)
    except (TypeError, ValueError):
        return {"error": "计划项 id 不合法"}
    assessment = args.get("assessment")
    if assessment not in ("passed", "needs_retry", "blocked"):
        return {"error": "assessment 必须是 passed/needs_retry/blocked"}
    try:
        item = record_study_plan_item_assessment(
            db,
            student_id=sid,
            item_id=plan_item_id,
            assessment=assessment,
            evidence_summary=args.get("evidence_summary"),
            reason=args.get("reason"),
            confidence=float(args["confidence"]) if args.get("confidence") is not None else None,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    except PermissionError as exc:
        return {"error": str(exc)}
    return {
        "plan_item_id": plan_item_id,
        "assessment": assessment,
        "item_status": item.status,
        "summary": f"已记录完成判定：{assessment}（{args.get('reason', '')}）",
    }


async def _handle_query_notes(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查笔记列表：了解弟弟之前记过什么。复用 note_service.list_notes。"""
    from app.features.note import service as note_service

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    subject = args.get("subject")
    st = db.get(User, sid)
    st_mode = getattr(st, "mode", "study") if st else "study"
    notes = note_service.list_notes(db, sid, subject=subject, status="confirmed", mode=st_mode)
    items = [
        {"id": n.id, "title": n.title, "subject": n.subject, "type": n.type, "tags": n.knowledge_tags, "preview": (n.content or "")[:80]}
        for n in notes[:20]
    ]
    return {
        "notes": items,
        "summary": f"共 {len(notes)} 条笔记" + (f"（学科 {subject}）" if subject else ""),
    }


async def _handle_query_feedback(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查学习反馈历史：了解弟弟最近学习动态。复用 feedback.list_feedback。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    feedback_items = feedback.list_feedback(db, sid)
    items = [{"type": f.feedback_type, "content": f.content, "time": f.created_at} for f in feedback_items[:20]]
    wrong_reasons = [item for item in items if _is_wrong_reason_feedback(item["content"], item["type"])]
    return {
        "feedback": items,
        "wrong_reasons": wrong_reasons,
        "summary": f"共 {len(feedback_items)} 条学习反馈，其中 {len(wrong_reasons)} 条错因反馈",
    }


async def _handle_query_recommendations(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """查历史推荐及点击情况：避免重复推荐、了解弟弟兴趣。复用 recommendation.list_recommendations。"""
    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    recs = recommendation.list_recommendations(db, sid)
    items = [{"title": r.title, "url": r.url, "clicked": r.clicked, "reason": r.reason} for r in recs[:20]]
    clicked = sum(1 for r in recs if r.clicked)
    return {
        "recommendations": items,
        "summary": f"共推过 {len(recs)} 个资源，点开 {clicked} 个",
    }


async def _handle_save_note(args: dict[str, Any], role: str, db: Session, teacher_id: int) -> dict[str, Any]:
    """保存笔记：AI 帮弟弟把学完的知识点整理成 Markdown 笔记并落库。

    自动化核心：agent 主动问弟弟要不要记笔记 → 整理好内容（含 category 分类）→ 调此工具落库。
    新建默认 draft 状态，弟弟在前端确认后改 confirmed。
    落库的是「待确认草稿」：请对弟弟说「我整理了一版笔记，你看看对不对」，不要说「已保存」；
    弟弟在对话里点「就这样存」确认后才转 confirmed，正式进 agent 记忆和每日记录。
    """
    from app.features.note import service as note_service

    sid = _resolve_tool_student_id(args, role, db, teacher_id)
    if not sid:
        return {"error": "缺少 student_id"}
    category = args.get("category") or "未分类"
    student = db.get(User, sid)
    student_mode = getattr(student, "mode", "study") if student else "study"
    item = note_service.create_note(
        db,
        {
            "student_id": sid,
            "title": args["title"],
            "subject": args.get("subject", "其他"),
            "category": category,
            "content": args.get("content", ""),
            "knowledge_tags": args.get("knowledge_tags", []),
            "source": args.get("source", "其他"),
            "source_ref": args.get("source_ref", []),
        },
        mode=student_mode,
    )
    return {
        "id": item.id,
        "title": item.title,
        "subject": item.subject,
        "category": item.category,
        "content": item.content,
        "knowledge_tags": item.knowledge_tags or [],
        "source": item.source,
        "status": item.status,  # draft（待确认）
        "saved": True,
        "note_draft": True,  # 前端据此渲染草案卡（预览+确认），而非普通工具结果
        "summary": (
            f"已落笔记草稿「{item.title}」（分类：{item.category}），status=draft 待确认。"
            f"注意：这是草稿不是正式笔记，确认前不进记忆。"
            f"请告诉弟弟『我整理了一版笔记，你看看对不对，可以就这样存或改一下』，不要说已保存。"
            f"查看：[查看笔记](#/notes/{item.id})"
        ),
    }
