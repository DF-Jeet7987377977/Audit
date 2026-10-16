-- DreamFolks Call Audit: MySQL database and user. Run once:  sudo mysql < deploy/schema.sql
-- (api/server.py also creates the tables itself on start if they are missing.)
CREATE DATABASE IF NOT EXISTS call_audit CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'callaudit'@'localhost' IDENTIFIED BY 'CHANGE-ME';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX ON call_audit.* TO 'callaudit'@'localhost';
FLUSH PRIVILEGES;

USE call_audit;
CREATE TABLE IF NOT EXISTS audits (
  id INT AUTO_INCREMENT PRIMARY KEY,
  phone VARCHAR(16) NOT NULL UNIQUE,          -- one audit per lead
  auditor_login VARCHAR(255) NOT NULL,
  auditor_name VARCHAR(255),
  lead_id VARCHAR(64), agent VARCHAR(128), category VARCHAR(128), talk_band VARCHAR(32), source VARCHAR(128),
  submitted_at VARCHAR(32) NOT NULL,
  updated_at VARCHAR(32), updated_by VARCHAR(255),
  record LONGTEXT NOT NULL                     -- full audit (lead details + answers) as JSON
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS settings (k VARCHAR(64) PRIMARY KEY, v LONGTEXT NOT NULL, updated_at VARCHAR(32), updated_by VARCHAR(255)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS lead_pool (id INT PRIMARY KEY, content LONGTEXT NOT NULL, rows_count INT, updated_at VARCHAR(32), updated_by VARCHAR(255)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
