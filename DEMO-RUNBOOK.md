# DEMO-RUNBOOK

Exact commands to run the SANAD demo, in order. Everything here has been
executed on the machine this was written on; where a step has an alternative,
the alternative is the one that was actually used and it says so.

---

## 0. What you need

| Tool | Version | Install |
|---|---|---|
| Node | ≥ 22 | <https://nodejs.org> |
| pnpm | ≥ 11 | `npm i -g pnpm` |
| uv | ≥ 0.11 | <https://docs.astral.sh/uv/> |
| just | ≥ 1.5 | `npm i -g rust-just` |
| PostgreSQL 16 + pgvector, Redis 7 | — | Docker, or the WSL path in §2 |

Python is **not** a prerequisite — `uv` fetches the pinned 3.12 toolchain.

No API key is required. The demo runs with **AI OFF** by default, which is a
supported mode rather than a degraded one: every teaching decision has a
deterministic twin and the session is identical in shape either way. §7 turns
AI ON.

---

## 1. Install dependencies

```bash
just bootstrap
```

That copies `.env.example` → `.env` (never overwriting), installs both
toolchains, syncs the fonts, and — if Docker is running — starts the containers
and migrates. If Docker is not running it will fail at `docker compose`; do
steps 2 and 3 by hand instead:

```bash
pnpm install
```

```bash
uv --directory services/api sync --all-extras
```

```bash
uv run --no-project --python 3.12 tools/bootstrap_env.py
```

---

## 2. Start the datastores

### With Docker

```bash
docker compose up -d --wait
```

```bash
docker compose run --rm minio-init
```

### Without Docker — the path this was built on

Docker Desktop's service could not be started on the build machine without
administrator rights, so PostgreSQL, Redis and MinIO were provisioned inside
WSL2 on **the same ports `.env` already names**, which means no configuration
changes anywhere. Run as root in your WSL distribution:

```bash
sudo apt-get update && sudo apt-get install -y curl ca-certificates gnupg
```

```bash
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
```

```bash
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && apt-get update
```

```bash
apt-get install -y postgresql-16 postgresql-16-pgvector redis-server
```

Then set Postgres to port **55432**, Redis to **56379** with `bind 0.0.0.0 ::`
(the IPv6 half matters — `localhost` resolves to `::1` first from Windows, and a
Redis listening only on IPv4 makes every request wait two seconds and then time
out), create the `sanad` superuser with password `sanad` and the `sanad` and
`sanad_test` databases, and start both.

---

## 3. Migrate and seed

```bash
just migrate
```

```bash
just migrate-test
```

```bash
just seed
```

```bash
just seed-demo
```

Or, to do all of it from a guaranteed-clean database — which is what the demo
should be shown from:

```bash
just db-reset
```

`db-reset` drops the schema, re-applies every migration, loads the 88-skill
curriculum and creates the demo family. It refuses when `SANAD_ENVIRONMENT` is
`production` and when the database is not on localhost.

`seed-demo` prints the caregiver's phone number and the four children's ids.

---

## 4. Start the app

```bash
just up
```

One command, both processes, one colour-coded log stream. If Docker is not
running, start them separately instead:

```bash
uv --directory services/api run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
pnpm --filter @sanad/web dev
```

| URL | What |
|---|---|
| <http://localhost:3000/onboarding> | sign in |
| <http://localhost:3000/children> | the four demo children |
| <http://localhost:3000/play> | the child's session |
| <http://localhost:8000/health> | liveness |
| <http://localhost:8000/docs> | OpenAPI (404 in production) |

---

## 5. Sign in

The demo caregiver is **`01000000000`**. No SMS provider is configured, so the
code is not sent anywhere — it is printed by the API:

```
[NullSms] -> +201000000000 code=123456
```

If the API's output is not in front of you, read it back:

```bash
curl "http://localhost:8000/auth/otp/latest?phone_e164=%2B201000000000"
```

