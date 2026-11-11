# 模块化迁移准备 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为后端「按业务功能模块化」迁移准备防丢校验工具，并把已决策的架构方向沉淀进架构文档、需求文档和技术债清单。本阶段不动业务代码，只产出一个可复用的迁移校验脚本 + 文档收口 + 3 个 ADR。

**Architecture:** 校验脚本对照三道网验证迁移不丢东西：(1) openapi.json 路由 diff（抓漏路由/改错 prefix/漏挂载）；(2) 旧 import 路径 rg 清零（抓漏改 import，含 agent_loop 函数内延迟 import）；(3) 公开函数清单对比（抓漏迁函数）。脚本用 TDD：先造「假装漏迁」的 fixture，让脚本能 diff 出差异并 exit 非 0，再实现。文档更新把技术债清单「四、待决策」改为「已决策：模块化单体」，修正架构文档里 DDL 机制的措辞（真实是 `sql/001-020_*.sql` 增量脚本 + `scripts/run_ddl.py`，非 `ensure_*_table.py`），并补 growth 子包结构、materials providers/、迁移顺序、ADR、实施原则。

**Tech Stack:** Python 3.11、pytest、bash、rg。

> **进度（2026-07-19）**：本准备 plan 已随 PR #56 完成 Task 1-3（verify 脚本 7 测试绿 + docs 收口 + 3 ADR + 技术债清单），Task 4 收尾待 #58 CI 修复 merge 后跑全量验证。**#57 已完成 question_bank PR-A**（god module 拆 4 子 + 门面，44 unit + 24 API 测试绿），见 `docs/requirements/13-后端按业务功能模块化拆分.md` §6 进度注。主线：#56 -> #57 -> PR-B 搬目录（用本 plan 的 verify 脚本校验）。

---

### Task 1: 写防丢校验脚本（TDD，subagent-driven）

**Files:**
- Create: `studybuddy-backend/scripts/verify_module_migration.py`
- Test: `studybuddy-backend/tests/scripts/test_verify_module_migration.py`
- Fixture: `studybuddy-backend/tests/scripts/fixtures/migration/`

**Interfaces:**
- `verify_module_migration.py openapi-diff --before <openapi.json> --after <openapi.json>`：比对 paths 与 components，有差异 exit 1
- `verify_module_migration.py old-path --pattern <regex> --root <dir>`：检查旧 import 路径清零，有残留 exit 1
- `verify_module_migration.py fn-diff --before-fns <file> --after-fns <dir>`：比对公开函数清单，有缺失 exit 1
- Exit code：0 = 一致；1 = 发现差异（漏迁）

- [x] **Step 1: 写失败测试。** 造 fixture：`before_openapi.json` 有路由 `/api/question-bank/papers`，`after_openapi.json` 少这条；fixture 源文件里有 `from app.services.question_bank`；`before_fns.txt` 比 `after_fns` 多一个 `search_public_paper_candidates`。测试断言三个子命令都 exit 1 且 stderr 报出具体差异。
- [x] **Step 2: 跑测试验证 RED。** `cd studybuddy-backend && .venv/bin/python -m pytest tests/scripts/test_verify_module_migration.py -q`，预期 ImportError（脚本不存在）。
- [x] **Step 3: 实现脚本。** 三个子命令，各自对比、发现差异打印具体内容并 exit 1，一致 exit 0。openapi-diff 用 `jq` 或 Python json 对比 paths 和 components.schemas；old-path 用 `rg`；fn-diff 用 `rg "^def |^async def "` 提取后 sort 对比。
- [x] **Step 4: 跑测试验证 GREEN。** 三个 fixture 场景都正确 exit 1 报差异；再造一组「完全一致」的 fixture 验证 exit 0。
- [x] **Step 5: 真实 smoke。** 对当前真实 backend 跑一次 openapi-diff（before=after 同一份抓取的 openapi.json），确认 exit 0。抓取命令：`curl -s localhost:8001/openapi.json`（若本地未起，文档说明手动抓取方式，不强依赖运行实例）。
- [x] **Step 6: Review。** 派 review subagent 审脚本逻辑、三道网是否与文档描述一致、测试覆盖是否够、有无误报。
- [x] **Step 7: Commit。** `增加模块化迁移防丢校验脚本`。

### Task 2: 补建议进架构文档与需求文档 + ADR

**Files:**
- Modify: `docs/后端模块化架构.md`
- Modify: `docs/requirements/13-后端按业务功能模块化拆分.md`
- Create: `docs/adr/0001-feature-modularization.md`
- Create: `docs/adr/0002-models-centralized.md`
- Create: `docs/adr/0003-agent-as-orchestrator.md`

- [x] 架构文档 §3 修正 DDL 措辞：`sql/001-020_*.sql` 增量脚本 + `scripts/run_ddl.py` 执行器，`ensure_*.py` 为补充。
- [x] 架构文档 §4.2 growth 行补子包结构（records/summary/supervision/intent 四个子域）。
- [x] 架构文档 §4.2 materials 行补 `providers/` 预留（docling/mineru/marker）。
- [x] 需求文档 §7 阶段表迁移顺序改为：question_bank -> exams -> error_book+learning -> growth -> wechat/agent（wechat 1209 行线上关键放最后）。
- [x] 需求文档新增 §10 实施原则：一次一 feature、必要时保留兼容转发层、不混业务改动、API 变化单独提交、迁完更新目录树/依赖图/技术债清单、service 超 500 行先拆子模块。
- [x] 新建 3 个 ADR，每个含：决策 / 背景 / 选择 / 放弃的方案 / 影响。0001 模块化单体决策（放弃微服务）、0002 models 集中（放弃 model 进 feature）、0003 agent 即编排层（放弃 agent_loop 拆进各域）。

### Task 3: 更新技术债清单

**Files:**
- Modify: `docs/技术债与重构清单.md`

- [x] 「四、待决策：后端模块化拆分」改为「四、已决策：模块化单体」，指向需求文档 13 和架构文档。
- [x] 「三、优先级」表里中3/中4/中5/中6 的「建议和拆分一起定」标注，改为「随模块化迁移消解（见架构文档 §4.2 对应 feature）」。
- [x] 新增一行指向迁移校验脚本 `studybuddy-backend/scripts/verify_module_migration.py`，说明三道网用途。

### Task 4: 验证与收尾

- [x] `cd studybuddy-backend && .venv/bin/python -m pytest tests/scripts/test_verify_module_migration.py -q`（校验脚本自身测试绿）
- [ ] `cd studybuddy-backend && .venv/bin/python -m pytest -q`（确认未碰业务代码，全量仍绿）
- [ ] 文档交叉引用检查：技术债清单、架构文档、需求文档、ADR 互相指向一致，无断链。
- [ ] 更新 `.superpowers/sdd/progress.md` 记录本次 plan/task 状态。
- [ ] verification-before-completion：用新鲜命令输出证明脚本测试绿、文档无断链、git 状态干净。
