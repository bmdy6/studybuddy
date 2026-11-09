-- 006 素材类型枚举：统一为格式分类（pdf/doc/image/audio/video/other）
-- 原 enum('vocab','grammar','image','other') 改为格式分类，与前端 MATERIAL_TYPES 一致

USE studybuddy;

ALTER TABLE materials
  MODIFY COLUMN type ENUM('pdf','doc','image','audio','video','other') NOT NULL DEFAULT 'other';

-- 把 #19 的 type 从 other 修正为 pdf
UPDATE materials SET type='pdf' WHERE id=19;
