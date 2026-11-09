-- 004 个人中心：users 表加 avatar 列（UX P0-1）
-- 存头像 URL，nullable（前端用默认头像兜底）

USE studybuddy;

ALTER TABLE users
  ADD COLUMN avatar VARCHAR(512) NULL COMMENT '头像URL' AFTER display_name;
