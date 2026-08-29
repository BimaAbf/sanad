"""`sanad rag` — an inspection harness for the LangChain/LangGraph path.

This exists because the interesting parts of that path are invisible from the
outside. `GET /children/{id}/recommendation` returns one activity and one
sentence; it does not show you which documents were retrieved and at what score,
whether the red-flag screen fired, exactly what bytes went to Groq after
redaction, which guardrail rejected an answer, or whether the reply you are
reading came from the model or from the deterministic engine. Every one of those
is a thing you need to see to trust or debug this layer, and every one of them
is a field in a LangGraph state object that the HTTP response drops.

So each subcommand runs the real code against the real database -- the same
repository, the same embedder, the same compiled graphs the API uses, no
fixtures and no fakes -- and prints every stage.

    sanad rag demo                              seed a child with real history
    sanad rag index  --child ID                 build + embed + write the corpus
    sanad rag search --child ID --query "..."   retrieval only, with scores
    sanad rag next   --child ID                 the recommendation graph
    sanad rag ask    --child ID --message "..." the caregiver chat graph
    sanad rag say    --child ID --heard "..."   the child chat graph
    sanad rag all    --child ID                 index, then one of each

Reading the output: with `AI_LIVE=0` (the default) the gateway makes no network
call and every decision point reports `no_fixture`, so what you are watching is
retrieval plus the deterministic fallback. That is the honest baseline and it is
worth running first -- it tells you whether the DB half works. Set `AI_LIVE=1`
with a `GROQ_API_KEY` and the same commands show the model answering.

Not imported by the API. Nothing in `app/` depends on this module.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import LlmGateway, Provider
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, init_engine
from app.modules.chat.domain import Surface, screen
from app.modules.chat.repository import ChatRepository
from app.modules.chat.service import ChatService
from app.modules.children.consent_gate import ConsentGate
from app.modules.recommendation.repository import RecommendationRepository
from app.modules.recommendation.service import RecommendationService

RULE = "=" * 78
THIN = "-" * 78


def _out(line: str = "") -> None:
    """Print, surviving a Windows console that is not UTF-8.

    Every string in this product is Arabic. A `UnicodeEncodeError` from cp1252
    halfway through a diagnostic is a worse failure than a few replacement
    characters, and it would look like the tool crashed rather than like the
    terminal did.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8", "replace").decode("ascii", "replace"))


def _heading(title: str) -> None:
    _out()
    _out(RULE)
    _out(title)
    _out(RULE)


def _stage(title: str) -> None:
    _out()
    _out(f"-- {title} " + THIN[len(title) + 4 :])


def _json(value: Any, *, limit: int = 2000) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if len(rendered) <= limit:
        return rendered
    return rendered[:limit] + f"\n  ... [{len(rendered) - limit} more characters]"


# --- wiring -----------------------------------------------------------------


def _gateway(settings: Settings) -> LlmGateway:
    """The same gateway `app/core/wiring.py` builds, constructed here directly.

    Importing the wiring would drag in the routers and the FastAPI app for a
    command-line tool that never serves a request.
    """
    return LlmGateway(
        live=settings.ai_live,
        api_key=settings.ai_api_key,
        provider=Provider(settings.ai_provider),
        groq_base_url=settings.groq_base_url,
    )


def _services(session: AsyncSession, settings: Settings) -> tuple[
    RecommendationService, ChatService, LlmGateway
]:
    gateway = _gateway(settings)
    # No Redis. The consent gate reads through to Postgres without it, which is
    # slower and fail-closed -- the right direction for a consent check to fail
    # in, and irrelevant at one query per command.
    consent = ConsentGate(session, None)
    recommendations = RecommendationService(
        repository=RecommendationRepository(session),
        consent=consent,
        gateway=gateway,
    )
    chat = ChatService(
        repository=ChatRepository(session),
        recommendations=recommendations,
        consent=consent,
        gateway=gateway,
    )
    return recommendations, chat, gateway


