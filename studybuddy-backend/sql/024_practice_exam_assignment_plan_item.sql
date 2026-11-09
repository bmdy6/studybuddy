-- U-045 学生自练卷关联计划项：exam_assignments 加 plan_item_id 列与索引。
-- ensure 脚本幂等添加（MySQL 5.7 不支持 ADD COLUMN IF NOT EXISTS）。
ALTER TABLE exam_assignments
  ADD COLUMN plan_item_id BIGINT NULL COMMENT '自练卷关联的学习计划项（纯自练为空）';
ALTER TABLE exam_assignments
  ADD INDEX idx_exam_assignments_plan_item (plan_item_id);
