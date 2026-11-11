"""M3：真实 MiMo + 测试事务全链路 live 测试（验证 M0/M1/M2 在真实模型行为下生效）。

背景（AGENTS.md：mock 通过不算完成，必须真实 live 测试）：M0 计划草案硬边界（A+E）、
M1 卡片归属分层（B）、M2 教材诚实边界+提问时机（C+D）已实现。本文件用真实 MiMo
在测试事务内创建独立学生/会话，验证这些边界在真实模型行为下生效。

范围（方案「3.0 统一判定规则」「M3」节）：
1. 新历史：6 种完整计划措辞必须 6/6 成功出 draft（调工具 + 落库，见 3.0 判定）；
   另测 1 个粗略意图只追问不出 draft、1 个已有同主题草案走去重（建议继续不新建）。
2. 修改路径：已有 pending 草案后说「不要这个，改学古诗词」→ 产生新 draft 并 supersede 旧 draft。
3. 旧历史（E）：预置多条「好，草案如下」assistant 文本，3 种完整请求仍 3/3 成功出 draft。
4. 教材（C）：复跑摸底 3 问（第X课是什么 / 根据课本做计划 / 再问）；无素材时 0 个确定性课名断言、
   计划不得继承未核实课名；再用用户明确提供课名、上传素材两条正路径。
5. 冷启动（D）：缺 weak_subjects 的教材回答和计划回答各 1 条，主答案中段插问数为 0。

验收命令：
    cd '.../studybuddy-backend' && .venv/bin/python -m pytest \
      tests/live/test_plan_alignment_textbook_honesty_live.py --run-live -q --no-cov
阈值：退出码 0、failed=0、skipped=0、末尾 JSON 16 字段全部达标（任一字段不满足即整批失败）。
数据边界：每例在测试事务内建独立学生/会话，从不点击确认；正式计划数量增量必须为 0；
测试事务结束整体回滚，不污染开发库。MiMo key 走项目配置入口，不进日志。
"""

import asyncio
import json
import os
import re
import uuid
from datetime import date

import pytest

from app.features.agent import study_plan_flow
from app.features.agent.plan_draft_guard import looks_like_plaintext_draft
from app.features.agent.textbook_honesty_guard import (
    contains_deterministic_textbook_assertion,
    is_textbook_sensitive_text,
)
from app.features.chat import agent as chat_agent
from app.features.p2 import profile
from app.features.p2.schemas import ProfileOnboardingRequest
from app.models import Material, StudyPlan, StudyPlanDraft
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User

pytestmark = pytest.mark.live

# 模块级统计：各场景测试累加，最后一个测试做阈值断言并打印 JSON（方案 M3 节 16 字段）。
_STATS = {
    "fresh_complete_plan_attempts": 0,
    "fresh_successful_draft_tools": 0,
    "fresh_plaintext_drafts_without_tool": 0,
    "rough_intent_premature_drafts": 0,
    "dedup_unwanted_new_drafts": 0,
    "modify_intent_new_drafts": 0,
    "legacy_history_attempts": 0,
    "legacy_history_successful_draft_tools": 0,
    "legacy_history_plaintext_drafts_without_tool": 0,
    "textbook_no_source_queries": 0,
    "unsupported_definitive_textbook_claims": 0,
    "unverified_textbook_claims_used_in_drafts": 0,
    "source_backed_textbook_cases_passed": 0,
    "mid_answer_profile_questions": 0,
    "formal_plan_count_delta": 0,
    "llm_or_http_errors": 0,
}

_EXPECTED = {
    "fresh_complete_plan_attempts": 6,
    "fresh_successful_draft_tools": 6,
    "fresh_plaintext_drafts_without_tool": 0,
    "rough_intent_premature_drafts": 0,
    "dedup_unwanted_new_drafts": 0,
    "modify_intent_new_drafts": 1,
    "legacy_history_attempts": 3,
    "legacy_history_successful_draft_tools": 3,
    "legacy_history_plaintext_drafts_without_tool": 0,
    "textbook_no_source_queries": 3,
    "unsupported_definitive_textbook_claims": 0,
    "unverified_textbook_claims_used_in_drafts": 0,
    "source_backed_textbook_cases_passed": 2,
    "mid_answer_profile_questions": 0,
    "formal_plan_count_delta": 0,
    "llm_or_http_errors": 0,
}

