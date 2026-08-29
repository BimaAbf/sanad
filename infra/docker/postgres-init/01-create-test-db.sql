-- A separate database for the test suite, so `just test` can never truncate
-- the data a developer is looking at in `just dev`.
SELECT 'CREATE DATABASE misk_test OWNER misk'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'misk_test') \gexec
