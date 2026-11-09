-- 007 错题导入：exam_batches 表（考试批次，关联多张照片素材）

USE studybuddy;

CREATE TABLE IF NOT EXISTS exam_batches (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  student_id          BIGINT NOT NULL,
  subject             VARCHAR(20) NOT NULL COMMENT '学科',
  exam_name           VARCHAR(100) NOT NULL COMMENT '考试名',
  exam_date           VARCHAR(20) NOT NULL COMMENT '考试日期YYYY-MM-DD',
  photo_material_ids  JSON NULL COMMENT '关联的素材id列表(照片)',
  parsed_pdf_ref      VARCHAR(512) NULL COMMENT 'img2pdf合成的PDF的content_ref',
  folder_name         VARCHAR(200) NULL COMMENT '子文件夹名',
  status              VARCHAR(20) NOT NULL DEFAULT 'uploaded' COMMENT 'uploaded/parsed/graded',
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_batch_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_batch_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
