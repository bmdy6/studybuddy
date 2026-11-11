# 错题优先上下文 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 在讲题、制定计划、复盘、推荐练习前，自动读取并引用学生近期错题、错因、错题复盘笔记和高频知识点。

**Architecture:** 在后端 Agent loop 中新增独立的学习记忆上下文 builder，复用现有 `diagnosis_service.get_error_book`、`note_service.get_blind_spots`、`note_service.list_notes`。主循环在现有学生画像上下文之后追加 `[学习记忆]`，并用轻量触发器控制何时注入。

**Tech Stack:** Python 3、FastAPI 后端、SQLAlchemy ORM、pytest；不新增前端页面、不新增数据库表、不引入 mem0/向量库/图数据库。

## Global Constraints

- 先复用现有 MySQL 数据和 service，不引入 mem0、向量库、图数据库或新 UI。
- 学习计划仍保持“先商量再创建”：错题上下文只能用于生成草案和追问，不能绕过学生确认。
- 学生只能读取自己的学习记忆；家长只能读取已绑定学生的数据。
- 数据缺失时不能编造历史，要明确数据少并引导记录错题、错因或每日回顾。
- Builder 读取失败只记录 warning，不阻塞对话。
- 高频知识点最多 5 个，代表性错题最多 5 道，错题复盘笔记最多 3 篇。
- 单个题干、答案、笔记摘要限制 80-120 字；整段上下文目标控制在 1200 中文字以内。
- 关键词与格式逻辑集中在 helper 中，不能散落硬编码。

---

## File Structure

- Modify: `studybuddy-backend/app/core/agent_loop.py`
  - 新增 `_should_include_learning_memory(latest_user_text: str) -> bool`
  - 新增 `_shorten_learning_memory_text(value: Any, limit: int = 100) -> str`
  - 新增 `_summarize_error_book_groups(groups: list[Any], limit: int = 5) -> list[str]`
  - 新增 `_summarize_error_review_notes(notes: list[Any], limit: int = 3) -> list[str]`
  - 新增 `_build_learning_memory_context(db: Session, student_id: int, latest_user_text: str) -> str`
  - 在 `agent_loop(...)` 拼 system context 的地方追加学习记忆上下文
- Modify: `studybuddy-backend/tests/unit/test_agent_loop.py`
  - 增加学习记忆触发、摘要、异常兜底、主循环注入、计划确认保护测试
- Modify: `docs/已实现能力清单.md`
  - 实现后补“Agent 错题优先上下文”
- Modify: `docs/未实现需求清单.md`
  - U-002 从 P1 移除或标记已完成，保留后续掌握状态等未实现项
- Modify: `studybuddy-client/src/data/releaseNotes.ts`
  - 增加帮助与更新记录
- Modify: `docs/真人验收指南.md`
  - 增加“错题优先上下文”真人验收步骤

---

### Task 1: 学习记忆触发器与文本截断

**Files:**
- Modify: `studybuddy-backend/app/core/agent_loop.py`
- Test: `studybuddy-backend/tests/unit/test_agent_loop.py`

**Interfaces:**
- Produces: `_should_include_learning_memory(latest_user_text: str) -> bool`
- Produces: `_shorten_learning_memory_text(value: Any, limit: int = 100) -> str`
- Consumes: no new internal interface

- [ ] **Step 1: Write failing tests**

Append this class near existing context tests in `studybuddy-backend/tests/unit/test_agent_loop.py`:

```python
class TestLearningMemoryContext:
    """错题优先学习记忆上下文。"""

    @pytest.mark.parametrize(
        "text",
        [
            "今天英语怎么学",
            "下午想练两道类似题",
            "帮我复盘最近错题",
            "我哪里反复错了",
            "给我制定一个数学计划",
            "最近需要督促什么",
        ],
    )
    def test_learning_memory_trigger_for_study_intents(self, text):
        assert agent_loop._should_include_learning_memory(text)

    @pytest.mark.parametrize(
        "text",
        [
            "怎么登录",
            "帮助页面在哪里",
            "你好",
            "切换账号失败了",
        ],
    )
    def test_learning_memory_skips_non_study_intents(self, text):
        assert not agent_loop._should_include_learning_memory(text)

    def test_shorten_learning_memory_text_strips_space_and_limits_length(self):
        text = "  第一行\n\n第二行很长" + "好" * 120

        shortened = agent_loop._shorten_learning_memory_text(text, limit=20)

        assert "\n" not in shortened
        assert len(shortened) <= 21
        assert shortened.endswith("…")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext -q
```

