"""strip_stale_thoughts: drop thought text & empty parts on all model turns; preserve thought_signature verbatim."""

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.coach.coaching.model_callbacks import strip_stale_thoughts

SIG = b"sig"


def _user(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def _model(*parts: types.Part) -> types.Content:
    return types.Content(role="model", parts=list(parts))


def _call(name: str, sig: bytes = SIG) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args={}), thought_signature=sig)


def _resp(name: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(name=name, response={"result": "ok"}))],
    )


def _run(contents: list[types.Content]) -> list[types.Content]:
    req = LlmRequest(contents=contents)
    assert strip_stale_thoughts(None, req) is None
    return req.contents


def test_strip_stale_thoughts_drops_thought_and_empty_parts_while_preserving_signatures():
    from running_coach.coach.coaching.quick_actions import SYNTHETIC_THOUGHT_SIGNATURE

    out = _run([
        _user("audit my plan"),
        _model(
            types.Part(text="thinking...", thought=True),
            _call("fetch_plan_audit_data", sig=SYNTHETIC_THOUGHT_SIGNATURE),
            _call("load_skill", sig=SIG),
        ),
        _resp("fetch_plan_audit_data"),
        _model(types.Part(text="### Assessment", thought_signature=SIG), types.Part(text="", thought_signature=SIG)),
        _user("yes update it"),
        # Active turn Call 2: thought text and trailing empty SSE part are stripped, real FC signature stays!
        _model(
            types.Part(text="active turn thought...", thought=True),
            _call("stage_workout_changes", sig=SIG),
            types.Part(text=""),
        ),
        _resp("stage_workout_changes"),
    ])
    assert len(out) == 7
    first_model, second_model, active_model = out[1], out[3], out[5]
    assert [p.function_call.name for p in first_model.parts] == ["fetch_plan_audit_data", "load_skill"]
    # Both synthetic and real thought signatures stay verbatim on retained parts (0 billable input tokens;
    # prevents completed-turn prefix-cache invalidation on follow-up turns).
    assert first_model.parts[0].thought_signature == SYNTHETIC_THOUGHT_SIGNATURE
    assert first_model.parts[1].thought_signature == SIG
    assert all(not p.thought for p in first_model.parts + second_model.parts + active_model.parts)
    assert [p.text for p in second_model.parts] == ["### Assessment"]  # empty signed part dropped
    assert second_model.parts[0].thought_signature == SIG
    # Active turn: thought + trailing empty part dropped, active functionCall signature preserved!
    assert len(active_model.parts) == 1
    assert active_model.parts[0].function_call.name == "stage_workout_changes"
    assert active_model.parts[0].thought_signature == SIG


def test_thinking_policy_is_strictly_state_driven():
    from running_coach.coach.coaching.model_callbacks import thinking_for
    from running_coach.coach.coaching.quick_actions import PLAN_INTAKE_STATE_KEY, SYNTHESIS_GUARD_STATE_KEY

    # All warm chat turns (with or without staged state) keep uniform MEDIUM thinking so prefix cache never busts.
    staged_state = {"staged_workout_changes": {"staged_id": "s-1", "changes": [{"kind": "workout"}]}}
    for state in ({}, staged_state, {SYNTHESIS_GUARD_STATE_KEY: "inv-synth"}):
        cfg, reason = thinking_for(state, "inv-synth")
        assert cfg.thinking_level == types.ThinkingLevel.MEDIUM and cfg.include_thoughts is True
        assert reason == "default"

    # Only the cold Build Plan intake opener uses LOW thinking.
    intake_state = {PLAN_INTAKE_STATE_KEY: "inv-intake"}
    cfg_in, reason_in = thinking_for(intake_state, "inv-intake")
    assert cfg_in.thinking_level == types.ThinkingLevel.LOW and reason_in == "intake"
    cfg_later, reason_later = thinking_for(intake_state, "inv-later")
    assert cfg_later.thinking_level == types.ThinkingLevel.MEDIUM and reason_later == "default"


