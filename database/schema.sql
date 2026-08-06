-- Reference schema for the attendance system.
-- The source of truth is the SQLAlchemy models in app/models/entities.py;
-- this file documents the intended MySQL DDL and can be used as a migration baseline.

CREATE DATABASE IF NOT EXISTS attendance_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE attendance_system;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100)  NOT NULL,
    email         VARCHAR(190)  NOT NULL UNIQUE,
    password_hash VARCHAR(255)  NOT NULL,
    role          ENUM('admin','student') NOT NULL DEFAULT 'student',
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_users_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS auth_tokens (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT          NOT NULL,
    token      VARCHAR(64)  NOT NULL UNIQUE,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME     NOT NULL,
    CONSTRAINT fk_token_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token_token (token)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    subject        VARCHAR(120) NOT NULL,
    faculty        VARCHAR(120) NOT NULL,
    date           DATE         NOT NULL,
    start_time     TIME         NOT NULL,
    end_time       TIME         NOT NULL,
    latitude       DECIMAL(10,7) NOT NULL,
    longitude      DECIMAL(10,7) NOT NULL,
    radius_meters  INT          NOT NULL DEFAULT 75,
    qr_token       VARCHAR(64)  NOT NULL UNIQUE,
    expires_at     DATETIME     NOT NULL,
    created_by     INT          NOT NULL,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_session_creator FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_session_date (date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendance_records (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT          NOT NULL,
    session_id INT          NOT NULL,
    scan_time  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    latitude   DECIMAL(10,7) NOT NULL,
    longitude  DECIMAL(10,7) NOT NULL,
    status     VARCHAR(20)  NOT NULL DEFAULT 'present',
    CONSTRAINT fk_record_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_record_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    CONSTRAINT uq_student_session UNIQUE (student_id, session_id),
    INDEX ix_record_session (session_id)
) ENGINE=InnoDB;