Expected: FAIL because `_should_include_learning_memory` and `_shorten_learning_memory_text` do not exist.

- [ ] **Step 3: Implement helpers**

Add near `_build_profile_context` in `studybuddy-backend/app/core/agent_loop.py`:

```python
_LEARNING_MEMORY_TRIGGER_KEYWORDS = (
    "错题",
    "错因",
    "哪里错",
    "反复错",
    "薄弱",
    "不会",
    "讲题",
    "批改",
    "复盘",
    "总结",
    "计划",
    "怎么学",
    "今天学",
    "下午学",
    "周末学",
    "练习",
    "练两道",
    "同类题",
    "推荐练",
    "督促",
)

_LEARNING_MEMORY_SKIP_KEYWORDS = (
    "登录",
    "账号",
    "切换账号",
    "帮助页面",
    "帮助与更新",
    "打不开",
    "报错",
)


def _should_include_learning_memory(latest_user_text: str) -> bool:
    text = (latest_user_text or "").strip()
    if not text:
        return False
    if any(keyword in text for keyword in _LEARNING_MEMORY_SKIP_KEYWORDS):
        return False
    return any(keyword in text for keyword in _LEARNING_MEMORY_TRIGGER_KEYWORDS)


def _shorten_learning_memory_text(value: Any, limit: int = 100) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add studybuddy-backend/app/core/agent_loop.py studybuddy-backend/tests/unit/test_agent_loop.py
git commit -m "增加学习记忆触发判断"
```

---

### Task 2: 学习记忆上下文 Builder

**Files:**
- Modify: `studybuddy-backend/app/core/agent_loop.py`
- Test: `studybuddy-backend/tests/unit/test_agent_loop.py`

**Interfaces:**
- Consumes: `_should_include_learning_memory(latest_user_text: str) -> bool`
- Consumes: `_shorten_learning_memory_text(value: Any, limit: int = 100) -> str`
- Produces: `_summarize_error_book_groups(groups: list[Any], limit: int = 5) -> list[str]`
- Produces: `_summarize_error_review_notes(notes: list[Any], limit: int = 3) -> list[str]`
- Produces: `_build_learning_memory_context(db: Session, student_id: int, latest_user_text: str) -> str`

- [ ] **Step 1: Write failing tests**

Add imports at the top of `studybuddy-backend/tests/unit/test_agent_loop.py` if missing. The file already imports `date` and `timedelta`; extend that import instead of adding a duplicate datetime import.

```python
from datetime import date, datetime, timedelta

from app.models.error_book import ErrorBook
from app.models.record import ExamRecord
```

Append these tests to `TestLearningMemoryContext`:

```python
    def _create_wrong_question(self, db, tag: str = "一般过去时", error_count: int = 3) -> None:
        exam = Exam(title="学习记忆测试卷", subject="english", created_by=1)
        db.add(exam)
        db.commit()
        db.refresh(exam)

        question = Question(
            exam_id=exam.id,
            type="single_choice",
            stem="He ___ to school yesterday.",
            options=["go", "goes", "went", "gone"],
            answer_json=["went"],
            score=5,
            knowledge_tags=[tag],
        )
        db.add(question)
        db.commit()
        db.refresh(question)

        record = ExamRecord(exam_id=exam.id, student_id=2, total_score=0, status="graded")
        db.add(record)
        db.commit()
        db.refresh(record)

        db.add(
            ErrorBook(
                student_id=2,
                question_id=question.id,
                exam_record_id=record.id,
                knowledge_tags=[tag],
                error_count=error_count,
                last_wrong_at=datetime(2026, 7, 5, 18, 30, 0),
            )
        )
        db.commit()

    def test_learning_memory_context_includes_blind_spots_errors_and_review_notes(self, db):
        self._create_wrong_question(db)
        note_service.create_note(
            db,
            {
                "student_id": 2,
                "title": "一般过去时复盘",
                "subject": "英语",
                "category": "错题复盘",
                "content": "下次先找 yesterday 这种时间标志词，再判断动词过去式。",
                "knowledge_tags": ["一般过去时"],
                "source": "错题讲解",
                "source_ref": [1],
                "status": "confirmed",
            },
        )

        context = agent_loop._build_learning_memory_context(db, 2, "今天英语怎么学")

        assert "[学习记忆]" in context
        assert "近期高频错题" in context
        assert "一般过去时" in context
        assert "错 3 次" in context
        assert "代表性错题" in context
        assert "He ___ to school yesterday." in context
        assert "错题复盘笔记" in context
        assert "一般过去时复盘" in context
        assert "不要编造" in context

    def test_learning_memory_context_returns_empty_for_non_study_intent(self, db):
        self._create_wrong_question(db)

        context = agent_loop._build_learning_memory_context(db, 2, "怎么登录")

        assert context == ""

    def test_learning_memory_context_handles_service_errors(self, db):
        with patch("app.services.note_service.get_blind_spots", side_effect=RuntimeError("boom")):
            context = agent_loop._build_learning_memory_context(db, 2, "今天英语怎么学")

        assert context == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext -q
```

