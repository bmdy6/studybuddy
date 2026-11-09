-- 008: 笔记加 category 字段（学科下细分分类，agent 保存时判断）
-- 英语→词汇/语法/阅读，数学→函数/几何/代数，语文→古诗文/现代文/作文，课外→兴趣/拓展
-- 同时清理废弃的 concept 概念卡历史数据（纯模板空洞，已停用 auto_create_concepts）

ALTER TABLE notes ADD COLUMN category VARCHAR(50) NULL COMMENT '学科下细分分类，agent判断' AFTER subject;

-- 删除历史 concept 概念卡（study_record 保留）
DELETE FROM notes WHERE type = 'concept';
