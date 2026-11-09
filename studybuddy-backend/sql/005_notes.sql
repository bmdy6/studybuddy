-- 005 笔记功能：notes 表（学习记录层）
-- 盲区层不存表，从 error_book 聚合（见 note_service.get_blind_spots）
-- concept 概念卡已废弃，type 统一 study_record（见 008 迁移清理历史 concept 数据）

USE studybuddy;

CREATE TABLE IF NOT EXISTS notes (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  student_id      BIGINT NOT NULL,
  type            VARCHAR(20) NOT NULL DEFAULT 'study_record' COMMENT 'study_record=学习记录',
  title           VARCHAR(200) NOT NULL,
  subject         VARCHAR(20) NOT NULL DEFAULT '其他' COMMENT '语文/数学/英语/...',
  content         TEXT NOT NULL,
  knowledge_tags  JSON NULL COMMENT '知识点标签',
  source          VARCHAR(20) NOT NULL DEFAULT '其他' COMMENT '错题讲解/视频学习/做题/其他',
  source_ref      JSON NULL COMMENT '溯源：关联错题id/视频BV号/试卷id',
  status          VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT 'draft=草稿/confirmed=已确认',
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_notes_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_notes_student (student_id),
  INDEX idx_notes_subject (subject),
  INDEX idx_notes_type (type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