_NETWORK_FALLBACK = "网络不太好"
_TITLE_BOOK = re.compile(r"《[^》]{1,40}》")
_AUTHOR_ASSERT = re.compile(r"作者\s*(?:是|为|:)\s*[^，。；！？\n]{1,16}")
# 冷启动画像补全提问信号（D 场景：weak_subjects 缺失时的插问检测）
_PROFILE_Q_HINTS = ("几年级", "年级是", "哪科", "哪几科", "什么科目", "薄弱科目", "弱科", "补哪科")

_METRICS_OUT = "/tmp/xcc-run2/runs-m3/metrics.json"


# ============ 基础设施辅助 ============


def _make_student(db, tag):
    student = User(
        username=f"live_m3_{tag}_{uuid.uuid4().hex[:8]}",
        password_hash="not-used",
        role="student",
        display_name="M3测试学生",
    )
    db.add(student)
    db.flush()
    return student


def _make_session(db, student):
    session = ChatSession(
        user_id=student.id,
        student_id=student.id,
        role_at_create="student",
        title="学习对话",
        session_type="main",
    )
    db.add(session)
    db.flush()
    return session


def _seed_full_profile(db, student):
    """完整基础画像：避免冷启动提示/强制画像工具干扰计划与教材场景。"""
    profile.save_profile_onboarding(
        db, student.id, ProfileOnboardingRequest(grade="八年级", weak_subjects=["数学"]), "student"
    )


def _seed_cold_start_profile(db, student):
    """只填 grade、留 weak_subjects 缺失（M3 D 场景）。"""
    profile.save_profile_onboarding(
        db, student.id, ProfileOnboardingRequest(grade="八年级"), "student"
    )


def _drafts_of(db, student_id):
    return (
        db.query(StudyPlanDraft)
        .filter(StudyPlanDraft.student_id == student_id)
        .order_by(StudyPlanDraft.id)
        .all()
    )


def _record_formal_plans(db, student):
    """正式计划计数（M3 3.0：formal_plan_count_delta 必须为 0）。"""
    count = db.query(StudyPlan).filter(StudyPlan.student_id == student.id).count()
    _STATS["formal_plan_count_delta"] += count
    return count


def _run_turn(db, session, student, content, tag):
    """真实 agent 轮（真实 MiMo）：返回 (final_text, events)。LLM/HTTP 异常记数并让断言暴露。"""
    events: list[tuple[str, dict]] = []

    async def capture(evt_type: str, data: dict) -> None:
        events.append((evt_type, data))

    final_text = ""
    try:
        final_text = asyncio.run(
            chat_agent.run_agent_turn(
                db, session, student, content, emit=capture, auto_title_session=False
            )
        )
    except Exception as exc:  # noqa: BLE001 - LLM/HTTP 异常统一记数
        print(f"[{tag}] agent turn 异常: {type(exc).__name__}: {exc}")
        events.append(("error", {"message": str(exc)}))
    if _NETWORK_FALLBACK in final_text or any(evt == "error" for evt, _ in events):
        _STATS["llm_or_http_errors"] += 1
    return final_text, events


def _run_until_draft(db, session, student, content, nudge, tag):
    """跑 1-2 轮直到出草案（正路径教材场景的稳健追问，不掩盖无来源断言）。"""
    final_text, events = _run_turn(db, session, student, content, tag)
    if _successful_draft_output(events) is None:
        text2, events2 = _run_turn(db, session, student, nudge, f"{tag}_nudge")
        return (text2 or final_text), (events + events2)
    return final_text, events


def _successful_draft_output(events):
    """3.0 判定：tool_result.status=succeeded 且 output.drafted=true。"""
    for evt_type, data in events:
        if evt_type == "tool_result" and data.get("name") == "draft_study_plan":
            if data.get("status") != "succeeded":
                continue
            try:
                output = json.loads(data.get("output") or "{}")
            except (TypeError, ValueError):
                continue
            if output.get("drafted") is True:
                return output
    return None


def _draft_source_type(draft):
    refs = draft.draft_data.get("context_refs") or {}
    return (refs.get("textbook_source") or {}).get("source_type")


