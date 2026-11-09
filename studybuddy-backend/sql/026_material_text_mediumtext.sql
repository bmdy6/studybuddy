-- 026 素材大文本字段扩容：教材整本 Markdown（约 200KB+）超出 TEXT(64KB) 上限
-- text -> mediumtext（16MB），对任何大 PDF 素材同样受益

USE studybuddy;

ALTER TABLE materials
  MODIFY COLUMN raw_text MEDIUMTEXT NULL,
  MODIFY COLUMN recognized_markdown MEDIUMTEXT NULL,
  MODIFY COLUMN confirmed_markdown MEDIUMTEXT NULL;
