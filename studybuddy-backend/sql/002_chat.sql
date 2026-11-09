-- 知了 P2 增量迁移：对话会话与消息表
-- 对应模型：app/models/chat.py
-- 执行：PYTHONPATH=. .venv/bin/python scripts/run_ddl.py sql/002_chat.sql

USE studybuddy;

-- 9. chat_sessions（对话会话：关联发起人 + 学生）
CREATE TABLE IF NOT EXISTS chat_sessions (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  user_id         BIGINT       NOT NULL  COMMENT '发起人(teacher/student)',
  student_id      BIGINT       NOT NULL  COMMENT '关联学生(teacher 发起时为当前孩子)',
  role_at_create  ENUM('teacher','student') NOT NULL  COMMENT '创建时角色，决定工具权限',
  title           VARCHAR(128) NOT NULL DEFAULT '新对话',
  context_summary TEXT         NULL COMMENT '已压缩的较早对话摘要',
  context_summary_message_id BIGINT NULL COMMENT '摘要覆盖到的最后消息 ID',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_user (user_id),
  KEY idx_student (student_id),
  CONSTRAINT fk_chat_session_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_chat_session_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话会话表（P2 agent 化）';

-- 10. chat_messages（对话消息：user / assistant / tool 三种角色）
CREATE TABLE IF NOT EXISTS chat_messages (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  session_id      BIGINT       NOT NULL,
  role            ENUM('user','assistant','tool') NOT NULL,
  content         TEXT         NULL  COMMENT '文本内容（纯文本消息）',
  tool_calls      JSON         NULL  COMMENT 'assistant 的工具调用请求 [{id,name,input}]',
  tool_result     JSON         NULL  COMMENT 'tool 角色的结果摘要 {name,output}',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_session (session_id),
  CONSTRAINT fk_chat_msg_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话消息表（P2 agent 化）';
