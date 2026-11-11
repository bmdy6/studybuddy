# 提交 PR skill + CI AI 代码审查 设计

> 日期：2026-07-16
> 状态：设计待审

## 背景与目标

当前项目改动靠对话里临时提醒提交，没有标准化的 PR 流程 skill；CI 只跑测试，没有 AI 审查，代码质量/功能符合性全靠人工把关。

本设计做两件互相独立但配套的事：

1. **「提交 PR」skill**：把"按 PR 规范提交、不合并 main"沉淀成项目级 skill，后面每次都按它走，避免漏步。
2. **CI AI 代码审查**：在 GitHub Actions 的 PR 流程里内置一个 AI reviewer，用 MiMo 按项目 `zhixueban-code-reviewer` 标准审查 diff，结果发一条结构化 PR comment，best-effort 不阻断合并。

两者配合：skill 负责规范提交，CI reviewer 负责自动审查，人工只做最终合并决策。

### 不做

- 不做自动合并（合并始终由用户人工决定）。
- 不做行级 inline review comment（只发一条总结 comment）。
- 不引入第三方 AI reviewer action（代码不外泄给第三方）。
- 不动现有 `backend.yml`/`frontend.yml`/`e2e.yml`/`release.yml` 的测试逻辑。

## 子项一：「提交 PR」skill

### 文件

新建 `docs/skills/zhixueban-pr-submitter/SKILL.md`，与现有 3 个 skill 同目录同风格（frontmatter `name` + `description`，正文中文）。

### 触发场景

用户说"提交 PR""发 PR""按规范提交""帮我提个 PR"时使用。当前分支已有改动、需要走 PR 流程时也适用。

### 检查清单（skill 正文核心）

按顺序执行，每步可人工确认；push 和 create PR 是外向不可逆动作，默认先告知用户再执行：

1. **分支检查**：确认当前不在 `main`；若在 main，先建分支（命名 `<类型>/<简短描述>`，类型如 fix/feat/docs）。
2. **测试**：按改动范围跑测试。
   - 后端：`cd studybuddy-backend && .venv/bin/python -m pytest -q`
   - 前端：`cd studybuddy-client && npm run lint && npm test && npm run typecheck && npm run build`
   - 涉及 LLM/视觉功能：补 live 测试并 `--run-live` 跑过一次
   - 测试不过先修，不带着红测试提 PR
3. **diff 自检**：`git status` + `git diff` 检查
   - 无临时文件、截图、`.env`、`.env.local.bak`、构建缓存、临时脚本
   - 无 mock-only 的"通过"（涉及 AI/视觉要有 live 证据）
   - 改动范围合理，没有夹带无关改动
4. **提交信息**：写简洁中文 commit message，一眼看懂做了什么；多个改动分多个 commit 还是合并由改动主题决定，但一个 PR 聚焦一个主题。
5. **commit**：`git add` 相关文件（不 `git add .`），commit。
6. **push**：`git push -u origin <分支名>`，push 前告知用户。
7. **建 PR**：`gh pr create --title "<中文标题>" --body "<正文>"`
   - 正文模板：
     - **改动说明**：做了什么、为什么
     - **测试**：跑了哪些测试、结果
     - **验收**：浏览器/live 验收路径和结果（如有）
     - **不合并**：提示"请人工审查后再合并"
8. **等待与提示**：告知用户 PR 已创建，等 CI（含 AI reviewer）跑完，提醒用户审查后决定是否合并。**不自动合并。**

### 边界

- skill 是流程引导，不替代 `zhixueban-release-verification`（上线验收）和 `zhixueban-code-reviewer`（人工审查标准）。提 PR 前若涉及上线，仍要走 release-verification。
- 不负责更新文档/帮助/进度（那是 release-verification 的职责），但 commit 前会提醒"文档是否同步"。

## 子项二：CI AI 代码审查

### 文件

1. 新增 `.github/workflows/ai-review.yml`：PR 触发的 workflow。
2. 新增 `scripts/ai_review.py`：调 MiMo 审查 diff 的脚本（放项目根 `scripts/`，与现有 `scripts/deploy_all.sh` 同级）。

### workflow 结构（`ai-review.yml`）

```yaml
name: AI 代码审查
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    continue-on-error: true        # best-effort，不阻断
    permissions:
      pull-requests: write         # 发 comment
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0           # 拿全历史才能 diff base...head
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: 安装依赖
        run: pip install openai
      - name: 运行 AI 审查
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          LLM_BASE_URL: ${{ secrets.LLM_BASE_URL }}
          LLM_MODEL: ${{ secrets.LLM_MODEL }}
        run: |
          python scripts/ai_review.py \
            --pr ${{ github.event.pull_request.number }} \
            --base ${{ github.event.pull_request.base.sha }} \
            --head ${{ github.event.pull_request.head.sha }}
```

- `GITHUB_TOKEN` 自动提供，无需配置。
- `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL` 需用户在 GitHub 仓库 Settings → Secrets 配置（值取自后端 `.env`，base_url/model 可用默认）。
- `continue-on-error: true` 保证审查失败不卡 PR。

### 审查脚本（`scripts/ai_review.py`）

**输入**：PR number、base sha、head sha（通过命令行参数传入）。
**流程**：
1. 用 `gh pr diff <number>` 或 `git diff base...head -- <排除项>` 取 diff。
   - 排除 lockfile、生成文件、测试 fixture 等噪声（`package-lock.json`、`*.min.js`、`htmlcov/` 等）。
   - diff 超长时截断（保留头部，如 > 8000 行只取前 8000 行并注明截断）。