def test_internal_tools_are_hidden_from_llm_declarations_and_plan_builder_expands_in_code():
    from google.adk.models.llm_response import LlmResponse
    from types import SimpleNamespace

    from running_coach.coach.coaching.model_callbacks import after_coach_model, hide_internal_tools

    def make_req(contents: list[types.Content]) -> LlmRequest:
        decls = [
            types.FunctionDeclaration(name=n)
            for n in (
                "load_skill",
                "fetch_plan_context",
                "fetch_trend_data",
                "stage_training_plan",
                "apply_training_plan",
                "apply_staged_changes",
            )
        ]
        decls.append(
            types.FunctionDeclaration(
                name="get_weather",
                parameters_json_schema={
                    "type": "object",
                    "title": "get_weatherParams",
                    "properties": {
                        "title": {"type": "string", "title": "Title", "default": None, "nullable": True},
                        "days": {"type": "integer", "title": "Days", "default": 3},
                    },
                },
            )
        )
        r = LlmRequest(
            contents=contents,
            config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=decls)]),
        )
        r.tools_dict.update({d.name: d for d in decls})
        return r

    # 1. Plain chat: internal tools and stage_training_plan hidden; apply_staged_changes stays stably declared
    #    so staging/applying workouts never mutates tool definitions or busts Gemini's prefix cache;
    #    Pydantic `title` and null `default` metadata stripped while preserving property key `"title"` and `default: 3`.
    req = make_req([_user("hi")])
    hide_internal_tools(None, req)
    by_name = {d.name: d for t in req.config.tools for d in t.function_declarations}
    assert set(by_name) == {"load_skill", "apply_staged_changes", "get_weather"}
    assert by_name["get_weather"].parameters_json_schema == {
        "type": "object",
        "properties": {
            "title": {"type": "string", "nullable": True},
            "days": {"type": "integer", "default": 3},
        },
    }
    assert {
        "fetch_plan_context",
        "fetch_trend_data",
        "apply_training_plan",
        "stage_training_plan",
        "apply_staged_changes",
    } <= set(req.tools_dict)

    # 2. Current turn loaded plan-builder -> stage_training_plan is declared for Step 2.
    plan_turn = make_req([
        _user("yes, build the plan"),
        _model(types.Part(function_call=types.FunctionCall(name="load_skill", args={"skill_name": "plan-builder"}))),
        _resp("load_skill"),
    ])
    hide_internal_tools(SimpleNamespace(state={}), plan_turn)
    assert "stage_training_plan" in {d.name for t in plan_turn.config.tools for d in t.function_declarations}

    # 3. Follow-up turn while staged_training_plan is unapplied -> stage_training_plan stays declared;
    #    once applied_training_plan marks that staged_id done -> hidden again on subsequent turns.
    followup_unapplied = make_req([_user("make week 5 easier")])
    hide_internal_tools(SimpleNamespace(state={"staged_training_plan": {"staged_id": "plan-1"}}), followup_unapplied)
    assert "stage_training_plan" in {d.name for t in followup_unapplied.config.tools for d in t.function_declarations}

    followup_applied = make_req([_user("what shoes should I buy?")])
    hide_internal_tools(
        SimpleNamespace(state={
            "staged_training_plan": {"staged_id": "plan-1"},
            "applied_training_plan": {"staged_id": "plan-1", "done": True},
        }),
        followup_applied,
    )
    assert "stage_training_plan" not in {d.name for t in followup_applied.config.tools for d in t.function_declarations}

    ctx = SimpleNamespace(state={}, invocation_id="inv-1")
    resp = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(
            name="load_skill",
            args={"skill_name": "plan-builder", "start_date": "2026-11-30", "mode": "overhaul"},
        ))
    ]))
    shaped = after_coach_model(ctx, resp)
    calls = [(p.function_call.name, dict(p.function_call.args or {})) for p in shaped.content.parts]
    assert calls == [
        ("load_skill", {"skill_name": "plan-builder", "start_date": "2026-11-30", "mode": "overhaul"}),
        ("fetch_plan_context", {"start_date": "2026-11-30", "mode": "overhaul"}),
    ]

    # 4. Turn 2/3 after plan-builder:intake: active fetch_plan_context unhides stage_training_plan,
    #    uses MEDIUM thinking ("default") for synthesis/revisions, and reuses plan_context_cache even after staging.
    from running_coach.coach.coaching.model_callbacks import thinking_for
    from running_coach.shared.dates import get_today_date, iso_date

    intake_turn2 = make_req([
        _user("I'd like to build a new training plan"),
        _model(_call("fetch_plan_context")),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="fetch_plan_context", response={"result": "PLAN CONTEXT (new): 2026-11-30 → 2027-02-21"}
        ))]),
        _model(types.Part(text="How many days can you run?")),
        _user("4 days a week, Sunday long run"),
    ])
    hide_internal_tools(SimpleNamespace(state={}), intake_turn2)
    assert "stage_training_plan" in {d.name for t in intake_turn2.config.tools for d in t.function_declarations}
    pb_cfg, pb_reason = thinking_for({})
    assert pb_cfg.thinking_level == types.ThinkingLevel.MEDIUM and pb_reason == "default"

    edit_cfg, edit_reason = thinking_for({"staged_training_plan": {"staged_id": "plan-1"}})
    assert edit_cfg.thinking_level == types.ThinkingLevel.MEDIUM and edit_reason == "default"

    today_iso = iso_date(get_today_date())
    cached_ctx = SimpleNamespace(
        state={
            "plan_context_cache": {
                "start_date": "2026-11-30",
                "end_date": "2027-02-21",
                "mode": "overhaul",
                "today": today_iso,
            }
        },
        invocation_id="inv-2",
    )
    same_window = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(
            name="load_skill",
            args={"skill_name": "plan-builder", "start_date": "2026-11-30", "end_date": "2027-02-21", "mode": "overhaul"},
        ))
    ]))
    assert after_coach_model(cached_ctx, same_window) is None  # no duplicate fetch_plan_context!
    different_mode = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(
            name="load_skill",
            args={"skill_name": "plan-builder", "start_date": "2026-11-30", "end_date": "2027-02-21", "mode": "new"},
        ))
    ]))
    assert len(after_coach_model(cached_ctx, different_mode).content.parts) == 2  # mode changed -> re-fetch