def _banner(settings: Settings) -> None:
    _out(f"provider   : {settings.ai_provider}")
    _out(f"AI_LIVE    : {int(settings.ai_live)}")
    _out(f"key present: {bool(settings.ai_api_key)}")
    if not settings.ai_live:
        _out()
        _out("AI_LIVE=0 -> no network call. Decision points will report")
        _out("`no_fixture` and the deterministic fallback answers. That is the")
        _out("baseline: it shows whether retrieval and the DB half work.")


async def _session(settings: Settings):  # type: ignore[no-untyped-def]
    from app.core.db import get_session

    init_engine(settings)
    agen = get_session()
    return agen, await anext(agen)


SELECT_OWNER = """
    SELECT caregiver_id::text AS id
    FROM caregiver_child
    WHERE child_id = CAST(:child AS uuid)
    ORDER BY role
    LIMIT 1
"""


async def _caregiver_for(session: AsyncSession, child_id: str) -> str | None:
    """This child's caregiver, from `caregiver_child`.

    Looked up rather than invented. `chat_messages.caregiver_id` is a foreign
    key, so a made-up uuid is a ForeignKeyViolation on the first persisted turn
    — which is exactly what the first run of this harness produced. In the API
    the id comes off the JWT and is always real; here it has to be fetched.
    """
    row = (await session.execute(text(SELECT_OWNER), {"child": child_id})).first()
    return str(row.id) if row is not None else None


# --- demo data --------------------------------------------------------------

SEED_SQL: tuple[str, ...] = (
    """
    INSERT INTO caregivers (id, phone_e164, display_name)
    VALUES (CAST(:caregiver AS uuid), :phone, 'ولي أمر تجريبي')
    """,
    """
    INSERT INTO children (id, display_name, date_of_birth, comms_level,
                          max_choices, wait_time_ms, session_minutes)
    VALUES (CAST(:child AS uuid), :name, DATE '2020-05-01', 'single_words', 2, 8000, 8)
    """,
    """
    INSERT INTO caregiver_child (caregiver_id, child_id, role, accepted_at)
    VALUES (CAST(:caregiver AS uuid), CAST(:child AS uuid), 'owner', now())
    """,
)

#: Every consent the AI path checks. Without `ai_processing` the chat surfaces
#: refuse outright (403) and the recommendation silently skips the judge -- both
#: correct, and both confusing to meet in a demo without being told why.
GRANT_CONSENTS = """
    INSERT INTO consents (child_id, caregiver_id, consent_key, version, status)
    SELECT CAST(:child AS uuid), CAST(:caregiver AS uuid), key, version, 'granted'
    FROM consent_definitions
"""

SELECT_SKILLS_FOR_DEMO = """
    SELECT id::text AS id, code, label_ar
    FROM skills
    WHERE category = 'colors' AND is_active
    ORDER BY intro_order
    LIMIT 4
"""

INSERT_STATE = """
    INSERT INTO skill_states (child_id, skill_id, state, p_known, due_at)
    VALUES (CAST(:child AS uuid), CAST(:skill AS uuid),
            CAST(:state AS mastery_state), :p_known, :due_at)
    ON CONFLICT (child_id, skill_id) DO UPDATE
        SET state = EXCLUDED.state, p_known = EXCLUDED.p_known, due_at = EXCLUDED.due_at
"""

INSERT_SESSION = """
    INSERT INTO play_sessions (id, child_id, started_by, activities_done,
                               correct_count, ended_reason, started_at, ended_at)
    VALUES (CAST(:id AS uuid), CAST(:child AS uuid), CAST(:caregiver AS uuid),
            :done, :correct, :reason, :started, :ended)
"""

