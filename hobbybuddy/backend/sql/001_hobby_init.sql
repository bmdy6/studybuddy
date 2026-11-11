-- 趣爱好 (hobbybuddy) 数据库初始化脚本
-- 数据库：MySQL 5.7（端口 3307，独立库 hobbybuddy）
-- 字符集：utf8mb4 / utf8mb4_unicode_ci  存储引擎：InnoDB
-- 红线：必备 id/created_at/updated_at；不用外键级联。
-- v1 = 纯资源推荐对话，只建 users 表；练习/作品不落库（表结构 v2 需要时再启用）。

CREATE DATABASE IF NOT EXISTS hobbybuddy
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE hobbybuddy;

-- 1. users（兴趣空间用户：学习者本人，单一角色）
CREATE TABLE IF NOT EXISTS users (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  username        VARCHAR(64)  NOT NULL,
  password_hash   VARCHAR(255) NOT NULL  COMMENT 'bcrypt 哈希',
  display_name    VARCHAR(64)  NULL,
  avatar          VARCHAR(512) NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='兴趣空间用户表';