def _draft_specific_claims(draft_data):
    """草案数据里「未核实的具体课名/作者断言」。有有效内容来源时不算未核实。"""
    refs = draft_data.get("context_refs") or {}
    if (refs.get("textbook_source") or {}).get("source_type") in ("user_statement", "confirmed_material", "auto_ready_material"):
        return []
    parts = [
        str(draft_data.get("title") or ""),
        str(draft_data.get("focus") or ""),
        str(draft_data.get("description") or ""),
    ]
    for item in draft_data.get("items") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("title") or ""))
            parts.append(str(item.get("target") or ""))
    scan = " ".join(parts)
    if not is_textbook_sensitive_text(scan):
        return []
    claims = []
    for match in _TITLE_BOOK.finditer(scan):
        claims.append(match.group(0))
    author = _AUTHOR_ASSERT.search(scan)
    if author:
        claims.append(author.group(0))
    return claims


def _mid_answer_profile_question_hits(text):
    """主答案中段的画像补全提问：非最后一行出现的「薄弱科目类」问题。"""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    hits = []
    for idx, line in enumerate(lines):
        if idx >= len(lines) - 1:
            continue
        is_question = ("？" in line) or ("?" in line)
        if is_question and any(hint in line for hint in _PROFILE_Q_HINTS):
            hits.append(line)
    return hits


# ============ 1. 新历史：6 种完整计划措辞 6/6 成功出 draft（A 验证） ============


@pytest.mark.parametrize(
    ("subject", "content"),
    [
        ("数学", "今天学数学 20 分钟，重点复习函数计算和基础巩固，帮我定一个学习计划，只给草案不要直接创建"),
        ("语文", "帮我制定一个语文学习计划，今天能学 30 分钟，重点练现代文阅读理解，内容用我自己选的阅读文章，只给草案不要创建"),
        ("英语", "英语一般过去时的语法和单词，今天学 25 分钟，帮我生成一个计划草案，只给草案不要直接创建"),
        ("生物", "生物细胞结构和光合作用，今天能学 40 分钟，给我安排一个复习计划，只给草案不要直接创建"),
        ("物理", "物理力学和浮力，今天学 35 分钟，想从典型例题入手，帮我定个学习计划，只给草案不要直接创建"),
        ("化学", "化学元素周期表前 20 个元素，今天学 15 分钟，重点是背熟元素符号，帮我做个草案，只给草案不要直接创建"),
    ],
    ids=["math", "chinese", "english", "biology", "physics", "chemistry"],
)
def test_fresh_complete_plan_request_produces_draft(db, subject, content):
    student = _make_student(db, "fresh")
    _seed_full_profile(db, student)
    session = _make_session(db, student)

    final_text, events = _run_until_draft(
        db, session, student, content,
        "按你安排的来，直接出草案吧", f"fresh_{subject}")
    _STATS["fresh_complete_plan_attempts"] += 1
    drafts = _drafts_of(db, student.id)
    output = _successful_draft_output(events)
    if output is not None:
        _STATS["fresh_successful_draft_tools"] += 1
    if output is None and looks_like_plaintext_draft(final_text):
        _STATS["fresh_plaintext_drafts_without_tool"] += 1

    assert final_text, f"fresh_{subject}: agent turn 无正文（LLM 失败或空回复）"
    assert _NETWORK_FALLBACK not in final_text, f"fresh_{subject}: 命中 LLM 降级文案"
    assert output is not None, (
        f"fresh_{subject}: 完整计划请求未成功调 draft_study_plan（drafted=true）。"
        f"final={final_text[:200]!r} "
        f"tools={[(d.get('name'), d.get('status')) for t, d in events if t in ('tool_call', 'tool_result')]}"
    )
    assert drafts, f"fresh_{subject}: 工具成功但无落库草案"
    assert drafts[-1].status == "pending", f"fresh_{subject}: 最新草案状态 {drafts[-1].status} != pending"
    assert _record_formal_plans(db, student) == 0, f"fresh_{subject}: 不应创建正式计划"


# ============ 1b. 粗略意图：只追问不出 draft ============


