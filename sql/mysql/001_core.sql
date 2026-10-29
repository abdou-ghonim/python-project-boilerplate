-- Core schema — MySQL / MariaDB. See sql/README.md.
--
-- Indexes are declared inside CREATE TABLE rather than as separate statements:
-- MySQL has no `CREATE INDEX IF NOT EXISTS`, so inlining them is what makes
-- re-running this file a no-op.

CREATE TABLE IF NOT EXISTS app_user (
    id              INT          NOT NULL AUTO_INCREMENT,
    username        VARCHAR(255) NOT NULL,
    email           VARCHAR(255)     NULL,
    display_name    VARCHAR(255)     NULL,
    -- Null for a federated user: there is no local password to check.
    password_hash   VARCHAR(512)     NULL,
    role            VARCHAR(32)  NOT NULL DEFAULT 'user',
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    auth_provider   VARCHAR(32)  NOT NULL DEFAULT 'local',
    external_id     VARCHAR(255)     NULL,
    last_login_at   DATETIME         NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY ix_app_user_username (username),
    KEY ix_app_user_email (email),
    KEY ix_app_user_external_id (external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item (
    id            INT          NOT NULL AUTO_INCREMENT,
    name          VARCHAR(255) NOT NULL,
    description   TEXT             NULL,
    status        VARCHAR(32)  NOT NULL DEFAULT 'active',
    quantity      INT          NOT NULL DEFAULT 0,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_item_status (status),
    KEY ix_item_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
