-- 018: 素材归属、文件层与内容层去重字段
-- PR-06 素材自动识别、自动可用与双层去重后端
--
-- 说明：本文件是正式 DDL 记录。CI/线上幂等重跑由
-- scripts/ensure_material_extraction_columns.py 负责（SHOW COLUMNS / SHOW INDEX 判断后再 ALTER）。
-- MySQL 5.7 兼容：不使用 8.0 专属特性；索引用 KEY idx_ 命名。
-- 不建唯一约束：file_sha256 按“归属范围”判断，跨学生允许同 hash 共存。
-- 不删除正式数据；duplicate_of_material_id 仅用于归一展示与读取，不删记录/文件。

USE studybuddy;

-- 素材归属学生（学生上传=自己；家长上传=指定学生；旧数据=NULL，去重 fallback uploaded_by）
ALTER TABLE materials ADD COLUMN student_id BIGINT NULL,
  ADD CONSTRAINT fk_materials_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE SET NULL;

-- 上传时对原始文件字节算 SHA-256 hex
ALTER TABLE materials ADD COLUMN file_sha256 VARCHAR(64) NULL;

-- 识别成功后对规范化 Markdown 算 SHA-256 hex
ALTER TABLE materials ADD COLUMN content_fingerprint VARCHAR(64) NULL;

-- 高置信非空识别结果自动置 1，Agent 可直接读
ALTER TABLE materials ADD COLUMN auto_ready TINYINT(1) NOT NULL DEFAULT 0;

-- 内容指纹精确命中时指向同归属范围的规范素材（归一，不删记录/文件）
ALTER TABLE materials ADD COLUMN duplicate_of_material_id BIGINT NULL,
  ADD CONSTRAINT fk_materials_duplicate_of FOREIGN KEY (duplicate_of_material_id) REFERENCES materials(id) ON DELETE SET NULL;

-- 去重查询索引（按归属范围查 sha / 内容指纹）
ALTER TABLE materials
  ADD KEY idx_material_student (student_id),
  ADD KEY idx_material_sha (file_sha256),
  ADD KEY idx_material_fingerprint (content_fingerprint);
