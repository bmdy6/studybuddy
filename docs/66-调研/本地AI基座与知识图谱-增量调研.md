# 本地AI基座与知识图谱 增量调研（叠在技能树之上）

> 日期：2026-08-24
> 关联：`技能树-MapFlow接入学习地图-调研.md`
> 结论先行：`MapFlow` 管可视化与生成，`koharu/club-3090/semantica` 管本地化底座与可追溯知识，三件套叠在现有学习地图上，不另起项目。

## 1. 一句话定位

| 项目 | 管什么 | 与 xcc 的缝 |
|---|---|---|
| `mayocream/koharu` | Rust 漫画/版面 `检测→OCR→擦除→翻译→排版` 全本地 | 你 `pdf-inspector` 只读文本型PDF，扫描版教材正好补上 |
| `noonghunna/club-3090` | 3090 本地跑大模型配方（vLLM/llama.cpp 双路，127TPS/262K） | 你 `mimo-v2.5` 云API 可平滑切到本地 3090 自托管，降成本 |
| `semantica-agi/semantica` | `pip install semantica` 的 Graph-Native 底座（抽实体/关系/去重/推理/溯源） | MapFlow 只画树，Semantica 把 `错题/笔记/素材` 自动抽成图谱并回答“为什么这么判” |

## 2. 值得抄的（只抄增量能力）

* **kohanru：** `RF-DETR Seg 2XL 检测 + PaddleOCR VL/Manga OCR + LaMa/FLUX擦除 + GGUF本地方案 + WebGPU画布`，`Tauri` 跨端，`MIT/Apache`。只抄 `检测+OCR` 链，教材扫描页先过这链再进你现有的 `素材标签`。
* **club-3090：** `setup.sh/launch.sh/c3` 一键起 OpenAI 兼容接口，`vLLM dual` 最快 vs `llama.cpp single` 最稳（200K无崩），`CLIFFS.md` 踩坑全写。只抄“本地开服”这层，你的 `llm.reasoning_effort` 保持不变。
* **semantica：** `Sources→Parse→Normalize→Split→Extract→Conflict→Deduplication→KG→Ontology/Reasoning/Provenance/Context` 全链，`W3C PROV-O` 每 факт可追溯，`SHACL` 约束防脏数据。只抄 `语义抽取+去重+溯源`，不全量上 ontology。

## 3. 怎么叠（不推倒）

```
现有： 错题/笔记/素材 --knowledge_tag--> LearningMap(列表)
增量1： 扫描PDF --koharuOCR--> 同样 knowledge_tag
增量2： LLM 调用 --club-3090本地--> 同样 prompt（mimo→qwen本地）
增量3： 三源 --semantica抽取--> Context Graph --边--> MapFlow 技能树（先修边可解释）
```

* 本地化先只做 `素材解析` 走 Koharu 推理（可选开关，云API仍兜底）
* 大模型先只做 `判分/诊断` 走本地 qwen（与 `mimo` 同接口，灰度 10%）
* 知识图谱先只做 `素材标签去重+冲突提示`（如“分数运算”同名异义），不做全量推理

## 4. 不做清单

* 不做漫画翻译全流程、不做高频量化、不做全量 ontology
* 本地推理失败自动回退云，不阻塞学习主链路

## 5. DSH 好坏判断（增量-2026-08-24）

> 来源：`zhenjia.dev/posts/the-deepseek-of-deepseek-harness`（过度工程是否为自进化而建）

* **好（为未来）：** `Everything is Plugin` + `id/name` 分离实现时空可组合，Agent 可运行时不重启热替 `pruner/loop`，`pre/post-execute Hook→block` 回模型，为 `Agent Self-Evolution` 预埋。
* **坏（对当下）：** 99% 团队一辈子换不了一次 loop，信号又贵（改完得跑全量评测+人判才知好坏），属过度工程。类比搜广推在线学习，Agent 自改 Harness 仍是研究需求。
* **对 xcc 结论：** 不全盘抄 DSH，做到 `Skill/编排/Hook` 2-3 级即可；只抄 `Hook校验` 与 `可声明接口` 思想，热替能力暂不引入。

## 6. 下一步

* koharu：用一本扫描教材跑通 `检测→OCR` spike，产出带坐标的文本块落 `materials`。
* club-3090：1×3090 起 `qwen3.6-27b` 灰度跑 `判分`，TPS>30 且与 `mimo` 一致性>95% 即过。
* semantica：对 100 条素材跑 `抽取+去重`，冲突率与重复标签下降即过。