def test_plan_builder_expansion_stays_contiguous_across_sse_trailing_empty_part():
    import asyncio
    from types import SimpleNamespace
    from google.adk.utils.streaming_utils import StreamingResponseAggregator

    from running_coach.coach.coaching.model_callbacks import after_coach_model

    async def aggregate_sse_chunks(chunks: list[types.GenerateContentResponse]):
        agg = StreamingResponseAggregator()
        for chunk in chunks:
            async for _ in agg.process_response(chunk):
                pass
        return agg.close()

    # Mirrors gemini-4-argon SSE stream: thought chunk -> signed load_skill FC chunk -> STOP chunk with Part(text="").
    chunks = [
        types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[
                types.Part(text="Planning block...", thought=True),
            ]))]
        ),
        types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id="call_1",
                        name="load_skill",
                        args={"skill_name": "plan-builder", "start_date": "2026-11-16", "mode": "new"},
                    ),
                    thought_signature=SIG,
                ),
            ]))]
        ),
        types.GenerateContentResponse(
            candidates=[types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text="")]),
                finish_reason=types.FinishReason.STOP,
            )]
        ),
    ]
    aggregated = asyncio.run(aggregate_sse_chunks(chunks))
    assert aggregated.content.parts[-1].text == "" and aggregated.content.parts[-1].function_call is None

    shaped = after_coach_model(SimpleNamespace(state={}, invocation_id="inv-sse"), aggregated)
    parts = shaped.content.parts
    fc_indices = [i for i, p in enumerate(parts) if p.function_call]
    assert fc_indices == [1, 2]  # contiguous: never split by the trailing Part(text="") at index 3
    assert [(parts[i].function_call.name, parts[i].thought_signature) for i in fc_indices] == [
        ("load_skill", SIG),
        ("fetch_plan_context", None),
    ]



