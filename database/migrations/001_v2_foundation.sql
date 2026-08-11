-- 001_v2_foundation
-- v2: audit layer, device binding, configurable verification, per-session sheet sync.

CREATE TABLE org_settings (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    verification_mode     VARCHAR(8) NOT NULL DEFAULT 'none',
    default_radius_meters INT NOT NULL DEFAULT 75,
    selfie_retention_days INT NOT NULL DEFAULT 90,
    sheets_enabled        TINYINT(1) NOT NULL DEFAULT 0,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

INSERT INTO org_settings (id) VALUES (1);

ALTER TABLE users
    ADD COLUMN verification_code VARCHAR(500) NULL AFTER role,
    ADD COLUMN verification_code_assigned_at DATETIME NULL AFTER verification_code;

CREATE TABLE device_registrations (
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

CREATE TABLE attendance_attempts (
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

ALTER TABLE attendance_records
    MODIFY latitude  DECIMAL(10,7) NULL,
    MODIFY longitude DECIMAL(10,7) NULL,
    ADD COLUMN device_id INT NULL AFTER session_id,
    ADD COLUMN gps_accuracy_meters DECIMAL(10,2) NULL AFTER longitude,
    ADD COLUMN method VARCHAR(10) NULL AFTER status,
    ADD COLUMN verification_method_used VARCHAR(20) NULL AFTER method,
    ADD COLUMN code_verified TINYINT(1) NULL AFTER verification_method_used,
    ADD COLUMN ip VARCHAR(45) NULL AFTER code_verified,
    ADD COLUMN isp VARCHAR(100) NULL AFTER ip,
    ADD COLUMN os VARCHAR(50) NULL AFTER isp,
    ADD COLUMN browser VARCHAR(50) NULL AFTER os,
    ADD COLUMN browser_version VARCHAR(50) NULL AFTER browser,
    ADD COLUMN device_model VARCHAR(100) NULL AFTER browser_version,
    ADD COLUMN network_type VARCHAR(20) NULL AFTER device_model,
    ADD COLUMN screen VARCHAR(30) NULL AFTER network_type,
    ADD COLUMN anomaly_score INT NOT NULL DEFAULT 0 AFTER screen,
    ADD COLUMN anomaly_flags JSON NULL AFTER anomaly_score,
    ADD COLUMN reviewed TINYINT(1) NOT NULL DEFAULT 0 AFTER anomaly_flags,
    ADD CONSTRAINT fk_record_device FOREIGN KEY (device_id) REFERENCES device_registrations(id) ON DELETE SET NULL;

CREATE TABLE audit_log (
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

CREATE TABLE sheets_sync (
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
