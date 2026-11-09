-- 009: 删除 notes.related_notes 死字段
-- related_notes 原是 concept 概念卡的关联链路，concept 废弃后（见 008）无任何业务逻辑
-- 写入有效值：agent save_note 不传、update_note 不改，仅 REST 手动 POST 能填（无场景）。
-- 彻底删除字段清理死代码。source_ref 保留（错题讲解→笔记关联闭环用）。

SET @has_related_notes := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'notes'
    AND COLUMN_NAME = 'related_notes'
);
SET @drop_related_notes_sql := IF(
  @has_related_notes > 0,
  'ALTER TABLE notes DROP COLUMN related_notes',
  'SELECT 1'
);
PREPARE drop_related_notes_stmt FROM @drop_related_notes_sql;
EXECUTE drop_related_notes_stmt;
DEALLOCATE PREPARE drop_related_notes_stmt;
