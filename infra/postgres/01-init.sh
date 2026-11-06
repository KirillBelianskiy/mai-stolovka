#!/usr/bin/env bash
set -euo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv users_password USERS_DB_PASSWORD
\getenv menu_password MENU_DB_PASSWORD
\getenv orders_password ORDERS_DB_PASSWORD
\getenv notifications_password NOTIFICATIONS_DB_PASSWORD

CREATE ROLE users_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'users_password';
CREATE ROLE menu_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'menu_password';
CREATE ROLE orders_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'orders_password';
CREATE ROLE notifications_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'notifications_password';
CREATE DATABASE users_db OWNER users_owner;
CREATE DATABASE menu_db OWNER menu_owner;
CREATE DATABASE orders_db OWNER orders_owner;
CREATE DATABASE notifications_db OWNER notifications_owner;
REVOKE ALL ON DATABASE users_db FROM PUBLIC;
REVOKE ALL ON DATABASE menu_db FROM PUBLIC;
REVOKE ALL ON DATABASE orders_db FROM PUBLIC;
REVOKE ALL ON DATABASE notifications_db FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;

\connect users_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
\connect menu_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
\connect orders_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
\connect notifications_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
