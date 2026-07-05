-- Runs once on first initialization of the postgres volume
-- (docker-entrypoint-initdb.d). GlitchTip needs its own database;
-- the image's migrations create the schema on first start.
CREATE DATABASE glitchtip;
