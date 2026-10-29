-- Core schema — SQLite.
--
-- The schema is the source of truth here, not the Python models: this file runs
-- before the application does (`flask db-apply`), and `flask generate-models`
-- reads the result back out into app/models/models.py.
--
-- Every statement is written to be safe to re-run, so applying the directory
-- twice is a no-op rather than an error.

CREATE TABLE IF NOT EXISTS app_user (
    id              INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
    username        VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    display_name    VARCHAR(255),
    -- Null for a federated user: there is no local password to check, and a
    -- nullable column says that more clearly than an unusable placeholder hash.
    password_hash   VARCHAR(512),
    role            VARCHAR(32)  NOT NULL DEFAULT 'user',
    is_active       BOOLEAN      NOT NULL DEFAULT 1,
    auth_provider   VARCHAR(32)  NOT NULL DEFAULT 'local',
    external_id     VARCHAR(255),
    last_login_at   DATETIME,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_app_user_username    ON app_user (username);
CREATE INDEX        IF NOT EXISTS ix_app_user_email       ON app_user (email);
CREATE INDEX        IF NOT EXISTS ix_app_user_external_id ON app_user (external_id);

CREATE TABLE IF NOT EXISTS item (
    id            INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
    name          VARCHAR(255) NOT NULL,
    description   TEXT,
    status        VARCHAR(32)  NOT NULL DEFAULT 'active',
    quantity      INTEGER      NOT NULL DEFAULT 0,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_item_status         ON item (status);
CREATE INDEX IF NOT EXISTS ix_item_status_created ON item (status, created_at);