INSERT_ATTEMPT = """
    INSERT INTO attempts (session_id, child_id, activity_code, skill_id, result,
                          prompt_level, latency_ms, choice_count, selected_skill_id,
                          client_ts, created_at, idempotency_key)
    VALUES (CAST(:session AS uuid), CAST(:child AS uuid), :activity,
            CAST(:skill AS uuid), CAST(:result AS attempt_result),
            CAST(:prompt AS prompt_level), :latency, 2,
            CAST(NULLIF(:selected, '') AS uuid), :ts, :ts, :key)
"""

INSERT_MILESTONE = """
    INSERT INTO mastery_events (child_id, skill_id, from_state, to_state,
                                p_known_at_event, rule_satisfied, created_at)
    VALUES (CAST(:child AS uuid), CAST(:skill AS uuid),
            CAST(:from_state AS mastery_state), CAST(:to_state AS mastery_state),
            :p_known, true, :at)
"""


async def _seed_demo(session: AsyncSession) -> str:
    """A child with enough history for retrieval to have something to find.

    The shape matters more than the volume. It seeds, deliberately:

      * a REPEATED wrong choice -- the same confusion four times, which is what
        turns a random tap into a pattern `documents.py` will index;
      * a session that ended in FATIGUE, which the judge is told to react to;
      * one lapsed skill, one practising, one mastered, so the candidate engine
        has all three kinds to order.

    A child with twenty random correct attempts would index fine and demonstrate
    nothing.
    """
    child_id = str(uuid.uuid4())
    caregiver_id = str(uuid.uuid4())
    now = dt.datetime.now(dt.UTC)
    params = {
        "child": child_id,
        "caregiver": caregiver_id,
        "phone": f"+2010{uuid.uuid4().hex[:9]}",
        "name": "طفل تجريبي",
    }

    for statement in SEED_SQL:
        await session.execute(text(statement), params)
    await session.execute(text(GRANT_CONSENTS), params)

    skills = list(await session.execute(text(SELECT_SKILLS_FOR_DEMO)))
    if len(skills) < 3:
        raise RuntimeError(
            "the skills catalogue is empty or too small; run `just seed` first"
        )
    target, confusable, mastered = skills[0], skills[1], skills[2]

    states = (
        (target.id, "lapsed", 0.55, now - dt.timedelta(days=2)),
        (confusable.id, "practising", 0.48, now),
        (mastered.id, "mastered", 0.94, now + dt.timedelta(days=9)),
    )
    for skill_id, state, p_known, due_at in states:
        await session.execute(
            text(INSERT_STATE),
            {"child": child_id, "skill": skill_id, "state": state,
             "p_known": p_known, "due_at": due_at},
        )

    # Three sessions, the most recent cut short by fatigue.
    for index, (days_ago, done, correct, reason) in enumerate(
        ((6, 12, 9, "completed"), (3, 14, 10, "completed"), (1, 6, 2, "fatigue"))
    ):
        session_id = str(uuid.uuid4())
        started = now - dt.timedelta(days=days_ago)
        await session.execute(
            text(INSERT_SESSION),
            {"id": session_id, "child": child_id, "caregiver": caregiver_id,
             "done": done, "correct": correct, "reason": reason,
             "started": started, "ended": started + dt.timedelta(minutes=7 - index)},
        )
        for attempt in range(done):
            # The confusion: on the target skill they keep tapping the same
            # wrong picture. Four occurrences clears MIN_CONFUSION_OCCURRENCES.
            wrong = index >= 1 and attempt < 2
            await session.execute(
                text(INSERT_ATTEMPT),
                {
                    "session": session_id,
                    "child": child_id,
                    "activity": f"listen_point:{target.code}",
                    "skill": target.id,
                    "result": "incorrect" if wrong else "correct",
                    "prompt": "independent" if attempt % 3 else "gestural",
                    "latency": 2400 + attempt * 120,
                    "selected": confusable.id if wrong else target.id,
                    "ts": started + dt.timedelta(seconds=30 * attempt),
                    "key": f"{session_id}:{attempt}",
                },
            )

    await session.execute(
        text(INSERT_MILESTONE),
        {"child": child_id, "skill": mastered.id, "from_state": "practising",
         "to_state": "mastered", "p_known": 0.94, "at": now - dt.timedelta(days=8)},
    )
    await session.commit()
    return child_id


