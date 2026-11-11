# 技能树（MapFlow）接入 xcc 学习地图 调研（快速概览）

> 日期：2026-08-24
> 状态：调研初稿（待你确认后进 K3）
> 结论先行：MapFlow 的“树模型+画布+生成Skill”可直接复用来升级你现有的学习地图，不用新开页面，也不动现有素材/笔记/错题数据。

## 1. 是什么、做什么、有什么用

* **是什么：** MapFlow `rongyan-123/MapFlow` 是一个“学一个点点亮一个”的技能树平台，已上线 `xxian.fun`。模型是 `SkillTree / SkillNode / SkillEdge / progress`，每个节点带 `推荐深度 Recognize→DeepMastery + 深度理由 + 学习目标 + 验收证据`，边是先修关系。
* **做什么：** 前端用 `React Flow` 画可拖拽图，用 `layoutTree` 自动排版；提供一个通用 `skills/skill-tree-generator/SKILL.md`，让任何 AI 按“先问目标→搜4类资料→确认分层→逐模块填节点”产出 `SKILL_TREE.json`。
* **有什么用（对你）：** 正好补上 `xcc` 的 K3/K4 —— 你现在的 `LearningMapPage.tsx` 只是按 `knowledge_tag` 自由文本聚合，分 `weak/reviewing/stable` 四组折叠，无 `depth_level` 也无先修边。MapFlow 就是把这堵“标签墙”变成有层级、有路径的图谱。

## 2. 现状对比（已读代码）

| 维度 | xcc 现状 | MapFlow 可抄 |
|---|---|---|
| 后端 | `map_service.py` 按 `student_id` 聚合错题/笔记/素材/计划的 tag 计数，无层级表 | `SkillTree/SkillNode/SkillEdge` 三表 + `node_progress` 按人隔离 |
| 前端 | `LearningMapPage.tsx` 列表 + 首屏推荐卡 + `?knowledge_tag=` 深链到错题/笔记/素材 | `SkillTreeCanvas.tsx + layoutTree.ts + 20字段类型`，状态动画、MiniMap、fitView 自带 |
| 生成 | 人工打标签 | Skill 两阶段向导：A.问职业/项目目标 B.搜 roadmap/awesome/脑图/JD 再生成 |

## 3. 怎么融（不新开页，最懒路径）

**原则：共存不推倒，老 tag 即节点。**

1. **模型加列：** `knowledge_tag` 仍是主键，追加 `category(主干模块)/depth_level/position/ recommended_depth/depth_rationale/key_concepts/observable_evidence` 字段，新增 `skill_edge(source→target)` 一张表。素材/笔记/错题仍用 `knowledge_tags` 挂节点，不迁移。
2. **视图替换：** 把 `LearningMapPage` 的“四组列表”那段换成 `SkillTreeCanvas`，状态色沿用 `weak红/reviewing黄/stable绿`，节点详情复用现有“错× 笔记× 素材× 查看全部”按钮。
3. **生成接入：** 把 `SKILL.md` 的提示词改成调你现有的 `mimo-v2.5`（MapFlow 默认 DeepSeek，Key只驻内存不入库），在 Agent 侧注册为工具“生成技能树”，产物直接落库，前端秒画。

改动面：前端抄 3 文件 + 后端 3 表 + 1 个生成工具，后台任务零侵入，老地图可灰度切换。

## 4. 值不值得继续看

* **值得：** MIT 可商用，React 18 + Vite + TS 技术栈与你 `studybuddy-client` 一致，抄起来无缝。文档和测试（20个）也比 `xi` 完整，`main` 就是线上主线。
* **边界：** MapFlow 的 `mapflow-server` 私有，别依赖 `xxian.fun`；生成质量靠“研究来源”保证，无自动校验，需人工确认分层。

## 5. 下一步

* **Spike（半天）：** 用现有 30 个 `knowledge_tag` 套上 MapFlow 层级，在本地跑通 `SkillTreeCanvas`，手机端 390×844 验无溢出。
* **确认后进 K3：** 建表 → 灰度 `LearningMapPage` → 上线 `生成Skill`。

> 本调研为快速概览，未做全量模型字段审计和线上压力测；确认做再展开深研。
