-- Reference schema for the attendance system (v2).
-- The source of truth is the SQLAlchemy models in app/models/entities.py;
-- this file documents the intended MySQL DDL. Apply changes to a live
-- database via scripts/migrate.py (database/migrations/*.sql).

CREATE DATABASE IF NOT EXISTS attendance_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE attendance_system;

CREATE TABLE IF NOT EXISTS users (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    name                        VARCHAR(100)  NOT NULL,
    email                       VARCHAR(190)  NOT NULL UNIQUE,
    password_hash               VARCHAR(255)  NOT NULL,
    role                        VARCHAR(7)    NOT NULL DEFAULT 'student',
    verification_code           VARCHAR(500)  NULL,
    verification_code_assigned_at DATETIME     NULL,
    created_at                  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
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

CREATE TABLE IF NOT EXISTS org_settings (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    verification_mode     VARCHAR(8) NOT NULL DEFAULT 'none',
    default_radius_meters INT NOT NULL DEFAULT 75,
    selfie_retention_days INT NOT NULL DEFAULT 90,
    sheets_enabled        TINYINT(1) NOT NULL DEFAULT 0,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS device_registrations (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    token_hash      VARCHAR(64) NOT NULL UNIQUE,
    device_name     VARCHAR(255) NULL,
    os              VARCHAR(50) NULL,
    os_version      VARCHAR(50) NULL,
    browser         VARCHAR(50) NULL,
    browser_version VARCHAR(50) NULL,
    model           VARCHAR(100) NULL,
    screen          VARCHAR(30) NULL,
    language        VARCHAR(10) NULL,
    ip              VARCHAR(45) NULL,
    last_seen_at    DATETIME NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_device_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_device_user (user_id)
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
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    student_id               INT          NOT NULL,
    session_id               INT          NOT NULL,
    device_id                INT          NULL,
    scan_time                DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    latitude                 DECIMAL(10,7) NULL,
    longitude                DECIMAL(10,7) NULL,
    gps_accuracy_meters      DECIMAL(10,2) NULL,
    selfie_path              VARCHAR(255) NULL,
    status                   VARCHAR(20)  NOT NULL DEFAULT 'present',
    method                   VARCHAR(10)  NULL,
    verification_method_used VARCHAR(20)  NULL,
    code_verified            TINYINT(1)   NULL,
    ip                       VARCHAR(45)  NULL,
    isp                      VARCHAR(100) NULL,
    os                       VARCHAR(50)  NULL,
    browser                  VARCHAR(50)  NULL,
    browser_version          VARCHAR(50)  NULL,
    device_model             VARCHAR(100) NULL,
    network_type             VARCHAR(20)  NULL,
    screen                   VARCHAR(30)  NULL,
    anomaly_score            INT          NOT NULL DEFAULT 0,
    anomaly_flags            JSON         NULL,
    reviewed                 TINYINT(1)   NOT NULL DEFAULT 0,
    CONSTRAINT fk_record_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_record_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    CONSTRAINT fk_record_device FOREIGN KEY (device_id) REFERENCES device_registrations(id) ON DELETE SET NULL,
    CONSTRAINT uq_student_session UNIQUE (student_id, session_id),
    INDEX ix_record_session (session_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendance_attempts (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    student_id       INT NOT NULL,
    session_id       INT NULL,
    device_id        INT NULL,
    attempted_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    outcome          VARCHAR(10) NOT NULL,
    fail_reason      VARCHAR(40) NULL,
    method           VARCHAR(10) NULL,
    latitude         DECIMAL(10,7) NULL,
    longitude        DECIMAL(10,7) NULL,
    ip               VARCHAR(45) NULL,
    isp              VARCHAR(100) NULL,
    user_agent       VARCHAR(255) NULL,
    os               VARCHAR(50) NULL,
    browser          VARCHAR(50) NULL,
    browser_version  VARCHAR(50) NULL,
    device_model     VARCHAR(100) NULL,
    network_type     VARCHAR(20) NULL,
    screen           VARCHAR(30) NULL,
    server_timestamps JSON NULL,
    CONSTRAINT fk_attempt_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_attempt_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE SET NULL,
    CONSTRAINT fk_attempt_device FOREIGN KEY (device_id) REFERENCES device_registrations(id) ON DELETE SET NULL,
    INDEX idx_attempt_time (attempted_at),
    INDEX idx_attempt_student (student_id),
    INDEX idx_attempt_session (session_id),
    INDEX idx_attempt_outcome (outcome)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS audit_log (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    actor_id    INT NULL,
    actor_role  VARCHAR(20) NULL,
    action      VARCHAR(50) NOT NULL,
    entity_type VARCHAR(30) NULL,
    entity_id   INT NULL,
    details     JSON NULL,
    ip          VARCHAR(45) NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_actor FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_audit_time (created_at),
    INDEX idx_audit_actor (actor_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sheets_sync (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    session_id      INT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    spreadsheet_id  VARCHAR(120) NULL,
    attempts        INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME NULL,
    last_error      VARCHAR(500) NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_sync_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    INDEX idx_sync_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    VARCHAR(64) PRIMARY KEY,
    applied_at DATETIME NOT NULL
) ENGINE=InnoDB;