Expected: FAIL because builder functions do not exist.

- [ ] **Step 3: Implement summaries and builder**

Add below Task 1 helpers in `studybuddy-backend/app/core/agent_loop.py`:

```python
def _summarize_error_book_groups(groups: list[Any], limit: int = 5) -> list[str]:
    items: list[dict[str, Any]] = []
    for group in groups or []:
        tag = getattr(group, "tag", "") or ""
        for question in getattr(group, "questions", []) or []:
            items.append(
                {
                    "tag": tag,
                    "error_id": getattr(question, "error_id", ""),
                    "stem": getattr(question, "stem", ""),
                    "student_answer": getattr(question, "student_answer", ""),
                    "correct_answer": getattr(question, "correct_answer", ""),
                    "error_count": int(getattr(question, "error_count", 0) or 0),
                }
            )
    items.sort(key=lambda item: item["error_count"], reverse=True)
    lines: list[str] = []
    for item in items[:limit]:
        parts = [
            f"error_id={item['error_id']}",
            f"知识点={item['tag'] or '未标注'}",
            f"题干={_shorten_learning_memory_text(item['stem'], 100)}",
        ]
        if item["student_answer"]:
            parts.append(f"学生答案={_shorten_learning_memory_text(item['student_answer'], 60)}")
        if item["correct_answer"]:
            parts.append(f"正确答案={_shorten_learning_memory_text(item['correct_answer'], 60)}")
        parts.append(f"错过 {item['error_count']} 次")
        lines.append("，".join(parts))
    return lines


def _summarize_error_review_notes(notes: list[Any], limit: int = 3) -> list[str]:
    review_notes = [
        note
        for note in notes or []
        if getattr(note, "category", None) == "错题复盘" or getattr(note, "source", None) == "错题讲解"
    ]
    lines: list[str] = []
    for note in review_notes[:limit]:
        title = _shorten_learning_memory_text(getattr(note, "title", ""), 40)
        content = _shorten_learning_memory_text(getattr(note, "content", ""), 120)
        if title or content:
            lines.append(f"《{title or '未命名复盘'}》：{content}")
    return lines


def _build_learning_memory_context(db: Session, student_id: int, latest_user_text: str) -> str:
    if not _should_include_learning_memory(latest_user_text):
        return ""
    try:
        from app.services import diagnosis_service, note_service

        parts: list[str] = []
        blind_spots = note_service.get_blind_spots(db, student_id, min_errors=2)[:5]
        if blind_spots:
            blind_bits = [
                f"{item.tag}错 {item.error_count} 次，最近 {item.last_wrong_at or '未知日期'}，已有 {item.note_count} 篇笔记"
                for item in blind_spots
            ]
            parts.append("近期高频错题：" + "；".join(blind_bits))

        error_lines = _summarize_error_book_groups(diagnosis_service.get_error_book(db, student_id), limit=5)
        if error_lines:
            parts.append("代表性错题：" + "；".join(f"{index + 1}. {line}" for index, line in enumerate(error_lines)))

        note_lines = _summarize_error_review_notes(note_service.list_notes(db, student_id), limit=3)
        if note_lines:
            parts.append("错题复盘笔记：" + "；".join(f"{index + 1}. {line}" for index, line in enumerate(note_lines)))

        if not parts:
            return "\n[学习记忆] 目前错题和复盘笔记数据较少。不要编造历史；可以引导学生上传错题、记录错因或写每日回顾。"

        parts.append("使用要求：计划、讲题、推荐练习前先参考这些数据；引用时说清依据；没有数据时不要编造；创建学习计划前仍必须先和学生确认。")
        context = "\n[学习记忆] " + "；".join(parts) + "。"
        if len(context) > 1200:
            context = context[:1199].rstrip() + "…"
        return context
    except Exception:  # noqa: BLE001
        logger.warning("读取学习记忆失败：student_id=%s", student_id, exc_info=True)
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add studybuddy-backend/app/core/agent_loop.py studybuddy-backend/tests/unit/test_agent_loop.py
git commit -m "生成错题优先学习记忆上下文"
```