# --- stage printers ---------------------------------------------------------


def _print_documents(documents: Sequence[Any]) -> None:
    if not documents:
        _out("  (nothing retrieved — the index is empty, or nothing cleared the")
        _out("   relevance floor. `sanad rag index` first.)")
        return
    for document in documents:
        metadata = getattr(document, "metadata", {})
        score = metadata.get("score")
        kind = metadata.get("kind", "?")
        shown = score if score is not None else "   -"
        _out(f"  [{kind:10}] score={shown}  {document.page_content}")


def _print_sent_payload(gateway: LlmGateway) -> None:
    """What actually went to the provider, after redaction.

    This is the output worth staring at. `sent_payloads` is populated on the
    same path the PII assertions read, so what is printed here is exactly what
    left the process — if a child's name were leaking into a prompt, it would be
    visible in this block and nowhere else.
    """
    if not gateway.sent_payloads:
        _out("  (no request was assembled — the model was never reached)")
        return
    request = gateway.sent_payloads[-1]
    _out(f"  model      : {request.get('model')}")
    messages = request.get("messages", [])
    system = next((m for m in messages if m.get("role") == "system"), None)
    user = next((m for m in messages if m.get("role") == "user"), None)
    if system is not None:
        text_value = str(system.get("content", ""))
        _out(f"  system     : {len(text_value)} chars (frozen prefix)")
    if user is not None:
        _out("  user       :")
        for line in _json(json.loads(str(user.get("content", "{}")))).splitlines():
            _out(f"    {line}")


def _print_screen(message: str, *, next_node: str = "retrieval") -> None:
    """The red-flag pre-filter — the 'detection' half.

    It runs BEFORE the model on both chat surfaces, and a finding at severity 2
    terminates the graph, so the model is never called at all. That ordering is
    the requirement; showing it separately is how you can tell it happened.
    """
    result = screen(message)
    if result.escalate:
        _out(f"  ESCALATE — categories: {', '.join(result.categories)}")
        _out("  the model will NOT be called; the graph ends at `screen`.")
    elif result.findings:
        _out(f"  flagged (below escalation threshold): {', '.join(result.categories)}")
    else:
        _out(f"  clear — no red flag; the graph continues to `{next_node}`.")


# --- commands ---------------------------------------------------------------


