"""strip_stale_thoughts: completed turns lose thoughts/signatures; the current turn keeps them."""

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


def test_completed_turns_lose_thoughts_and_signatures():
    out = _run([
        _user("audit my plan"),
        _model(types.Part(text="thinking...", thought=True), _call("fetch_plan_audit_data")),
        _resp("fetch_plan_audit_data"),
        _model(types.Part(text="### Assessment", thought_signature=SIG), types.Part(text="", thought_signature=SIG)),
        _user("yes update it"),
    ])
    assert len(out) == 5
    first_model, second_model = out[1], out[3]
    assert [p.function_call.name for p in first_model.parts] == ["fetch_plan_audit_data"]
    assert all(p.thought_signature is None and not p.thought for p in first_model.parts + second_model.parts)
    assert [p.text for p in second_model.parts] == ["### Assessment"]  # empty signed part dropped


def test_followup_confirmation_uses_low_thinking_across_the_entire_turn():
    from running_coach.coach.coaching.model_callbacks import thinking_for

    history = [
        _user("When should I start strength training? Marathon was Nov 1st."),
        _model(types.Part(text="Start mobility tomorrow; if you'd like I can update your S&C sessions.")),
    ]
    # Step 1 of Turn 2: runner replies "yes update it" -> LOW thinking ("confirmation") + include_thoughts.
    step1 = LlmRequest(contents=[*history, _user("yes update it")])
    cfg1, reason1 = thinking_for({}, step1)
    assert cfg1.thinking_level == types.ThinkingLevel.LOW and cfg1.include_thoughts is True
    assert reason1 == "confirmation"

    # Step 2 of Turn 2 (after load_skill("workout-creator") returns): still LOW thinking on the staging call!
    step2 = LlmRequest(contents=[
        *history,
        _user("yes update it"),
        _model(_call("load_skill")),
        _resp("load_skill"),
    ])
    cfg2, reason2 = thinking_for({}, step2)
    assert cfg2.thinking_level == types.ThinkingLevel.LOW and reason2 == "confirmation"

    # Non-confirmations in follow-up turns keep MEDIUM thinking.
    for msg in ("My left calf feels tight today", "Yes, why Tuesday?", " ".join(["yes"] * 13)):
        cfg, reason = thinking_for({}, LlmRequest(contents=[*history, _user(msg)]))
        assert cfg.thinking_level == types.ThinkingLevel.MEDIUM and reason == "default"


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
                "stage_training_plan",
                "apply_training_plan",
                "apply_staged_changes",
                "get_weather",
            )
        ]
        r = LlmRequest(
            contents=contents,
            config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=decls)]),
        )
        r.tools_dict.update({d.name: d for d in decls})
        return r

    # 1. Plain chat: internal tools AND stage_training_plan hidden; apply_staged_changes stays declared.
    req = make_req([_user("hi")])
    hide_internal_tools(None, req)
    declared = {d.name for t in req.config.tools for d in t.function_declarations}
    assert declared == {"load_skill", "apply_staged_changes", "get_weather"}
    assert {"fetch_plan_context", "apply_training_plan", "stage_training_plan"} <= set(req.tools_dict)

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
    #    uses LOW thinking ("plan_builder"), and reuses plan_context_cache even after staging.
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
    pb_cfg, pb_reason = thinking_for({}, intake_turn2)
    assert pb_cfg.thinking_level == types.ThinkingLevel.LOW and pb_reason == "plan_builder"

    edit_cfg, edit_reason = thinking_for({"staged_training_plan": {"staged_id": "plan-1"}}, followup_unapplied)
    assert edit_cfg.thinking_level == types.ThinkingLevel.LOW and edit_reason == "plan_builder"

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