---

### Task 3: 接入 Agent 主循环并保护计划确认

**Files:**
- Modify: `studybuddy-backend/app/core/agent_loop.py`
- Test: `studybuddy-backend/tests/unit/test_agent_loop.py`

**Interfaces:**
- Consumes: `_build_learning_memory_context(db: Session, student_id: int, latest_user_text: str) -> str`
- Produces: Agent `system` prompt includes `[学习记忆]` for relevant student/teacher conversations

- [ ] **Step 1: Find current system context construction**

Run:

```bash
cd studybuddy-backend
rg -n "profile_context|_build_profile_context|system =" app/core/agent_loop.py
```

Expected: locate the block where `profile_sid` is resolved and `_build_profile_context` is appended to `system`.

- [ ] **Step 2: Write failing tests**

Append to `TestLearningMemoryContext`:

```python
    def test_agent_loop_injects_learning_memory_into_llm_system(self, db):
        self._create_wrong_question(db)
        captured_system = ""

        async def fake_stream(*args, **kwargs):
            nonlocal captured_system
            captured_system = kwargs.get("system") or args[2]
            return _mock_text_stream("我会先参考你最近的一般过去时错题。")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "今天英语怎么学"}],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        assert "[学习记忆]" in captured_system
        assert "一般过去时" in captured_system
        assert "创建学习计划前仍必须先和学生确认" in captured_system
        assert result[-1]["content"] == "我会先参考你最近的一般过去时错题。"

    def test_agent_loop_does_not_inject_learning_memory_for_help_question(self, db):
        self._create_wrong_question(db)
        captured_system = ""

        async def fake_stream(*args, **kwargs):
            nonlocal captured_system
            captured_system = kwargs.get("system") or args[2]
            return _mock_text_stream("帮助页面在右上角。")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=fake_stream):
            asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "帮助页面在哪里"}],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        assert "[学习记忆]" not in captured_system

    def test_learning_memory_does_not_bypass_study_plan_confirmation(self, db):
        self._create_wrong_question(db)
        tool_stream = _mock_tool_stream(
            "create_study_plan",
            {
                "student_id": 2,
                "title": "英语错题补漏",
                "planned_date": "2026-07-06",
                "confirmed": True,
                "items": [{"title": "复盘一般过去时错题", "minutes": 20}],
            },
        )
        text_stream = _mock_text_stream("先确认一下：你今天有多少时间复盘一般过去时？")

        with patch.object(ai_service, "call_llm_stream", new_callable=AsyncMock, side_effect=[tool_stream, text_stream]):
            result = asyncio.run(
                agent_loop.agent_loop(
                    [{"role": "user", "content": "今天英语怎么学"}],
                    role="student",
                    db=db,
                    teacher_id=2,
                )
            )

        plans = p2_service.list_study_plans(db, 2, status="")
        assert all(plan.title != "英语错题补漏" for plan in plans)
        assert "先确认一下" in result[-1]["content"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext -q
```

Expected: FAIL because system does not yet include `[学习记忆]`.

- [ ] **Step 4: Implement main loop injection**

In `agent_loop(...)`, after existing profile context append, add:

```python
    latest_user_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            latest_user_text = str(message.get("content") or "")
            break

    if profile_sid:
        learning_memory_context = _build_learning_memory_context(db, profile_sid, latest_user_text)
        if learning_memory_context:
            system += learning_memory_context
```

Keep this after `_build_profile_context(...)` so order remains:

