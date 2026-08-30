# 04 — Running it in its deployed shape

From a machine where nothing has ever run, to the stack running the way it runs
when deployed: production settings, real datastores, a real RS256 keypair, no
reloader, two uvicorn workers, a built web app, `/docs` disabled.

**This is not a deployment.** There is no cloud account, no registry and no
remote (BLOCKED.md #4). What it is: the same process invocations the container
images use, against the same configuration, on one machine — which is what
catches configuration-shaped bugs. The image build and the actual deploy are
§8 and §9, and both need things that do not exist yet.

**Read §7 before you start.** There is a ceiling on what can work end to end
today, and it is lower than the component list suggests.

---

## 0. If `just` cannot find a shell

On Windows, `just` runs recipes through `sh` by default, and Git Bash's `sh.exe`
is not on `PATH` unless you put it there — so every recipe failed with:

```
error: recipe `_env` could not be run because just could not find the shell `sh`: program not found
```

Fixed in the justfile with `set windows-shell := ["powershell.exe", "-NoLogo",
"-NoProfile", "-Command"]`. PowerShell 5.1 ships with every Windows 11 install,
so it is the one shell that is always present. If you see that error, your
justfile predates the fix.

Verified for the three properties a task runner actually needs, because
PowerShell gets two of them wrong in other configurations: a native command
exiting non-zero fails the recipe; the remaining lines of that recipe do **not**
run (so a pytest failure cannot be followed by a coverage gate reporting green);
and a command that writes to stderr and exits 0 is **not** treated as a failure
— `uv` and `pnpm` both write progress there.

---

## 1. Start the Docker daemon

Everything downstream needs Postgres, Redis and MinIO, and none of them can
start while the daemon is absent. BLOCKED.md #1 describes this as unrecovered;
the state on this machine is more specific than that:

| | |
|---|---|
| `docker --version` | ✅ 29.1.2 — the CLI is installed |
| `Docker Desktop.exe` | ✅ present in `C:\Program Files\Docker\Docker\` |
| WSL2 | ✅ working; the `docker-desktop` distro exists |
| `com.docker.service` | ❌ **StartMode `Manual`, State `Stopped`** |

That last row is the whole explanation for the missing named pipe. Docker
Desktop starts that service on launch and asks for elevation to do it; if the
elevation prompt was dismissed, Desktop comes up and the pipe never appears —
which is exactly the symptom in BLOCKED.md.

**In an elevated PowerShell** (right-click → Run as administrator):

```powershell
Start-Service com.docker.service
```

Then launch Docker Desktop and wait for the whale to stop animating. Confirm:

```bash
docker version --format '{{.Server.Version}}'
```

A version string means the daemon is answering. If `Start-Service` fails, or
the pipe still does not appear, the next step is *Settings → Troubleshoot →
Reset to factory defaults* in Docker Desktop, and after that a reinstall. Do not
proceed until this prints a version — every step below fails in a way that looks
like a different problem.

---

## 2. Bring up the datastores and run the migrations

```bash
just bootstrap
```

Idempotent: creates `.env` if absent, installs both toolchains, syncs fonts,
starts Postgres/Redis/MinIO/Mailhog and migrates both databases.

> ✅ **This now works, and the risky part is behind you.** Migrations
> `0002`–`0006` had never executed against a real Postgres — only `0001` had —
> and a transcription error in DDL is exactly what a first migration run
> catches. All five applied cleanly on the first attempt, including the monthly
> RANGE partitioning of `events` and the notification dedupe index.

> ⚠️ **One fix was needed to get here.** `docker compose up -d --wait` failed
> with `container sanad-minio-init-1 exited (0)` while every container was
> actually healthy: `--wait` treats *any* container that exits as a failed
> start, including a one-shot init task that exits 0 having done its job. The
> bucket creator now carries `profiles: ["init"]` so it is not part of the
> default `up`, and `bootstrap` runs it explicitly with `docker compose run
> --rm minio-init`, which waits for completion and returns its exit code. That
> broke `just up` too, and the compose-level fix covers both.

If `alembic upgrade head` fails, the failure is a real defect in the migration
and is worth fixing rather than working around. To get back to a clean slate:

```bash
just clean          # docker compose down -v — destroys the volumes
just bootstrap
```

Confirm the schema landed:

```bash
docker exec -it sanad-postgres-1 psql -U sanad -d sanad -c '\dt'
```

You should see 17 relations: thirteen tables — `caregivers`, `auth_otp`,
`refresh_tokens`, `play_pin_attempts`, `caregiver_invites`, `children`,
`consent_definitions`, `consents`, `events`, `progress_rollups`,
`pgee_nudge_state`, `notifications`, `caregiver_notification_prefs` — plus
`alembic_version` and three monthly RANGE partitions of `events`
(`events_2026_08`, `_09`, `_10`).

**There is no `skills`, `items`, `sessions` or `attempts` table.** That is not a
migration failure — see §7.

---

## 3. Check it before you dress it up as production

```bash
just test        # the CI gate; the five integration tests now have a stack to run against
just lint
just guards
```

✅ **Done, and it passed.** `just test`: **863 passed, 0 failed**, then
`COVERAGE GATE PASS: 30 critical file(s) at 100% branch coverage`, 32 tooling
tests, 87 web tests. `tests/integration/test_stack.py` is 8/8 — the five that
had never executed now run. That is `just test` green for the first time in the
project's history, and BLOCKED.md #1 is closed.

Note what is *not* now true: the repository layer is still barely covered
(`progress/repository.py` 0%, `children/` 34%, `identity/` 37%), and the
`ai_cannot_grant` database backstop, the export/erasure foreign-key walk and the
Postgres-level notification dedupe proof are still unwritten. Having a database
made those possible; it did not write them.

---

## 4. Generate the production configuration

```bash
just prod-env
```

Writes `.env.production-local`: `SANAD_ENVIRONMENT=production`, a fresh RS256
keypair, and real values for `SANAD_OTP_PEPPER` and `SANAD_INVITE_SECRET`.

Those four are required because `app.core.config._check_production_secrets`
refuses to start a production process that is still carrying the `local-dev-`
placeholders. The check is correct and should not be softened, so the generator
produces real values instead. It never overwrites: regenerating the keypair
under a running stack invalidates every refresh token already issued.

The keys are PEM, which is multi-line, which a `.env` carries **only inside
double quotes** — unquoted, the reader stops at the first line and pydantic gets
a PEM header and nothing else, and the failure surfaces much later as an
unreadable-key error at the first login. That is the single most error-prone
step here and is why it is a generator rather than an instruction.

`.env.production-local` is gitignored. It is not how a real deployment gets its
secrets — that is a secrets manager, per `docs/07 §4`.

---

## 5. Run it

```bash
just up-prod
```

Builds the web app, then starts both processes in deployed shape:

| | dev (`just up`) | deployed (`just up-prod`) |
|---|---|---|
| config | `.env`, `SANAD_ENVIRONMENT=local` | `.env.production-local`, `=production` |
| API | `uvicorn --reload`, 1 worker | `uvicorn --workers 2`, no reloader, `--host 0.0.0.0` |
| web | `next dev`, compiled on demand | `next start` over a real build |
| `/docs` | served | **404 — disabled in production** |
| refresh cookie | `Secure` off (localhost is http) | `Secure` on |

You get the same single log stream: preflight, containers, migrations, then
every line from both processes with the API's JSON re-rendered and one line per
request, teed to `logs/dev-<timestamp>.log`.

**`/docs` being gone is the point** — it is the first visible confirmation that
you are running production settings and not dev ones with a different label.

---

## 6. Walk through what actually works

`SANAD_SMS_PROVIDER=null` prints the OTP to stdout rather than sending it, so it
appears in the `just up-prod` stream as a `[NullSms] -> +20…` line. That is the
whole auth loop, with no aggregator.

```bash
# 1. request a code — 202 unconditionally, it never says whether the number exists
curl -s -X POST http://localhost:8000/auth/otp/request \
  -H 'Content-Type: application/json' \
  -d '{"phone_e164":"01001234567"}'
```

Read the code off the `[NullSms]` line in the runner's output, then:

> **Two things that will look like bugs and are not.** `/auth/otp/request`
> is capped at 3 per hour per number — a fourth returns 202 like all the others
> and simply never sends, because saying so would be an enumeration oracle. And
> if you paste Arabic into a `curl -d` argument on Windows, the console codepage
> turns it into `????` before curl sees it; send the payload with
> `--data-binary @file.json` written as UTF-8 instead. The API stores Arabic
> correctly — that was checked at the byte level.

```bash
# 2. exchange it for an access token
curl -s -X POST http://localhost:8000/auth/otp/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone_e164":"01001234567","code":"123456"}'
```

```bash
# 3. create a child (TOKEN from the response above)
curl -s -X POST http://localhost:8000/children \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"display_name":"سلمى","date_of_birth":"2022-03-14","comms_level":"single_words"}'
```

```bash
# 4. the consent ledger — the seven definitions migration 0003 seeded
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/children/$CHILD_ID/consents

# 5. progress views over the rollup tables
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/children/$CHILD_ID/progress/today
```

In the browser: <http://localhost:3000/home>, `/play`, `/console`,
`/onboarding`. All thirteen routes build and serve — verified.

Every request appears in the stream with a request id that correlates the
`http_request` line with any `problem_detail` line from the same request.

---

## 7. The ceiling — what will not work, and why

Being clear about this is more useful than a demo that dead-ends. **The
domain logic for all of the below is built and tested; what is missing is the
HTTP surface and the tables underneath it.**

Verified by walking it, not by reading the router list.

| Want to | Today |
|---|---|
| Sign in (OTP → RS256 token → `/me`) | ✅ works |
| Create a child, set consents | ✅ works — and the mandatory-consent gate correctly refuses a child without `data_processing`, `ai_processing` and `terms_not_medical`, in Arabic, as RFC 9457 |
| Store Arabic | ✅ verified at the byte level: `سلمى` lands as `d8b3d984d985d989` |
| **Read progress views** | ❌ **503 `Progress service is not configured`.** `progress/router.py` needs `set_progress_service_factory(...)` and **nothing in `app/` ever calls it** — only tests do. The four `/progress/*` routes are unreachable in any running instance. |
| See a child's name in `GET /me` | ⚠️ returns `""`. An acknowledged stub, not a silent bug: the router hard-codes `display_name=""` with the comment *"filled by the children module once it exists"*. It exists now. The name is correct in the database and via the children routes. |
| Score a pronunciation attempt (`POST /voice/attempt`) | ✅ the endpoint works; there is no audio to play back at it |
| **Run a learning session** | ❌ **no endpoints.** Only four routers are mounted — identity, children, voice, progress. There is no session, tutor or content router. |
| **Run a PGEE assessment** | ❌ same. `/assessment/[id]` renders in the web app; there is no API behind it. |
| Hear anything | ❌ the child app plays static files from a CDN. The CDN is empty — REVIEW-QUEUE #10, and `renderer.py` is not written. |
| Use the clinician console for real | ❌ no auth realm, no editors, no audit log (P14 partial). |
| `just seed` | ❌ exits 1, correctly: there is **no table** to put the curriculum or the item bank in. `seeds/curriculum.py` and `seeds/item_bank.py` are consumed by tests only. |

So the honest description of the ceiling: **identity, children and consent run
deployed-shaped end to end. Progress is built but not wired. Learning and
assessment have no HTTP surface and no persistence.** To lift it, in dependency
order:

1. Wire the progress service — one `set_progress_service_factory` call at
   startup. Cheap, except that `progress/repository.py` is at **0% coverage**
   and every line of it is SQL, so wiring it without tests would put untested
   SQL in the request path.
2. Migrations for the content, assessment, learning and voice tables from
   `docs/02` (`skills`, `items`, `assessments`, `sessions`, `attempts`,
   `tts_cache`).
3. A real `app.cli seed` that loads `seeds/curriculum.py` and
   `seeds/item_bank.py` into them.
4. Routers over the domain modules that already exist and are at 100% branch
   coverage — content, assessment, learning, tutor.
5. P05's LangGraph session and the SSE endpoint (needs the live Postgres from §1
   for `AsyncPostgresSaver`, so it is unblocked the moment §1 is done).
6. Audio: REVIEW-QUEUE #6 then #10, then `renderer.py`.

---

## 8. Building the images

Needs the daemon from §1 and nothing else.

```bash
docker build -f services/api/Dockerfile -t sanad-api:local services/api
docker build -f apps/web/Dockerfile -t sanad-web:local .
```

Neither has ever been built, so treat the first run as a test of the
Dockerfiles rather than a packaging step.

> One defect here has already been found and fixed without a daemon: the web
> Dockerfile copies `.next/standalone` and runs `node apps/web/server.js`, but
> `next.config.mjs` never asked Next to produce a standalone build — so the
> image build would have failed at the `COPY`, reading as a broken Dockerfile
> rather than a missing config key. The config now emits standalone when
> `NEXT_OUTPUT=standalone`, which the Dockerfile's build stage sets, and the
> ordinary `next start` path is unaffected. Verified: `server.js` lands at
> exactly the path the `CMD` expects.

On Windows, do not expect `node .next/standalone/apps/web/server.js` to run
*outside* a container — pnpm's symlinked `node_modules` makes Node's
`realpathSync` fail with `EPERM` unless elevated. That is a Windows filesystem
permission, not a bundle problem; the image runs Linux.

The Trivy scan in `.github/workflows/ci.yml` has never had an image to scan.
Once these build, it will.

---

## 9. Actually deploying

Out of reach today, and the reason is not effort: there is **no cloud account,
no registry, no state backend and no git remote** (BLOCKED.md #4). Not one P15
acceptance criterion has been met, and `terraform validate` has never run — the
provider plugins have never been downloaded.

The order, once an account exists:

1. `terraform validate` — do not trust the module wiring until this passes.
   Module wiring is exactly the kind of thing that reads correctly and does not
   resolve.
2. `terraform plan` against staging, read it in full, then `apply`.
3. Push the two images to a registry; give CI an OIDC role.
4. The three drills P15 requires: the deliberately-broken-deploy rollback, a
   restore drill with real RPO/RTO timings, and the kill switches under load.

Before any of that carries real traffic: `docs/setup/02` §2 — the Groq DPA.
