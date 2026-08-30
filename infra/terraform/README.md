# Terraform

Two deployment targets, one application. docs/08 §2 gives the AWS topology;
docs/12 §Δ3 makes Cloudflare + Hetzner the default and keeps AWS as the
documented scale-up path.

```
modules/
  network         VPC, subnets, NAT, security groups
  ecs             Fargate services: api, web, worker, langfuse
  rds             PostgreSQL 16 + pgvector, Multi-AZ, PITR 7d
  redis           ElastiCache Redis 7, Multi-AZ
  storage-cdn     R2/S3 buckets + CDN; private artefacts vs public media
  secrets         Secrets Manager entries and the IAM to read them
  waf             rate rules, geo, bot control
  observability   OTEL collector, alarms, the five dashboards
  gpu-asr         scale-to-zero GPU for Qwen3-ASR, with Groq Whisper failover
envs/
  staging
  production
```

## ⚠️ Never applied

`terraform apply` has not been run against any account, from this repository or
anywhere else. There is no AWS account, no Cloudflare account and no state
backend configured. What exists is the module structure, the variables and the
resource definitions; `terraform validate` has not been run either, because the
provider plugins have never been downloaded on this machine.

docs/09 P15's acceptance criteria — "`terraform apply` from zero produces a
working staging environment", "a deliberately broken deploy rolls back
automatically within the bake window", "RPO <= 5 min and RTO <= 1 h verified by
an actual restore drill" — are **all outstanding**, and none of them is
satisfiable without an account. They are recorded in PROGRESS.md and
BLOCKED.md rather than approximated.

## Order

1. `secrets` — everything else reads from it, and a resource that starts before
   its secret exists fails in a way that looks like a network problem.
2. `network`
3. `rds`, `redis`, `storage-cdn` — independent of each other
4. `ecs` — needs all of the above
5. `waf`, `observability` — last, because both attach to things above

## State

S3 backend with DynamoDB locking, per docs/08 §8. The backend block is
deliberately left unconfigured in `envs/*/backend.tf.example` rather than
committed: pointing a fresh checkout at someone else's state bucket by default
is how two engineers destroy each other's environment.