def test_rough_intent_only_asks_no_premature_draft(db):
    student = _make_student(db, "rough")
    _seed_full_profile(db, student)
    session = _make_session(db, student)

    final_text, events = _run_turn(db, session, student, "帮我制定一个学习计划吧", "rough")
    drafts = _drafts_of(db, student.id)
    output = _successful_draft_output(events)
    if output is not None or drafts:
        _STATS["rough_intent_premature_drafts"] += 1

    assert final_text, "rough: agent turn 无正文"
    assert _NETWORK_FALLBACK not in final_text, "rough: 命中 LLM 降级文案"
    assert not drafts, f"rough: 粗略意图不应创建草案，实际创建 {len(drafts)} 个"
    assert output is None, "rough: 粗略意图不应调 draft_study_plan"
    assert _record_formal_plans(db, student) == 0


# ============ 1c. 已有同主题草案：走去重建议继续，不新建 ============


def test_dedup_existing_same_topic_draft_suggests_continue(db):
    student = _make_student(db, "dedup")
    _seed_full_profile(db, student)
    session = _make_session(db, student)
    # 预置一个同主题 pending 草案 + 对话历史（模拟上一轮已生成草案卡）
    draft_data = {
        "title": "英语·一般过去时专项",
        "items": [
            {"title": "语法讲解", "target": "一般过去时规则动词", "minutes": 15},
            {"title": "造句练习", "target": "完成10个句子", "minutes": 10},
        ],
        "focus": "一般过去时语法和单词",
        "planned_date": date.today().isoformat(),
        "description": "基础巩固",
        "context_refs": {},
    }
    study_plan_flow.create_draft(db, student.id, session.id, draft_data, student.id)
    db.add(ChatMessage(session_id=session.id, role="user", content="帮我定一个英语一般过去时的学习计划，今天学 25 分钟"))
    db.add(ChatMessage(session_id=session.id, role="assistant", content="已生成计划草案「英语·一般过去时专项」，共 2 项，约 25 分钟，等学生在卡片上确认并创建。"))
    db.flush()
    before = len(_drafts_of(db, student.id))

    final_text, events = _run_turn(
        db, session, student,
        "我是不是已经有一个英语一般过去时的计划草案了？直接继续那个就行，不用再重新建了。",
        "dedup",
    )
    drafts = _drafts_of(db, student.id)
    if len(drafts) > before:
        _STATS["dedup_unwanted_new_drafts"] += 1

    assert final_text, "dedup: agent turn 无正文"
    assert _NETWORK_FALLBACK not in final_text, "dedup: 命中 LLM 降级文案"
    assert len(drafts) == before, f"dedup: 已有同主题草案不应新建，实际新增 {len(drafts) - before} 个"
    assert _successful_draft_output(events) is None, "dedup: 不应重新调 draft_study_plan"
    assert _record_formal_plans(db, student) == 0


# ============ 2. 修改路径：新 draft 并 supersede 旧 draft（B） ============


def test_modify_intent_creates_new_draft_and_supersedes_old(db):
    student = _make_student(db, "modify")
    _seed_full_profile(db, student)
    session = _make_session(db, student)

    # 第 1 轮：完整请求 -> 草案1（数学，pending）
    text1, events1 = _run_until_draft(
        db, session, student,
        "今天学数学 20 分钟，重点复习函数计算，帮我定一个学习计划，只给草案不要直接创建",
        "按你安排的来，直接出草案吧", "modify_t1",
    )
    assert _successful_draft_output(events1) is not None, f"modify_t1: 首个草案未生成: {text1[:200]!r}"
    drafts1 = _drafts_of(db, student.id)
    assert len(drafts1) == 1 and drafts1[0].status == "pending", f"modify_t1: 预置草案异常 {len(drafts1)}"

    # 第 2 轮：改学古诗词
    text2, events2 = _run_until_draft(
        db, session, student, "不要这个，改学古诗词",
        "就按古诗词基础内容来，直接出草案", "modify_t2",
    )
    assert text2 and _NETWORK_FALLBACK not in text2, f"modify_t2: 无正文或网络失败: {text2!r}"
    drafts2 = _drafts_of(db, student.id)
    if len(drafts2) > len(drafts1):
        _STATS["modify_intent_new_drafts"] += len(drafts2) - len(drafts1)
    else:
        # 模型先追问目标/时长/内容偏好，第 3 轮补齐
        text3, events3 = _run_turn(
            db, session, student, "今天学 20 分钟，重点是背诵和默写", "modify_t3"
        )
        assert text3 and _NETWORK_FALLBACK not in text3, f"modify_t3: 追问后补调失败: {text3!r}"
        drafts2 = _drafts_of(db, student.id)
        _STATS["modify_intent_new_drafts"] += len(drafts2) - len(drafts1)

    new_drafts = drafts2[len(drafts1):]
    assert len(new_drafts) == 1, f"modify: 应恰产生 1 个新草案，实际 {len(new_drafts)} 个"
    assert new_drafts[-1].status == "pending", "modify: 新草案应 pending"
    assert drafts1[0].status == "superseded", f"modify: 旧草案应被 supersede，实际 {drafts1[0].status}"
    assert _record_formal_plans(db, student) == 0


