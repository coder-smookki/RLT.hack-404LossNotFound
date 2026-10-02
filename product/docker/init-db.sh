#!/bin/sh
set -eu
app_password="$RLT_APP_PASSWORD"
psql --username "$POSTGRES_USER" --dbname postgres -v app_password="$app_password" <<'SQL'
CREATE ROLE rlt_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE rlt_product OWNER rlt_app;
REVOKE ALL ON DATABASE rlt_product FROM PUBLIC;
GRANT CONNECT ON DATABASE rlt_product TO rlt_app;
SQL
