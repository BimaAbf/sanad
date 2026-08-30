-- A separate database for the test suite, so `just test` can never truncate
-- the data a developer is looking at in `just dev`.
SELECT 'CREATE DATABASE sanad_test OWNER sanad'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sanad_test') \gexec
