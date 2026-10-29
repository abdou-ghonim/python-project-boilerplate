-- Core schema — Microsoft SQL Server. See sql/README.md.
--
-- Batches are separated by GO, as they are in sqlcmd and SSMS: T-SQL's
-- `IF ... BEGIN ... END` guards contain semicolons of their own, so a semicolon
-- is not a reliable statement terminator here.

IF OBJECT_ID(N'dbo.app_user', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.app_user (
        id              INT             NOT NULL IDENTITY(1,1) PRIMARY KEY,
        username        NVARCHAR(255)   NOT NULL,
        email           NVARCHAR(255)       NULL,
        display_name    NVARCHAR(255)       NULL,
        -- Null for a federated user: there is no local password to check.
        password_hash   NVARCHAR(512)       NULL,
        role            NVARCHAR(32)    NOT NULL CONSTRAINT df_app_user_role
                                                 DEFAULT 'user',
        is_active       BIT             NOT NULL CONSTRAINT df_app_user_is_active
                                                 DEFAULT 1,
        auth_provider   NVARCHAR(32)    NOT NULL CONSTRAINT df_app_user_provider
                                                 DEFAULT 'local',
        external_id     NVARCHAR(255)       NULL,
        last_login_at   DATETIMEOFFSET      NULL,
        created_at      DATETIMEOFFSET  NOT NULL CONSTRAINT df_app_user_created
                                                 DEFAULT SYSDATETIMEOFFSET(),
        updated_at      DATETIMEOFFSET  NOT NULL CONSTRAINT df_app_user_updated
                                                 DEFAULT SYSDATETIMEOFFSET()
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'ix_app_user_username'
                 AND object_id = OBJECT_ID(N'dbo.app_user'))
    CREATE UNIQUE INDEX ix_app_user_username ON dbo.app_user (username);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'ix_app_user_email'
                 AND object_id = OBJECT_ID(N'dbo.app_user'))
    CREATE INDEX ix_app_user_email ON dbo.app_user (email);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'ix_app_user_external_id'
                 AND object_id = OBJECT_ID(N'dbo.app_user'))
    CREATE INDEX ix_app_user_external_id ON dbo.app_user (external_id);
GO

IF OBJECT_ID(N'dbo.item', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.item (
        id            INT             NOT NULL IDENTITY(1,1) PRIMARY KEY,
        name          NVARCHAR(255)   NOT NULL,
        description   NVARCHAR(MAX)       NULL,
        status        NVARCHAR(32)    NOT NULL CONSTRAINT df_item_status
                                               DEFAULT 'active',
        quantity      INT             NOT NULL CONSTRAINT df_item_quantity
                                               DEFAULT 0,
        created_at    DATETIMEOFFSET  NOT NULL CONSTRAINT df_item_created
                                               DEFAULT SYSDATETIMEOFFSET(),
        updated_at    DATETIMEOFFSET  NOT NULL CONSTRAINT df_item_updated
                                               DEFAULT SYSDATETIMEOFFSET()
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'ix_item_status'
                 AND object_id = OBJECT_ID(N'dbo.item'))
    CREATE INDEX ix_item_status ON dbo.item (status);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'ix_item_status_created'
                 AND object_id = OBJECT_ID(N'dbo.item'))
    CREATE INDEX ix_item_status_created ON dbo.item (status, created_at);
GO
