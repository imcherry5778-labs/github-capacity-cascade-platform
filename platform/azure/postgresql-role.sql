-- P6 operator only, private PostgreSQL application database connection.
-- Password is deliberately absent. Use interactive psql \password separately.
\set ON_ERROR_STOP on
BEGIN;
DO $role$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'forgejo') THEN
    CREATE ROLE forgejo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  ELSIF EXISTS (
    SELECT FROM pg_roles WHERE rolname = 'forgejo'
    AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR NOT rolcanlogin)
  ) OR EXISTS (
    SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = 'forgejo'
  ) THEN
    RAISE EXCEPTION 'existing forgejo role is outside the application role contract';
  END IF;
END;
$role$;
SELECT format('GRANT CONNECT ON DATABASE %I TO forgejo', current_database()) \gexec
-- Dedicated application database only. Do not run this on a shared application database.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO forgejo;
COMMIT;
