-- 027 学习计划沿用：记录新计划的来源旧计划，防重复复制
-- 生产环境通过 scripts/ensure_study_plan_carry_over.py 幂等补齐字段、唯一索引和自引用外键。

ALTER TABLE study_plans
  ADD COLUMN source_plan_id BIGINT NULL COMMENT '沿用旧计划时的来源计划 id',
  ADD UNIQUE KEY uk_study_plans_source_plan (source_plan_id),
  ADD CONSTRAINT fk_study_plans_source_plan
    FOREIGN KEY (source_plan_id) REFERENCES study_plans(id) ON DELETE SET NULL;