async def _run(command: str, args: argparse.Namespace) -> int:
    settings = get_settings()
    _heading(f"sanad rag {command}")
    _banner(settings)

    agen, session = await _session(settings)
    try:
        if command == "demo":
            child_id = await _seed_demo(session)
            _stage("seeded")
            _out(f"  child id: {child_id}")
            _out()
            _out("  Next:")
            # `sys.executable`, not the literal "python". On Windows a bare
            # `python` is whatever is first on PATH -- usually the system
            # interpreter, which has none of this project's dependencies -- so a
            # hint printed with it is a copy-pasteable ModuleNotFoundError.
            _out(f"    {sys.executable} -m app.cli rag all --child {child_id}")
            return 0

        child_id = args.child
        recommendations, chat, gateway = _services(session, settings)
        caregiver_id = await _caregiver_for(session, child_id)

        if command in ("index", "all"):
            _stage("1. build the corpus from the database")
            documents = await recommendations.build_documents(child_id)
            for document in documents:
                _out(f"  [{document.kind.value:10}] {document.doc_id}")
                _out(f"               {document.text_ar}")
            _stage("2. embed and upsert into child_memory (pgvector)")
            indexed = await recommendations.reindex(child_id)
            await session.commit()
            _out(f"  {indexed} documents indexed")

        if command in ("search", "all"):
            query = getattr(args, "query", None) or "إيه أخبار الألوان؟"
            _stage(f"3. retrieval — query: {query}")
            _print_documents(await recommendations.search(child_id, query))

        if command in ("next", "all"):
            _stage("4. the recommendation graph")
            _out("  load_candidates -> retrieve -> judge -> decide")
            recommendation = await recommendations.next_exercise(child_id)
            _out()
            if recommendation is None:
                _out("  no eligible activity for this child")
            else:
                _out(f"  activity : {recommendation.label_ar} ({recommendation.skill_code})")
                _out(f"  kind     : {recommendation.kind}")
                _out(f"  reason   : {recommendation.reason_ar}")
                _out(f"  SOURCE   : {recommendation.source}")
                _out(f"  grounded : {', '.join(recommendation.grounded_in) or '(none)'}")
            _stage("   what was sent to the provider")
            _print_sent_payload(gateway)

        if command in ("ask", "all"):
            message = getattr(args, "message", None) or "هو بقى إيه في الألوان؟"
            _stage(f"5. caregiver chat — {message}")
            _out("  screen -> retrieve -> answer")
            _out()
            _print_screen(message, next_node="retrieve")
            turn = await chat.ask_caregiver(
                child_id=child_id, caregiver_id=caregiver_id or "", message=message
            )
            await session.commit()
            _out()
            _out(f"  OUTCOME  : {turn.outcome.value}")
            _out(f"  reply    : {turn.text_ar}")
            _out(f"  grounded : {', '.join(turn.grounded_in) or '(none)'}")
            _stage("   what was sent to the provider")
            _print_sent_payload(gateway)

        if command in ("say", "all"):
            heard = getattr(args, "heard", None) or "مش عارف"
            _stage(f"6. child chat — heard: {heard}")
            _out("  screen -> classify (closed set of reviewed phrases)")
            _out()
            _print_screen(heard, next_node="classify")
            turn = await chat.ask_child(
                child_id=child_id, caregiver_id=caregiver_id, heard=heard
            )
            await session.commit()
            _out()
            _out(f"  OUTCOME  : {turn.outcome.value}")
            _out(f"  phrase_id: {turn.phrase_id}")
            _out(f"  reply    : {turn.text_ar}")
            _out(f"  audio    : {turn.audio_key}")

        if command == "all":
            _stage("7. transcript now in the database")
            for message_row in await chat.history(child_id, Surface.CAREGIVER, limit=6):
                _out(f"  {message_row.role.value:9} [{message_row.outcome.value:9}] "
                     f"{message_row.text_ar}")
        return 0
    finally:
        await session.close()
        with_suppress = getattr(agen, "aclose", None)
        if with_suppress is not None:
            await agen.aclose()
        await dispose_engine()


def register(subparsers: Any) -> None:
    """Add `sanad rag ...` to the CLI."""
    rag = subparsers.add_parser("rag", help="inspect the LangChain/RAG path")
    inner = rag.add_subparsers(dest="rag_command", required=True)

    demo = inner.add_parser("demo", help="seed a demo child with real history")
    demo.set_defaults(run=lambda args: asyncio.run(_run("demo", args)))

    for name, help_text in (
        ("index", "build, embed and upsert the corpus"),
        ("search", "retrieval only, with scores"),
        ("next", "the recommendation graph"),
        ("ask", "the caregiver chat graph"),
        ("say", "the child chat graph"),
        ("all", "index, then one of each"),
    ):
        parser = inner.add_parser(name, help=help_text)
        parser.add_argument("--child", required=True, help="child uuid")
        parser.add_argument("--query", help="retrieval query (search, all)")
        parser.add_argument("--message", help="caregiver question (ask, all)")
        parser.add_argument("--heard", help="what the child said (say, all)")
        parser.set_defaults(run=lambda args, name=name: asyncio.run(_run(name, args)))


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    root = argparse.ArgumentParser(prog="rag")
    register(root.add_subparsers(dest="command", required=True))
    parsed = root.parse_args()
    sys.exit(parsed.run(parsed))