2. 读审查基准：`AGENTS.md` + `docs/代码规范.md`（若存在）的关键段落，拼进 system prompt。
3. 调 MiMo（OpenAI 兼容，复用 `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`），同步 `client.chat.completions.create`，超时 120s。
4. 把模型输出用 `gh pr comment <number> --body "<内容>"` 发到 PR。
5. 全程 try/except：任何失败（diff 取不到、MiMo 超时/限流/key 失效、gh 命令失败）只发一条"⚠️ AI 审查未跑成功（原因），请人工审查"comment，不抛错（配合 workflow `continue-on-error`）。

**审查 prompt 要点**（system + user）：
- system：你是知了项目的代码审查助手。按项目标准审查以下 PR diff，只看代码，不修改。审查维度：① 重复造轮子（是否复用现有 service/组件/工具）② 硬编码（接口/角色/颜色/密钥/枚举）③ 越权/数据可见性 ④ 测试不足（mock-only、缺 live、缺边界）⑤ 体验不合理（文案/流程/状态）⑥ 功能是否符合改动说明。输出按严重程度分 critical / warning / nit 三档，每条给文件:行号 + 问题 + 建议；无明显问题就说明 LGTM。
- user：附上 PR 标题、diff（截断后）、改动说明（从 PR body 取）。

### 失败兜底

- MiMo 超时/限流：发"AI 审查超时/限流，请人工审查"comment。
- key 未配置/失效：发"AI 审查未配置 key，请人工审查"comment。
- diff 为空或超长截断：仍审查可见部分，comment 注明截断。
- 全部失败路径都不阻断 PR（`continue-on-error`）。

### 幂等性

- 每次 push（synchronize）会重新触发、重发一条 comment。不做去重/编辑旧 comment（MVP 不做，避免复杂度）；comment 会带时间戳和 head sha 便于区分。
- 未来若 comment 噪声大，可改为编辑同一条 comment（用 `gh api` 查已有 reviewer comment 并 edit），本期不做。

## 测试口径

### skill

- skill 是文档，无单测。验证方式：dogfood——用本 spec 对应的改动（fix/agent-follow-user-goal 分支）作为第一个 PR，按 skill 清单走一遍，确认流程顺畅无遗漏。

### CI AI reviewer 脚本

- `scripts/ai_review.py` 是独立脚本，可本地手动跑验证：
  - 本地设 `LLM_API_KEY` 等环境变量，对一个真实 PR number 跑 `python scripts/ai_review.py --pr <n> --base <sha> --head <sha>`，看是否产出结构化 comment 内容（先打到 stdout，不实际发）。
  - 加 `--dry-run` 参数：只打印审查结果到 stdout，不发 `gh pr comment`，便于本地验证 prompt 效果。
- 真正的 PR comment 触发验证：dogfood PR 推上去后看 GitHub Actions 是否跑出 comment。

### 端到端 dogfood

1. 用本 spec + 实施计划本身作为改动，按 `zhixueban-pr-submitter` skill 提一个 PR。
2. CI 跑 `ai-review.yml`，对"新增 skill + CI reviewer"这个改动本身做 AI 审查。
3. 用户看 AI 审查 comment + 自己看，确认后人工合并。

## 数据流

```
开发者改代码（本地）
  → 按 zhixueban-pr-submitter skill：测试、自检、commit、push、gh pr create
  → GitHub 收到 PR，触发 ai-review.yml
  → workflow checkout + 取 diff + 读规范 + 调 MiMo
  → MiMo 返回审查结论
  → gh pr comment 发一条结构化 comment
  → 用户看 comment + 测试 CI 状态 + 自己审查
  → 用户人工合并（或要求修改）
```

## 权限与安全

- `GITHUB_TOKEN` 只有当前仓库的 PR 写权限，作用域最小化（`pull-requests: write` + `contents: read`）。
- MiMo key 进 GitHub Secrets，不进代码、不进日志（脚本不 echo key）。
- diff 内容发往 MiMo（小米）——与后端运行时调用 MiMo 同一服务商，无新增数据外泄面。
- 审查 comment 是公开可见的 PR comment，不含密钥（脚本不会把 .env 等内容发给模型，只发 diff 和规范文档）。

## 成功标准

1. `docs/skills/zhixueban-pr-submitter/SKILL.md` 存在，清单完整可执行。
2. `.github/workflows/ai-review.yml` + `scripts/ai_review.py` 存在，本地 `--dry-run` 能对真实 PR 产出结构化审查结果。
3. dogfood PR（本改动自身）推上去后，GitHub Actions 跑出一条 AI 审查 comment，按 critical/warning/nit 分档。
4. AI 审查失败时不阻断 PR（`continue-on-error` 验证）。
5. 用户根据 AI comment + 自查决定合并，skill 全程未自动合并。

## 风险与取舍

- **MiMo 审查质量未知**：MiMo 不是专门为 code review 训练的，审查可能不如 GPT-4 准。取舍：零成本 + 不外泄代码 + 中文场景适配，先跑起来看效果，不好再换。dogfood PR 本身就是第一次实测。
- **comment 噪声**：每次 push 重发 comment。MVP 接受，未来可改为编辑同一条。
- **diff 超长**：大 PR 可能截断丢失上下文。MVP 截断 + 注明，大 PR 本就该拆。
- **行号偏移**：总结 comment 不挂行号，靠 AI 在文字里写"文件:行号"，可能不准。用户可据此自己定位，不阻断。
