-- Two logins, run once as the PostgreSQL superuser. Replace both passwords.
--
-- qclab_owner owns the tables and runs migrations. Nothing else uses it, and its
-- password stays with whoever holds the database.
-- qclab_app is what the application signs in with. It can read and write rows, so
-- the triggers bind it, and it cannot disable them, drop a table or TRUNCATE.

CREATE ROLE qclab_owner LOGIN PASSWORD 'change-me-owner';
CREATE ROLE qclab_app LOGIN PASSWORD 'change-me-app';
-- template0: on Windows the default template is usually WIN1252 and refuses UTF8.
CREATE DATABASE qclab OWNER qclab_owner ENCODING 'UTF8' TEMPLATE template0;

\connect qclab

REVOKE ALL ON SCHEMA public FROM PUBLIC;
-- The server may hold other databases and logins. They do not get into this one.
REVOKE CONNECT ON DATABASE qclab FROM PUBLIC;
GRANT CONNECT ON DATABASE qclab TO qclab_app;
GRANT USAGE ON SCHEMA public TO qclab_app;
GRANT ALL ON SCHEMA public TO qclab_owner;

-- Everything the owner creates from now on, including every migration.
ALTER DEFAULT PRIVILEGES FOR ROLE qclab_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO qclab_app;
ALTER DEFAULT PRIVILEGES FOR ROLE qclab_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO qclab_app;