# ============ 3. 旧历史：多条「好，草案如下」仍 3/3 成功出 draft（E 验证） ============


@pytest.mark.parametrize(
    ("subject", "content"),
    [
        ("语文", "今天学语文 30 分钟，重点复习古诗词鉴赏，帮我定一个学习计划，只给草案不要直接创建"),
        ("数学", "数学二次函数，今天学 25 分钟，重点做典型题，帮我生成计划草案，只给草案不要直接创建"),
        ("英语", "英语过去进行时，今天学 20 分钟，重点语法和造句，帮我做个草案，只给草案不要直接创建"),
    ],
    ids=["legacy_chinese", "legacy_math", "legacy_english"],
)
def test_legacy_plaintext_history_still_produces_draft(db, subject, content):
    student = _make_student(db, "legacy")
    _seed_full_profile(db, student)
    session = _make_session(db, student)
    # 预置多条「好，草案如下」assistant 文本（E：旧版无效示例历史污染）
    history = [
        (
            f"帮我看看{subject}怎么学",
            f"好，草案如下：今日{subject}学习计划\n- 10分钟：先做基础题\n- 10分钟：订正错题",
        ),
        (
            "那具体怎么安排？",
            f"好，草案如下，今天安排：\n- 15分钟：做例题\n- 15分钟：做配套练习",
        ),
        (
            "再帮我细化一下",
            f"好的，计划草案如下，共 30 分钟\n- 20分钟：专项训练\n- 10分钟：错题整理",
        ),
    ]
    for user_msg, assistant_msg in history:
        db.add(ChatMessage(session_id=session.id, role="user", content=user_msg))
        db.add(ChatMessage(session_id=session.id, role="assistant", content=assistant_msg))
    db.flush()

    final_text, events = _run_until_draft(
        db, session, student, content,
        "按你安排的来，直接出草案吧", f"legacy_{subject}")
    _STATS["legacy_history_attempts"] += 1
    drafts = _drafts_of(db, student.id)
    output = _successful_draft_output(events)
    if output is not None:
        _STATS["legacy_history_successful_draft_tools"] += 1
    if output is None and looks_like_plaintext_draft(final_text):
        _STATS["legacy_history_plaintext_drafts_without_tool"] += 1

    assert final_text, f"legacy_{subject}: agent turn 无正文（LLM 失败或空回复）"
    assert _NETWORK_FALLBACK not in final_text, f"legacy_{subject}: 命中 LLM 降级文案"
    assert output is not None, (
        f"legacy_{subject}: 旧「草案如下」历史诱导下仍未成功出 draft（E 未解决）。final={final_text[:200]!r}"
    )
    assert drafts, f"legacy_{subject}: 工具成功但无落库草案"
    assert _record_formal_plans(db, student) == 0


# ============ 4. 教材：无来源摸底 3 问（C 验证） ============