That route exists only when the environment is not `production` **and** the null
SMS provider is configured; it 404s otherwise.

Codes are rate limited to **three per number per hour**. If sign-in stops
working, that is why — wait, or clear the counter:

```bash
uv run --no-project --python 3.12 --with redis python -c "import redis; r=redis.Redis(host='127.0.0.1',port=56379,db=0); [r.delete(k) for k in r.scan_iter('*')]"
```

---

## 6. The demo, in order

1. **`/children`** — four children with different stars, different achievements
   and different assessed bands. Every number is read from that child's own
   rows.
2. **أحمد** — press "يلا نلعب". Counting and matching at low difficulty with
   demonstrations, because his record says demonstrations work.
3. **ليلى** — speaking and matching at difficulty 4 with four choices and no
   demonstration, because hers says she works independently.
4. **سارة** — her session **opens on a tracing activity**, because months of
   accurate tracing make `productive` her strongest measured modality. Draw a
   dot: it fails, with no celebration and no star. Trace the guide: it passes.
5. **Answer something wrong** anywhere. There is no celebration, no star, and
   the next activity comes back at a lower difficulty with the support raised —
   visible in the AI inspector as `RECENT_ERRORS`.
6. **Add a child** from `/children` → "ضيف طفل", complete the thirteen-question
   caregiver assessment, and press "خلصنا". That writes the child's own BKT
   priors and support profile, and the very next session is built from them.
7. **Finish a session** — the child sees stars, achievements and the skills they
   practised. No accuracy, no ratio, no comparison.
8. **"افتح الملف"** — the caregiver report: activities, independent vs
   supported, minutes, stars, what went well, what needs practice, and every
   mastery change. Under it, **"ليه سند عمل كده؟"** — the AI inspector, one card
   per teaching decision, with the estimate it was taken at, the reason codes,
   the guardrail repairs and whether a model or the deterministic rule decided.
9. **Sign out and back in.** Everything is still there.

---

## 7. AI ON

The demo runs AI OFF by default and says so — the inspector prints
`قواعد ثابتة` (deterministic rules) rather than presenting a rule as a model.
To use a real provider:

```bash
# in .env
SANAD_AI_LIVE=1
SANAD_AI_PROVIDER=groq          # or anthropic
SANAD_GROQ_API_KEY=...          # or SANAD_AI_API_KEY for Anthropic
```

Restart the API. Every teaching decision then goes to the provider through
`app/ai/gateway.py`, is validated against `BrainDecision`, passes the same
guardrails, and is recorded with `model_name` set to the provider — which the
inspector shows as `نموذج ذكاء اصطناعي`. A provider that is slow, refuses,
returns invalid JSON or is not there at all falls back to the deterministic
decision and the session continues; there is no configuration in which a
provider outage stops a child's session.

Never commit a key. `.env` is gitignored.

---

## 8. Check it

```bash
just demo-check
```

Rebuilds the database from the migrations, seeds it, starts the API and the web
app if they are not already up, and runs every gate: formatting, lint, types,
the banned-terms lint, the CI guards, the whole backend suite against real
Postgres, the 100 %-branch coverage gate on the deterministic core, the web
lint/type/unit gates, and the critical path walked in a real browser against
this stack. It ends with `SANAD DEMO READY` or `SANAD DEMO NOT READY` and the
exact failing gates.

```bash
just demo-check --skip-e2e
```

Everything except the browser gate, for a fast inner loop. It can never print
READY — a run that did not exercise the critical path does not get to say the
demo is ready.

The browser gate needs Chromium once:

```bash
pnpm --filter @sanad/web exec playwright install chromium
```

---

## 9. Reset

```bash
just db-reset
```

Back to the four seeded children and nothing else. Run it before showing the
demo: the E2E suite creates children, and the demo reads better from a known
state.

```bash
just down
```

Stops the Docker containers. On the WSL path, stop the services inside WSL.
