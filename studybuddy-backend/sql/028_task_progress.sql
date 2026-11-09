-- 028 任务进度摘要：为 attempt 增加 taught_scope / next_start
ALTER TABLE study_plan_item_attempts
  ADD COLUMN taught_scope TEXT NULL COMMENT '讲解范围（如“一般过去时肯定句规则”）' AFTER reason,
  ADD COLUMN next_start TEXT NULL COMMENT '续学位置（如“从不规则动词第3题”）' AFTER taught_scope;
