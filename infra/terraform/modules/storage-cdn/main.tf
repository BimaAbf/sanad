/**
 * Object storage and the CDN. docs/08 §2, revised by docs/12 §Δ3.
 *
 * Two buckets, and the split is the point: PUBLIC media that a child app plays
 * from a CDN, and PRIVATE artefacts — data exports, consented child audio —
 * that must never be reachable by URL. Putting both in one bucket behind a
 * prefix policy is how a media URL ends up serving an export.
 */

variable "name" { type = string }
variable "kms_key_arn" { type = string }
variable "replica_region" {
  type    = string
  default = "eu-central-1"
}

resource "aws_s3_bucket" "media" {
  bucket = "${var.name}-media"
}

resource "aws_s3_bucket_public_access_block" "media" {
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Reached only through the CDN's origin access control, never directly.
resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket" "private" {
  bucket = "${var.name}-private"
}

resource "aws_s3_bucket_public_access_block" "private" {
  bucket                  = aws_s3_bucket.private.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "private" {
  bucket = aws_s3_bucket.private.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

# docs/04d §5: consented child audio lives 30 days, then goes. The lifecycle
# rule is a BACKSTOP for the application-level deletion, not a replacement — the
# application deletes immediately when consent is absent, and this catches the
# case where it did not run.
resource "aws_s3_bucket_lifecycle_configuration" "private" {
  bucket = aws_s3_bucket.private.id

  rule {
    id     = "child-audio-30-days"
    status = "Enabled"
    filter { prefix = "audio/" }
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 1 }
  }

  rule {
    id     = "exports-7-days"
    status = "Enabled"
    filter { prefix = "exports/" }
    # A data export is a full copy of a child's record sitting in a bucket. It
    # exists to be downloaded once, and then it should stop existing.
    expiration { days = 7 }
  }
}

output "media_bucket" { value = aws_s3_bucket.media.id }
output "private_bucket" { value = aws_s3_bucket.private.id }
