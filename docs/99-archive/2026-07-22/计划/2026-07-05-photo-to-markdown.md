# Photo To Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change拍题批改 from direct image-to-JSON grading to image-to-Markdown recognition first, then Markdown-based grading after user confirmation.

**Architecture:** Reuse current MiMo vision path and exam batch storage. Add a Markdown recognition helper in `photo_grading_service`, expose it through a new Agent tool, and make the existing forced upload intent call recognition first. Keep the first version chat-driven; no new OCR dependency or editor UI.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, existing OpenAI-compatible MiMo client, React/Vite/AntD.

## Global Constraints

- Do not introduce Pix2Text, Marker, Zerox, or another heavy dependency in this MVP.
- Do not auto-save recognized or graded questions into the error book before explicit user confirmation.
- Preserve original uploaded images and batch ids.
- If Markdown recognition succeeds but structured grading fails, the user must still see the Markdown text.
- Keep browser validation for true user flows only; static release/help text can be verified by tests or local build.

---

### Task 1: Markdown Recognition Service

**Files:**
- Modify: `studybuddy-backend/app/services/photo_grading_service.py`
- Test: `studybuddy-backend/tests/unit/test_photo_grading_service.py`

**Interfaces:**
- Produces: `normalize_photo_markdown_result(raw_text: str) -> PhotoMarkdownResult`
- Produces: `PhotoMarkdownResult` with fields `markdown`, `confidence`, `uncertain_points`, `content_type`, `raw_text`

- [ ] **Step 1: Write failing tests**

Add tests that verify:

```python
def test_normalize_photo_markdown_result_keeps_markdown_and_uncertain_points():
    raw = """
    ```markdown
    ### 知识点3 误差和错误
    学生作答：偏大 / 误差 / 不能

    **识别置信度**：85%
    **需要人工确认的内容**：第三空是否为“不能”
    **适合作为哪类学习素材**：初中物理易错点
    ```
    """

    result = normalize_photo_markdown_result(raw)

    assert "误差和错误" in result.markdown
    assert result.confidence == "medium"
    assert result.uncertain_points == ["第三空是否为“不能”"]
    assert result.content_type == "初中物理易错点"
```

Run: `cd studybuddy-backend && ./.venv/bin/pytest tests/unit/test_photo_grading_service.py::test_normalize_photo_markdown_result_keeps_markdown_and_uncertain_points -q`
Expected: FAIL because the function/type does not exist.

- [ ] **Step 2: Implement minimal parser**

Add a Pydantic model and parser that strips Markdown fences, preserves the body, maps percentage confidence to `high|medium|low`, and extracts the two summary lines when present.

- [ ] **Step 3: Verify service tests**

Run: `cd studybuddy-backend && ./.venv/bin/pytest tests/unit/test_photo_grading_service.py -q`
Expected: PASS.

### Task 2: Agent Tool Chain

**Files:**
- Modify: `studybuddy-backend/app/core/agent_loop.py`
- Test: `studybuddy-backend/tests/unit/test_agent_loop.py`

**Interfaces:**
- Produces tool `recognize_homework_photo_markdown(batch_id: int)`
- Existing `grade_homework_photo(batch_id: int, confirmed_markdown?: str)` can grade from confirmed Markdown when provided.

- [ ] **Step 1: Write failing tests**

Add tests that verify:

```python
def test_student_can_recognize_homework_photo_markdown():
    student_tools = {t["name"] for t in agent_loop.tools_for_role("student")}
    assert "recognize_homework_photo_markdown" in student_tools

def test_homework_photo_batch_forces_markdown_recognition_first():
    forced = agent_loop._forced_error_import_tool([
        {"role": "user", "content": "[拍题批改] 已上传 1 张照片到批次 #999，请先逐题批改。"}
    ])
    assert forced == {"name": "recognize_homework_photo_markdown", "args": {"batch_id": 999}}
```

Run: `cd studybuddy-backend && ./.venv/bin/pytest tests/unit/test_agent_loop.py::TestToolRegistry::test_student_can_recognize_homework_photo_markdown tests/unit/test_agent_loop.py::TestErrorImportIntentGuard::test_homework_photo_batch_forces_markdown_recognition_first -q`
Expected: FAIL.

- [ ] **Step 2: Add tool definition and handler**

The handler should load batch photos, call MiMo with a Markdown-only prompt, normalize through `normalize_photo_markdown_result`, set `batch.status = "parsed"`, and return:

```python
{
    "batch_id": batch.id,
    "recognized_markdown": result.markdown,
    "confidence": result.confidence,
    "uncertain_points": result.uncertain_points,
    "content_type": result.content_type,
    "summary": "已识别为 Markdown，请先核对题目和作答，确认后我再批改。"
}
```

- [ ] **Step 3: Let direct grading accept confirmed Markdown**

If `grade_homework_photo` receives `confirmed_markdown`, call the LLM with text only and request JSON grading from that confirmed text. If absent, keep current image-based fallback for compatibility.

- [ ] **Step 4: Verify Agent tests**

Run: `cd studybuddy-backend && ./.venv/bin/pytest tests/unit/test_agent_loop.py tests/unit/test_photo_grading_service.py -q`
Expected: PASS.

### Task 3: Frontend Copy And Chat Flow

**Files:**
- Modify: `studybuddy-client/src/pages/ChatPage.tsx`
- Test: `studybuddy-client/src/test/ChatPage.test.tsx`

**Interfaces:**
- Consumes existing upload APIs.
- Produces chat message asking Agent to recognize Markdown first.

- [ ] **Step 1: Write failing test**

Update the existing拍题 upload test so the sent message contains:

```text
请先把照片识别成 Markdown
```

Run: `cd studybuddy-client && npm test -- ChatPage.test.tsx`
Expected: FAIL until copy changes.

- [ ] **Step 2: Update user-facing copy**

Change upload modal and sent chat message:

```text
已上传 N 张照片到批次 #ID（任务名）。请先把照片识别成 Markdown，保留题干、选项和我的作答；让我确认识别稿后，再逐题批改并给正确答案、错因和知识点。
```

- [ ] **Step 3: Verify frontend tests**

Run: `cd studybuddy-client && npm test -- ChatPage.test.tsx`
Expected: PASS.

### Task 4: Verification And Docs

**Files:**
- Modify: `docs/已实现能力清单.md`
- Modify: `docs/开发进度文档.md`
- Modify: `studybuddy-client/src/data/releaseNotes.ts`

**Interfaces:**
- Documents new MVP behavior and remaining boundary.

- [ ] **Step 1: Update docs**

Document that拍题 first recognizes Markdown and requires confirmation before grading/入错题.

- [ ] **Step 2: Run checks**

Run:

```bash
cd studybuddy-backend && ./.venv/bin/pytest tests/unit/test_photo_grading_service.py tests/unit/test_agent_loop.py -q
cd studybuddy-client && npm test -- ChatPage.test.tsx
cd studybuddy-client && npm run typecheck
cd studybuddy-client && npm run lint
cd studybuddy-client && npm run build
```

Expected: all commands exit 0.
