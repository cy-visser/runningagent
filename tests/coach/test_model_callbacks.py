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

    decls = [
        types.FunctionDeclaration(name=n)
        for n in ("load_skill", "fetch_plan_context", "stage_training_plan", "apply_training_plan", "get_weather")
    ]
    req = LlmRequest(
        contents=[_user("hi")],
        config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=decls)]),
    )
    req.tools_dict.update({d.name: d for d in decls})
    hide_internal_tools(None, req)
    declared = {d.name for t in req.config.tools for d in t.function_declarations}
    assert declared == {"load_skill", "stage_training_plan", "get_weather"}
    assert {"fetch_plan_context", "apply_training_plan"} <= set(req.tools_dict)  # still runnable in code

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
