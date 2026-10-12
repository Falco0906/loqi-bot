-- OPERATOR ONLY, after explicit provisioning approval, in the isolated cluster.
-- This is a local privilege fixture, NOT production schema or a migration.
-- Execute ONLY through tests.postgres.provision after cluster authorization.
create role loqi_test_owner login inherit nosuperuser nocreatedb nocreaterole nobypassrls;
create role anon nologin noinherit nosuperuser nocreatedb nocreaterole nobypassrls;
create role authenticated nologin noinherit nosuperuser nocreatedb nocreaterole nobypassrls;
create role service_role nologin noinherit nosuperuser nocreatedb nocreaterole nobypassrls;
grant anon, authenticated, service_role, pg_read_all_settings to loqi_test_owner;
-- Database creation/comment are separately composed from validated identifiers
-- by the guarded runner (CREATE DATABASE cannot run in a transaction).
