"""uuid_generate_v7, citext, and the identity tables.

DDL transcribed from docs/02-data-model.md §3.

Postgres 16 has no built-in UUIDv7, so it is defined here. v7 is time-ordered,
which matters: these tables are insert-heavy and a random v4 primary key
fragments the B-tree. The implementation follows RFC 9562 §5.7 — 48-bit big-endian
Unix milliseconds, version 7, variant 0b10, random elsewhere.

Revision ID: 0002_identity
Revises: 0001_enum_types
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_identity"
down_revision: str | None = "0001_enum_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_V7 = """
CREATE OR REPLACE FUNCTION uuid_generate_v7()
RETURNS uuid
AS $$
DECLARE
    unix_ts_ms bytea;
    uuid_bytes bytea;
BEGIN
    unix_ts_ms = substring(int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint) from 3);
    -- 10 random bytes; the version and variant nibbles are overwritten below.
    uuid_bytes = unix_ts_ms || gen_random_bytes(10);
    -- version 7 in the high nibble of byte 7
    uuid_bytes = set_byte(uuid_bytes, 6, (b'0111'::bit(4) || get_byte(uuid_bytes, 6)::bit(8) >> 4)::bit(8)::int);
    -- variant 0b10 in the two high bits of byte 9
    uuid_bytes = set_byte(uuid_bytes, 8, (b'10'::bit(2) || get_byte(uuid_bytes, 8)::bit(8) >> 2)::bit(8)::int);
    RETURN encode(uuid_bytes, 'hex')::uuid;
END
$$
LANGUAGE plpgsql
VOLATILE;
"""


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    op.execute(UUID_V7)

    op.execute("""
        CREATE TABLE caregivers (
            id                uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            phone_e164        text UNIQUE,
            email             citext UNIQUE,
            password_hash     text,
            display_name      text NOT NULL DEFAULT '',
            relationship      text,
            governorate       text,
            locale            text NOT NULL DEFAULT 'ar-EG',
            play_pin_hash     text,
            is_active         boolean NOT NULL DEFAULT true,
            last_login_at     timestamptz,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT caregiver_has_identifier
                CHECK (phone_e164 IS NOT NULL OR email IS NOT NULL)
        )
    """)

    op.execute("""
        CREATE TABLE auth_otp (
            id            uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            phone_e164    text NOT NULL,
            code_hash     text NOT NULL,
            attempts      smallint NOT NULL DEFAULT 0,
            consumed_at   timestamptz,
            expires_at    timestamptz NOT NULL,
            created_ip    inet,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_auth_otp_phone_created ON auth_otp (phone_e164, created_at DESC)")

    op.execute("""
        CREATE TABLE refresh_tokens (
            id            uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            caregiver_id  uuid NOT NULL REFERENCES caregivers(id) ON DELETE CASCADE,
            token_hash    text NOT NULL UNIQUE,
            family_id     uuid NOT NULL,
            user_agent    text,
            revoked_at    timestamptz,
            expires_at    timestamptz NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_refresh_tokens_family ON refresh_tokens (family_id)")
    op.execute("CREATE INDEX ix_refresh_tokens_caregiver ON refresh_tokens (caregiver_id)")

    # The kiosk PIN lockout counter. Not in docs/02 §3: the DDL there stores the
    # PIN hash on caregivers but has nowhere to record the 5-attempt lockout, and
    # Redis is the wrong home for something a caregiver would notice surviving a
    # restart. Recorded in docs/adr/002-auth.md.
    op.execute("""
        CREATE TABLE play_pin_attempts (
            caregiver_id     uuid PRIMARY KEY REFERENCES caregivers(id) ON DELETE CASCADE,
            failed_attempts  smallint NOT NULL DEFAULT 0,
            locked_until     timestamptz,
            updated_at       timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS play_pin_attempts")
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute("DROP TABLE IF EXISTS auth_otp")
    op.execute("DROP TABLE IF EXISTS caregivers")
    op.execute("DROP FUNCTION IF EXISTS uuid_generate_v7()")