def test_create_session_does_not_append_greeting_event(monkeypatch):
    import asyncio
    from google.adk.integrations.firestore.firestore_session_service import FirestoreSessionService
    from google.adk.sessions.session import Session
    from running_coach.integrations.session_service import CoachFirestoreSessionService

    svc = object.__new__(CoachFirestoreSessionService)
    appended = []

    async def fake_super_create(self, *, app_name, user_id, state=None, session_id=None):
        return Session(id=session_id or "s1", app_name=app_name, user_id=user_id, state=state or {})

    async def fake_append(session, event):
        appended.append(event)
        return event

    monkeypatch.setattr(FirestoreSessionService, "create_session", fake_super_create)
    monkeypatch.setattr(svc, "append_event", fake_append)

    session = asyncio.run(svc.create_session(app_name="running_coach", user_id="u1", state={"__k": "v"}))
    assert session.state == {"__k": "v"}
    assert appended == [] and session.events == []


def test_get_runner_tp_cookie_singleflights_concurrent_kms_decrypts(monkeypatch):
    import asyncio
    import base64
    from types import SimpleNamespace

    from running_coach.integrations.trainingpeaks import credentials

    credentials.clear_tp_credential_cache()
    reads, decrypts = 0, 0

    async def fake_read(collection: str, doc_id: str):
        nonlocal reads
        reads += 1
        await asyncio.sleep(0.01)
        return {"cookie_ciphertext": base64.b64encode(b"cipher-bytes").decode("ascii")}

    def fake_decrypt(request: dict):
        nonlocal decrypts
        decrypts += 1
        return SimpleNamespace(plaintext=b"tp-secret-cookie")

    monkeypatch.setattr(credentials, "read_document", fake_read)
    monkeypatch.setattr(credentials, "tp_cookie_kms_key", lambda: "projects/p/locations/l/keyRings/r/cryptoKeys/k")
    monkeypatch.setattr(credentials, "_get_kms_client", lambda: SimpleNamespace(decrypt=fake_decrypt))

    async def run():
        return await asyncio.gather(*(credentials.get_runner_tp_cookie("runner_1") for _ in range(5)))

    try:
        cookies = asyncio.run(run())
        assert cookies == ["tp-secret-cookie"] * 5
        assert reads == 1 and decrypts == 1
    finally:
        credentials.clear_tp_credential_cache()


def test_warm_staging_retries_keep_medium_thinking_to_preserve_prefix_cache():
    from types import SimpleNamespace
    from running_coach.coach.coaching.model_callbacks import apply_thinking_policy

    ctx = SimpleNamespace(state={}, invocation_id="inv-warm")
    history = [
        _user("Audit my plan for the next 4 weeks"),
        _model(types.Part(text="### Assessment\n- ...\n### Recommendations\n- Nov 18: E 10 -> E 8")),
    ]
    for prompt in (
        "ok, stage the changes",
        "Stage the full set of changes",
        "Apply the recommendations",
    ):
        req = LlmRequest(contents=[*history, _user(prompt)])
        assert apply_thinking_policy(ctx, req) is None
        assert req.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM, prompt

    # Validation retries after stage_workout_changes / stage_training_plan return staged: 0 keep MEDIUM
    # thinking so Vertex's token-0 thinking level never flips mid-turn and invalidates the warm prefix cache.
    retry_req = LlmRequest(contents=[
        _user("Swap Thursday to a custom pyramid session"),
        _model(_call("stage_workout_changes")),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="stage_workout_changes", response={"result": '{"staged": 0, "needs_structure": [{}]}'}
        ))]),
    ])
    assert apply_thinking_policy(ctx, retry_req) is None
    assert retry_req.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM

    pb_retry_req = LlmRequest(contents=[
        _user("Build my marathon plan"),
        _model(_call("stage_training_plan")),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="stage_training_plan", response={"result": '{"staged": 0, "errors": [{"code": "Zz 5"}]}'}
        ))]),
    ])
    assert apply_thinking_policy(ctx, pb_retry_req) is None
    assert pb_retry_req.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM


def test_create_session_stamps_initial_expire_at(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from google.adk.integrations.firestore.firestore_session_service import FirestoreSessionService
    from google.adk.sessions.session import Session
    from running_coach.integrations.session_service import EXPIRE_AT_FIELD, CoachFirestoreSessionService

    updates: list[tuple[str, dict]] = []

    class FakeDocRef:
        def __init__(self, doc_id: str):
            self.doc_id = doc_id

        async def update(self, payload: dict):
            updates.append((self.doc_id, payload))

    svc = object.__new__(CoachFirestoreSessionService)
    svc.client = SimpleNamespace()
    monkeypatch.setattr(svc, "_get_sessions_ref", lambda app_name, user_id: SimpleNamespace(document=FakeDocRef))

    async def fake_super_create(self, *, app_name, user_id, state=None, session_id=None):
        return Session(id=session_id or "s-empty", app_name=app_name, user_id=user_id, state=state or {})

    monkeypatch.setattr(FirestoreSessionService, "create_session", fake_super_create)

    session = asyncio.run(svc.create_session(app_name="running_coach", user_id="web_u1"))
    assert session.id == "s-empty"
    assert len(updates) == 1
    assert updates[0][0] == "s-empty"
    assert EXPIRE_AT_FIELD in updates[0][1]


def test_firestore_subcollection_writes_skip_phantom_eval_profiles(monkeypatch):
    import asyncio
    from running_coach.integrations import firestore as fs

    fs.clear_known_runners_cache()
    persisted_users = {"cyrille_visser": {"firstname": "Cyrille", "lastname": "Visser"}}
    writes: list[tuple[str, str, dict]] = []
    reads: list[tuple[str, str]] = []

    async def fake_read(collection_path: str, doc_id: str):
        reads.append((collection_path, doc_id))
        if collection_path == "users":
            return persisted_users.get(doc_id)
        return None

    async def fake_write(collection_path: str, doc_id: str, data: dict):
        writes.append((collection_path, doc_id, data))

    monkeypatch.setattr(fs, "read_document", fake_read)
    monkeypatch.setattr(fs, "write_document", fake_write)

    try:
        # 1. Synthetic eval profile ("alex_runner") has no `users/alex_runner` doc -> all subcollection writes blocked.
        asyncio.run(fs.save_training_record("alex_runner", "w1", {"date": "2026-11-12"}))
        asyncio.run(fs.save_volume_history("alex_runner", {"weeks": []}))
        asyncio.run(fs.save_race_projection("alex_runner", {"version": 1}))
        assert writes == []

        # 2. Real persisted runner ("cyrille_visser") -> verified once, cached in-memory, and writes proceed.
        asyncio.run(fs.save_training_record("cyrille_visser", "w1", {"date": "2026-11-12"}))
        asyncio.run(fs.save_volume_history("cyrille_visser", {"weeks": []}))
        asyncio.run(fs.save_race_projection("cyrille_visser", {"version": 1}))
        assert [w[:2] for w in writes] == [
            ("users/cyrille_visser/training_log", "w1"),
            ("users/cyrille_visser/cache", "volume_history"),
            ("users/cyrille_visser/cache", "race_projection"),
        ]
        assert reads.count(("users", "cyrille_visser")) == 1
    finally:
        fs.clear_known_runners_cache()


def test_after_coach_model_records_thoughts_and_cached_tokens_on_span(monkeypatch):
    from types import SimpleNamespace
    from google.adk.models.llm_response import LlmResponse
    from opentelemetry import trace
    from running_coach.coach.coaching.model_callbacks import after_coach_model

    attrs: dict = {}

    class FakeSpan:
        def set_attribute(self, key: str, value) -> None:
            attrs[key] = value

    monkeypatch.setattr(trace, "get_current_span", lambda: FakeSpan())
    ctx = SimpleNamespace(state={}, invocation_id="inv-usage")

    # Partial streaming chunks do not record usage prematurely.
    partial_resp = LlmResponse(
        partial=True,
        content=types.Content(role="model", parts=[types.Part(text="hi")]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            thoughts_token_count=99, cached_content_token_count=3500
        ),
    )
    after_coach_model(ctx, partial_resp)
    assert attrs == {}

    # Finalized response records both thoughts_tokens and cached_tokens.
    final_resp = LlmResponse(
        partial=False,
        content=types.Content(role="model", parts=[types.Part(text="### Assessment")]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            thoughts_token_count=215, cached_content_token_count=3860
        ),
    )
    after_coach_model(ctx, final_resp)
    assert attrs == {"coach.thoughts_tokens": 215, "coach.cached_tokens": 3860}