1. Base system prompt
2. `[学生画像]`
3. `[学习记忆]`

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext tests/unit/test_agent_loop.py::TestStudyPlanReminder -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add studybuddy-backend/app/core/agent_loop.py studybuddy-backend/tests/unit/test_agent_loop.py
git commit -m "接入错题优先上下文"
```

---

### Task 4: 文档、更新记录与验收口径

**Files:**
- Modify: `docs/已实现能力清单.md`
- Modify: `docs/未实现需求清单.md`
- Modify: `studybuddy-client/src/data/releaseNotes.ts`
- Modify: `docs/真人验收指南.md`

**Interfaces:**
- Consumes: implemented backend behavior from Task 3
- Produces: user-visible update notes and human validation steps

- [ ] **Step 1: Update 已实现能力清单**

In `docs/已实现能力清单.md`, add or update the Agent row to include:

```markdown
| Agent 错题优先上下文 | 讲题、制定计划、复盘、推荐练习前会自动注入近期高频错题、代表性错题和错题复盘笔记；回答时要求说明依据，数据不足时不编造 | 让 AI 更像长期学习教练，而不是一次性答题工具 |
```

Also update “最近验证” after tests/browser validation with the actual date and commands.

- [ ] **Step 2: Update 未实现需求清单**

In `docs/未实现需求清单.md`, remove U-002 from P1 or change its row to point to 已实现能力清单. Keep U-004, U-005, U-006 and learning map items as未实现.

If preserving history is useful, add a short note under 产品方向调整:

```markdown
> U-002「错题优先上下文」已进入已实现能力清单，后续继续做掌握状态、复练和学习地图。
```

- [ ] **Step 3: Update release notes**

In `studybuddy-client/src/data/releaseNotes.ts`, add a new item in the latest release group:

```ts
{
  title: 'Agent 会优先参考近期错题和复盘笔记',
  description: '讲题、计划、复盘和推荐练习时，AI 会先看近期高频错题、代表性错题和错题复盘笔记；数据不足时会提醒补充，不再装作已经了解。',
}
```

Use the file's existing data shape and naming style.

- [ ] **Step 4: Update 真人验收指南**

In `docs/真人验收指南.md`, add section:

```markdown
## 错题优先上下文验收

1. 用学生账号登录。
2. 确认错题本里至少有一条错题，并且最好有一篇“错题复盘”笔记。
3. 打开聊天页，输入：“今天英语怎么学？”
4. 看 AI 是否先提到最近错题、错因或复盘笔记，再给计划草案。
5. AI 如果直接创建计划，没有先问可不可行，记为失败。
6. 再输入：“给我练两道类似的。”
7. 看 AI 是否围绕刚才提到的薄弱知识点，而不是随机出题。

验收结果填写：
- 是否提到真实错题/笔记：
- 是否先商量计划：
- 是否没有编造不存在的历史：
- 体验是否自然：
```

- [ ] **Step 5: Run doc grep checks**

Run:

```bash
rg -n "错题优先上下文|近期高频错题|复盘笔记" docs studybuddy-client/src/data/releaseNotes.ts
```

Expected: updated docs and release notes include the new capability.

- [ ] **Step 6: Commit**

```bash
git add docs/已实现能力清单.md docs/未实现需求清单.md docs/真人验收指南.md studybuddy-client/src/data/releaseNotes.ts
git commit -m "更新错题优先上下文文档"
```

---

### Task 5: Full Verification and Browser Smoke

**Files:**
- No code changes unless verification finds a bug.

**Interfaces:**
- Consumes: all previous tasks
- Produces: verification evidence before deployment

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py::TestLearningMemoryContext tests/unit/test_agent_loop.py::TestStudyPlanReminder tests/unit/test_agent_loop.py::TestWrongReasonFeedbackContext tests/unit/test_agent_loop.py::TestDailyReviewContext -q
```

Expected: PASS.

- [ ] **Step 2: Run backend broader agent tests**

Run:

```bash
cd studybuddy-backend
pytest tests/unit/test_agent_loop.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend static checks only if release notes changed**

Run:

```bash
cd studybuddy-client
npm run typecheck
npm run build
```

Expected: both PASS.

- [ ] **Step 4: Browser smoke with Codex in-app browser**

Use the existing local or deployed app:

1. Login as student.
2. Open `/chat`.
3. Ask `今天英语怎么学？`.
4. Confirm the answer references real recent wrong questions or says data is insufficient.
5. Confirm it asks the student whether the plan is feasible before creating a plan.

Expected: The response is based on student data and does not immediately create a plan.

- [ ] **Step 5: Commit verification-only fixes if needed**

If verification finds a small bug, fix it and commit with:

```bash
git add <changed-files>
git commit -m "修复错题上下文验收问题"
```

If no fixes are needed, do not create an empty commit.

- [ ] **Step 6: Push branch**

Run:

```bash
git status --short --branch
git push
```

Expected: branch pushed with all U-002 commits.
