---
name: zhixueban-pr-submitter
description: Use when submitting a 智学伴 PR — committing, pushing, and creating a pull request on GitHub. Triggered by "提交 PR""发 PR""按规范提交""提个 PR". Never auto-merges; human reviews and merges.
---

# 智学伴提交 PR 流程

## 使用场景

用于把当前分支的改动按规范提交为 GitHub Pull Request。它是项目内维护的流程 skill，和 `zhixueban-release-verification`（上线验收）、`zhixueban-code-reviewer`（人工审查标准）分工：

- 本 skill 只管「规范提交 PR、不合并」。
- 涉及上线的改动，提 PR 前仍要先走 `zhixueban-release-verification`。
- 代码审查标准见 `zhixueban-code-reviewer`，CI 里的 AI 审查也会自动跑。

## 必走清单

按顺序执行，每步可人工确认。push 和创建 PR 是外向不可逆动作，执行前先告知用户。

### 1. 分支检查

- 确认当前不在 `main`：`git branch --show-current`。
- 若在 `main`，先建分支：命名 `<类型>/<简短描述>`，类型如 `fix`/`feat`/`docs`/`chore`。
- 一个 PR 聚焦一个主题，不要把多个无关改动混在一个 PR。

### 2. 测试

按改动范围跑测试，不带着红测试提 PR：

- 后端改动：`cd studybuddy-backend && .venv/bin/python -m pytest -q`
- 前端改动：`cd studybuddy-client && npm run lint && npm test && npm run typecheck && npm run build`
- 涉及 LLM/视觉功能：必须补 live 测试（`tests/live/`，`@pytest.mark.live`）并 `--run-live` 跑过一次，确认不是 mock-only 的"通过"。
- 测试不过先修，修好再继续。

### 3. diff 自检

`git status` + `git diff`（含 `--cached`）逐项检查：

- 无临时文件、截图、`.env`、`.env.local.bak`、构建缓存（`htmlcov/`、`dist/`、`.vite/`）、临时脚本。
- 无 mock-only 的"通过"（涉及 AI/视觉要有 live 证据，见 AGENTS.md 真机测试约束）。
- 改动范围合理，没有夹带与本 PR 主题无关的改动。
- 若有附带的小脏改动（如 .gitignore 加一行），要么摘到单独 PR，要么在 PR 正文说明。

### 4. 提交信息

- 写简洁中文 commit message，一眼看懂做了什么。
- 多个改动是分多个 commit 还是合并，由改动主题决定；但一个 PR 聚焦一个主题。

### 5. commit

- `git add` 相关文件，不要 `git add .`（避免误加临时文件）。
- `git commit -m "<中文信息>"`。

### 6. push

- `git push -u origin <分支名>`。
- push 前告知用户「要推到 origin 了」。

### 7. 建 PR

```bash
gh pr create --base main --head <分支名> \
  --title "<中文标题>" \
  --body "<正文>"
```

正文模板：

```
## 改动说明
做了什么、为什么（关联需求/spec/issue）。

## 测试
跑了哪些测试、结果（含 live 验收证据，如有）。

## 验收
浏览器/live 验收路径和结果（如有）。

## 不合并
请人工审查后再合并。本 PR 是否涉及上线。
```

### 8. 等待与提示

- 告知用户 PR 已创建，给链接。
- 提醒：等 CI（含后端测试、前端测试、AI 代码审查）跑完，用户审查后决定是否合并。
- **不自动合并。** 合并始终由用户人工决定。

## 边界

- 本 skill 不替代文档同步（`release-verification` 负责）、不替代人工审查（`zhixueban-code-reviewer` + 用户自己看）。
- commit 前会提醒"文档/帮助/进度是否已同步"，但不强制在本 skill 内完成。
- 若用户明确说"直接合并"或"合并到 main"，仍要先确认 CI 绿 + 用户已看过 diff，再合；默认不合并。