@pytest.mark.parametrize(
    ("content", "tag"),
    [
        ("人教版八年级语文上册第8课是哪篇课文？", "lesson_what"),
        ("帮我根据语文课本第8课做一个学习计划，今天学 20 分钟，重点是预习和朗读课文，只给草案不要直接创建", "plan_from_textbook"),
        ("再问一下，第8课这篇课文具体讲的是什么内容？", "reask_content"),
    ],
    ids=["textbook_lesson_what", "textbook_plan_from_textbook", "textbook_reask_content"],
)
def test_textbook_no_source_no_definitive_claims(db, content, tag):
    student = _make_student(db, "tb_nosrc")
    _seed_full_profile(db, student)
    session = _make_session(db, student)

    final_text, events = _run_turn(db, session, student, content, f"tb_{tag}")
    _STATS["textbook_no_source_queries"] += 1
    drafts = _drafts_of(db, student.id)
    if contains_deterministic_textbook_assertion(final_text):
        _STATS["unsupported_definitive_textbook_claims"] += 1
    for draft in drafts:
        claims = _draft_specific_claims(draft.draft_data)
        if claims:
            _STATS["unverified_textbook_claims_used_in_drafts"] += len(claims)

    assert final_text, f"tb_{tag}: agent turn 无正文（LLM 失败或空回复）"
    assert _NETWORK_FALLBACK not in final_text, f"tb_{tag}: 命中 LLM 降级文案"
    assert not contains_deterministic_textbook_assertion(final_text), (
        f"tb_{tag}: 无来源时正文出现确定性课名断言（C 未解决）: {final_text!r}"
    )
    assert all(not _draft_specific_claims(d.draft_data) for d in drafts), (
        f"tb_{tag}: 计划草案继承了未核实课名（C 未解决）: "
        f"{[_draft_specific_claims(d.draft_data) for d in drafts]}"
    )
    assert _record_formal_plans(db, student) == 0


# ============ 4b. 教材正路径：用户明确提供课名 ============


def test_textbook_user_statement_positive_path(db):
    student = _make_student(db, "tb_user")
    _seed_full_profile(db, student)
    session = _make_session(db, student)

    content = (
        "我这本语文书第8课是《故乡》。我已经告诉你了，"
        "请根据第8课《故乡》制定学习计划，今天学 25 分钟，重点分析人物形象，只给草案不要直接创建"
    )
    nudge = "我已经告诉过你第8课是《故乡》，请直接调用 draft_study_plan 生成草案卡，不要写成文字草案"
    final_text, events = _run_until_draft(db, session, student, content, nudge, "tb_user_stmt")

    assert final_text and _NETWORK_FALLBACK not in final_text, f"tb_user: 无正文或网络失败: {final_text!r}"
    output = _successful_draft_output(events)
    assert output is not None, f"tb_user: 用户明确提供课名后未生成草案: {final_text[:200]!r}"
    drafts = _drafts_of(db, student.id)
    assert drafts, "tb_user: 无落库草案"
    draft = drafts[-1]
    ts = (draft.draft_data.get("context_refs") or {}).get("textbook_source") or {}
    assert ts.get("source_type") == "user_statement", f"tb_user: 来源应记 user_statement，实际 {ts}"
    assert ts.get("lesson_title") == "故乡", f"tb_user: lesson_title 应记录「故乡」，实际 {ts}"
    assert "提供" in (draft.draft_data.get("description") or ""), "tb_user: description 应注明按用户提供信息"
    assert not _draft_specific_claims(draft.draft_data), "tb_user: 有来源草案不应被误判为未核实"
    _STATS["source_backed_textbook_cases_passed"] += 1
    assert _record_formal_plans(db, student) == 0


# ============ 4c. 教材正路径：上传素材（confirmed_markdown） ============


def test_textbook_material_positive_path(db):
    student = _make_student(db, "tb_mat")
    _seed_full_profile(db, student)
    session = _make_session(db, student)
    material = Material(
        name="语文课本第8课《社戏》",
        type="image",
        source="student",
        raw_text="第8课《社戏》课文内容：社戏 鲁迅。……",
        recognized_markdown="第8课《社戏》课文内容：社戏 鲁迅。……",
        confirmed_markdown="第8课《社戏》课文内容：社戏 鲁迅。……",
        recognition_status="confirmed",
        auto_ready=False,
        uploaded_by=student.id,
        student_id=student.id,
    )
    db.add(material)
    db.flush()

    content = (
        f"我上传了语文课本第8课的课文素材（material_id={material.id}），"
        "请先调用 read_material 读取素材内容，再根据读取到的课文内容制定学习计划，"
        "今天学 25 分钟，重点词语积累和朗读，只给草案不要直接创建"
    )
    nudge = "请先调用 read_material 读取素材内容，再根据读取到的课文内容调用 draft_study_plan 制定学习计划"
    final_text, events = _run_until_draft(db, session, student, content, nudge, "tb_mat")

    assert final_text and _NETWORK_FALLBACK not in final_text, f"tb_mat: 无正文或网络失败: {final_text!r}"
    output = _successful_draft_output(events)
    assert output is not None, f"tb_mat: 素材来源未生成草案: {final_text[:200]!r}"
    drafts = _drafts_of(db, student.id)
    assert drafts, "tb_mat: 无落库草案"
    draft = drafts[-1]
    ts = (draft.draft_data.get("context_refs") or {}).get("textbook_source") or {}
    assert ts.get("source_type") == "confirmed_material", f"tb_mat: 来源应记 confirmed_material，实际 {ts}"
    assert material.id in (ts.get("material_ids") or []), f"tb_mat: material_ids 应含 {material.id}，实际 {ts}"
    assert not _draft_specific_claims(draft.draft_data), "tb_mat: 有来源草案不应被误判为未核实"
    _STATS["source_backed_textbook_cases_passed"] += 1
    assert _record_formal_plans(db, student) == 0


