-- 021 学习计划字段扩展（U-041）
-- description: 计划完整说明（AI 参考了什么、学生要求什么、为什么这么拆任务）
-- context_refs: 来源上下文引用（历史计划/素材/错题/回顾 id 等），JSON
-- revision: 乐观锁版本号，每次修改 +1，防并发覆盖
-- 注意：MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS，幂等执行靠 scripts/ensure_study_plan_fields.py

USE studybuddy;

ALTER TABLE study_plans
  ADD COLUMN description TEXT NULL COMMENT '计划完整说明：AI 参考、学生要求、拆分理由',
  ADD COLUMN context_refs JSON NULL COMMENT '来源上下文引用（计划/素材/错题 id 等）',
  ADD COLUMN revision INT NOT NULL DEFAULT 1 COMMENT '乐观锁版本号';