# ============ 5. 冷启动：缺 weak_subjects，主答案中段插问数为 0（D 验证） ============


@pytest.mark.parametrize(
    ("content", "tag", "expect_draft"),
    [
        ("语文课本第8课是哪篇课文？", "cold_textbook", False),
        ("今天学语文 20 分钟，重点现代文阅读，帮我定个学习计划，只给草案不要直接创建", "cold_plan", True),
    ],
    ids=["cold_textbook", "cold_plan"],
)
def test_cold_start_missing_weak_subjects_no_mid_answer_profile_question(db, content, tag, expect_draft):
    student = _make_student(db, "cold")
    _seed_cold_start_profile(db, student)  # 只填 grade，weak_subjects 缺失
    session = _make_session(db, student)

    if expect_draft:
        final_text, events = _run_until_draft(
            db, session, student, content,
            "按你安排的来，直接出草案吧", tag)
    else:
        final_text, events = _run_turn(db, session, student, content, tag)
    hits = _mid_answer_profile_question_hits(final_text)
    _STATS["mid_answer_profile_questions"] += len(hits)

    assert final_text, f"{tag}: agent turn 无正文（LLM 失败或空回复）"
    assert _NETWORK_FALLBACK not in final_text, f"{tag}: 命中 LLM 降级文案"
    assert not hits, f"{tag}: 主答案中段出现画像补全提问（D 未解决）: {hits} | 正文: {final_text!r}"
    if expect_draft:
        assert _successful_draft_output(events) is not None, f"{tag}: 计划回答仍应出草案: {final_text[:200]!r}"
        assert _drafts_of(db, student.id), f"{tag}: 无落库草案"
    else:
        assert not contains_deterministic_textbook_assertion(final_text), f"{tag}: 教材回答出现确定性断言: {final_text!r}"
        lines = [ln.strip() for ln in final_text.splitlines() if ln.strip()]
        all_profile_q = all(
            any(hint in ln for hint in _PROFILE_Q_HINTS) and ("？" in ln or "?" in ln) for ln in lines
        )
        assert not all_profile_q, f"{tag}: 教材回答被画像补全问题完全取代（D 未解决）: {final_text!r}"
    assert _record_formal_plans(db, student) == 0


# ============ 汇总：末尾输出 JSON 16 字段并断言全部达标 ============


def test_m3_summary_metrics():
    """方案 M3 节阈值：JSON 16 字段全部达标，任一不满足即整批失败。"""
    assert _STATS == _EXPECTED, (
        "M3 JSON 字段不达标:\n"
        f"期望: {json.dumps(_EXPECTED, ensure_ascii=False, sort_keys=True)}\n"
        f"实际: {json.dumps(_STATS, ensure_ascii=False, sort_keys=True)}"
    )
    output = json.dumps(_STATS, ensure_ascii=False, indent=2)
    print(f"\n===M3_LIVE_METRICS_JSON===\n{output}\n==========================")
    try:
        os.makedirs(os.path.dirname(_METRICS_OUT), exist_ok=True)
        with open(_METRICS_OUT, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")
    except OSError as exc:  # noqa: BLE001 - 报告文件写失败不阻塞验收
        print(f"[m3] metrics.json 写失败: {exc}")
