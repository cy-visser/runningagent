# Running Coach: Token, Call & Prefix-Cache Optimizations

This document maps **every token, LLM-call, thinking-budget, and prefix-cache optimization** implemented in `running_coach`—what it does, **where it lives in code**, and **what problem it solves**—organized first by **cross-cutting engine invariants** and then **per use case (each feature + free-text chat)**.

---

## 1. Executive Matrix by Use Case

| Use Case | Trigger | LLM Calls | Model & Thinking | Prompt / Cache Mode | Key Token Savers |
|---|---|---:|---|---|---|
| **Auth / Routing** | Every request | **0** | Pure Python | N/A | Parallel cached `profile_router` + coded error nodes |
| **Free-Text Chat (Q&A)** | Typed coaching message | **1** | `argon` (`MEDIUM`) | Full prompt (cached) | No skill/tool load; stale thoughts, empty parts & ADK identity boilerplate stripped; compact `<runner_profile>` |
| **Calendar Check (`get_schedule`)** | Typed / chat check | **1** (typed) / **2** (chat) | `argon` (`MEDIUM`) | **Full cached prefix** (`SYNTHESIS_GUARD`) | Pre-dispatch on typed peeks (short or multi-sentence); no `SKILL.md` (`-850` tok), no fitness/volume fetch, `<= 140w` reply cap, no UI report card |
| **Workout Analysis** | UI button / typed (short or rich) | **1** (`0` if none found) | `argon` (`MEDIUM`) | **Full cached prefix** (`SYNTHESIS_GUARD`) | Unified grammar + intent pre-dispatch (incl. multi-sentence/paragraph follow-up questions) skips Call 1 & warms Turn-0 prefix cache; `align_workout_skill` swaps run↔bike in code; `reply()` ends turn on missing workout |
| **Check-In Report** | UI button / typed (short or rich) | **1** | `argon` (`MEDIUM`) | **Full cached prefix** (`SYNTHESIS_GUARD`) | Pre-dispatch warms Turn-0 prefix cache; charts sent via `stateDelta` (not LLM prose); `guard_report_tools` blocks lookup misuse |
| **Race Predictor** | Web `/api/race-predictor` | **0** | Pure Python | Ephemeral session deleted | `SKILL_FREE_ACTIONS` + `skip_summarization=True` |
| **Trend Analysis** | UI button / typed (short or rich) | **1** | `argon` (`MEDIUM`) | **Full cached prefix** (`SYNTHESIS_GUARD`) | Pre-dispatch warms Turn-0 prefix cache; only last `LLM_RECENT_WEEKS` rows sent to LLM while full 26–52w goes to UI state |
| **Plan Audit** | UI button / typed (short or rich) | **1** | `argon` (`MEDIUM`) | **Full cached prefix** (`SYNTHESIS_GUARD`) | Unified grammar + intent pre-dispatch (no arbitrary length cap) warms Turn-0 prefix cache; 28d cached `volume_history`; delta-only `<= 200w` output cap |
| **Any Report (Free Text)** | Conversational / Dutch / custom | **2** | `argon` (`MEDIUM`) | **Full cached prefix on Call 1 & Call 2** | `mark_report_synthesis` keeps Call 1 & report data cached; active-turn thoughts/empty parts stripped while `thought_signature` stays intact for Turn-1+ caching |
| **Workout Creator (Stage)** | Chat edit (`1` to `150+` items) | **1** | `argon` (`MEDIUM`, uniform) | Full prompt (cached) | No `SKILL.md`; compact 1-line/multi-date/week strings (`~4–10` tok/workout); `0` `tp_get_workout` on codes; `<= 12`-line preview echo; `reply()` skips Call 2 |
| **Workout Creator (Apply)** | "Update TrainingPeaks" button | **0** (button) / **1** (`MEDIUM` chat) | Pure Python (button) | N/A (button) / Full cached (chat) | Shared `write_changes_throttled` (`Semaphore(3)` + global 429 cooldown + partial-failure resume); `> 12` applied items collapse to 1 line |
| **Plan Builder (Intake)** | "Build Plan" UI button | **1** | `argon` (`LOW`) | **Trimmed** (`_PLAN_INTAKE_RULES`, 0 tools) | `fetch_plan_context` pre-dispatched in code; no `SKILL.md` loaded yet |
| **Plan Builder (Stage / Edit)** | Runner agrees / tweaks weeks | **1** | `argon` (`MEDIUM`, uniform) | **Byte-identical full prefix + `<plan_builder_protocol>`** | 1-line/week codes; delta-only `base_staged_id` revisions; uniform `MEDIUM` preserves cache on retries; `ui_channel.reply()` skips Call 2 |
| **Plan Builder (Apply)** | "Apply to TrainingPeaks" (per week) | **0** | Pure Python | N/A | Silent per-week `plan-builder:apply` via shared `write_changes_throttled`; all apply events collapse to 1 line in history |
| **Nutrition / Weather** | Chat fueling or forecast request | **2** | `argon` (`MEDIUM`) | Full cached prefix on Call 1 & Call 2 | Compact 3-day window; `mark_report_synthesis` preserves prefix cache on Call 2 |
| **Onboarding / New Goal** | Unonboarded or `request_new_goal` | **1 / turn** | `gemini-3.1-flash-lite` | Task mode (`OnboardingAnswers`) | Cheap flash-lite model + prefilled `temp_onboarding_data` skips known fields |

---

## 2. Cross-Cutting Engine Optimizations (Active Across All Coaching Turns)

Before looking at individual features, these nine **model-agnostic** mechanisms run across the whole agent to keep baseline input/output tokens low and **maximize implicit prefix-cache hit rates** across Gemini 3.x, Gemini 4 Argon, Gemini 4 Hydrogen, and future prefix-cached models:

### 2.1 Zero-LLM Workflow Routing & Parallel Profile + Credential Resolution
- **Where**: [`coach/profile_router.py`](../coach/profile_router.py) (`profile_router`, `_resolve_profile_and_connection`, `not_linked_node`, `tp_not_connected_node`, `profile_unavailable_node`), [`integrations/firestore.py`](../integrations/firestore.py) (`cached_runner_id_for_email`), and [`agent.py`](../agent.py).
- **What it does**: Resolves authentication, Firestore profile lookup (using an in-memory `email -> runner_id` point-read fast path in parallel with KMS TrainingPeaks credential presence via `asyncio.gather`), and onboarding vs. coaching routing in deterministic Python, while warming the runner's `tp-mcp` session in the background (`_schedule_tp_warmup`).
- **What it solves**: Eliminates any coordinator/supervisor LLM call (`0` tokens for routing or unlinked/error states) and collapses two sequential Firestore round-trips into one parallel RTT while still reloading fresh profile edits on every web turn.

### 2.2 Vertical Feature Facades Instead of 60+ Raw MCP Tools
- **Where**: [`coach/coaching/coaching_agent.py`](../coach/coaching/coaching_agent.py) (`coaching_agent_tools`) + `features/*/*_tool.py`.
- **What it does**: Wraps 60+ raw TrainingPeaks MCP tools (`tp_*`), Open-Meteo APIs, and Firestore reads behind **11 compact domain tools** that join data in parallel and pre-compute physiological metrics (`Pa:Hr`, `EF`, `rIF`, `CTL/ATL/TSB`, week-over-week `%`, lap-step alignment) in Python.
- **What it solves**: Saves **~8,000–12,000 tool-schema input tokens on every call** and prevents multi-hop MCP chattiness (3–6 sequential LLM tool loops collapse into 1 tool step).

### 2.3 On-Demand Skills & Compact 1-Line Catalog
- **Where**: [`coach/coaching/skill_toolset.py`](../coach/coaching/skill_toolset.py) (`CompactSkillToolset`, `CoachLoadSkillTool`, `format_skill_catalog`).
- **What it does**:
  - Replaces ADK's verbose multi-tool skill loader with a single `load_skill` declaration and a 7-line `<available_skills>` summary (~`160` tokens).
  - Strips unnecessary metadata from `CoachLoadSkillTool.run_async`, returning only `{"skill_name", "instructions"}`, and keeps each on-demand `SKILL.md` free of duplicated global routing/`GOAL REASONING` boilerplate.
- **What it solves**: Keeps ~`4,500+` tokens of task-specific `SKILL.md` protocols out of every request until the exact turn that needs one, and minimizes Turn-0 synthesis tokens.

### 2.4 Static Prefix Head & Compressed `<runner_profile>` Injection
- **Where**: [`coach/coaching/profile_context.py`](../coach/coaching/profile_context.py) (`ensure_profile_context`, `inject_profile_context`), [`coach/coaching/instruction.py`](../coach/coaching/instruction.py) (`build_coach_instruction`, `build_profile_context`, `format_profile_summary`), and [`coach/coaching/goal_plan_summary.py`](../coach/coaching/goal_plan_summary.py) (`format_goal_plan`).
- **What it does**:
  - Keeps `build_coach_instruction` (`_COACH_ROLE` + `_ROUTING_RULES` + `_CONTRACT_RULES`) + `<available_skills>` **100% static across turns, users, and calendar days** by placing `Today: YYYY-MM-DD (Weekday)` inside `<runner_profile>` *after* `</available_skills>`.
  - Compresses runner demographics, PRs, shoes, multi-block goal plans (with Riegel North-Star equivalents), and goal reasoning into a dense ~`480`-token `<runner_profile>` block (~50% smaller than prose formatting; omits empty/"no injuries" fields) while stripping ADK's redundant auto-injected `You are an agent...` identity paragraph.
  - Injects `<runner_profile>` into `system_instruction` **once per call** (never persisted in session events) and places it **before** conditional `<plan_builder_protocol>` blocks.
  - Preserves the full `(system_instruction + tools)` prefix from **Turn 0 onward** on all report, workout, and schedule quick actions (`SYNTHESIS_GUARD_STATE_KEY`), warming the globally shared `~3,450`-token static prefix from Turn 0 (only `plan-builder:intake` uses trimmed `_PLAN_INTAKE_RULES` + `tools=[]`).
- **What it solves**: Prevents profile duplication across turns and guarantees a byte-identical prefix from Turn 0 through Turn N.

### 2.5 Internal Tool Hiding, Schema Metadata Stripping & Stable Tool Declarations
- **Where**: [`coach/coaching/model_callbacks.py`](../coach/coaching/model_callbacks.py) (`hide_internal_tools`, `_clean_declaration`, `INTERNAL_TOOLS`).
- **What it does**:
  - Removes code-only tools (`fetch_plan_context`, `apply_training_plan`, `refresh_race_projection`) from `llm_request.config.tools` while keeping them executable in `tools_dict`.
  - Hides the large `stage_training_plan` schema unless `plan-builder` is active in context.
  - Strips redundant Pydantic `"title"` metadata and `"default": null` entries from every declared `FunctionDeclaration` (~`250–300` tokens saved per full-prompt call).
  - Keeps `apply_staged_changes` **stably declared** rather than toggling it on/off when `staged_workout_changes` changes.
- **What it solves**: Saves schema tokens on everyday turns **without** mutating `config.tools` across turns (preserving implicit prefix caching).

### 2.6 Uniform Warm-Turn Thinking Level (Token-0 Cache Invariant)
- **Where**: [`coach/coaching/model_callbacks.py`](../coach/coaching/model_callbacks.py) (`thinking_for`, `apply_thinking_policy`).
- **What it does**: Uses uniform `DEFAULT_THINKING` (`COACH_THINKING_LEVEL`, default `MEDIUM`) across **all** warm coaching turns—including report synthesis, follow-up chat, staged approvals, and staging validation retries. Only the standalone `plan-builder:intake` opener (`PLAN_INTAKE_STATE_KEY`) uses `LOW`.
- **What it solves**: Gemini models inject `EFFORT LEVEL: <level>` at token 0; toggling `MEDIUM → LOW` mid-session invalidates 100% of the KV cache (~`4k–12k` cached tokens lost per flip). Keeping warm turns uniform guarantees zero thinking-induced cache misses across model generations.

### 2.7 Thought-Text Stripping with Cache-Safe `thought_signature` Preservation
- **Where**: [`coach/coaching/model_callbacks.py`](../coach/coaching/model_callbacks.py) (`strip_stale_thoughts`).
- **What it does**:
  - Drops `part.thought=True` reasoning text and trailing empty SSE `Part(text="")` (including signed empty parts) on **all** model turns (both active-turn Call 2 and completed turns).
  - Preserves `thought_signature` bytes **verbatim** on all retained `functionCall` and `text` parts across both active and completed turns (synthetic quick-action signatures and real model signatures alike; cross-model 429 fallback already rewrites signatures in `FallbackGemini.fallback_request`).
- **What it solves**: Eliminates ~`200–500` uncached reasoning-text tokens per 2-call turn while avoiding Turn-1 prefix-cache invalidation on completed 2-call turns (`thought_signature` is an opaque `TYPE_BYTES` payload billed at `0` input tokens, whereas stripping it mutates completed `functionCall` parts and truncates the implicit KV cache right before Turn 0's tool responses).

### 2.8 Completed-Turn Skill Stubbing & Bounded Report/Staging History
- **Where**: [`coach/report_memory.py`](../coach/report_memory.py) (`keep_latest_reports_and_skills`, `_stale_skill_stub`, `_keep_latest_in_part`, `_without_replaced_staging`, `_compact_applied`, `_compact_plan`).
- **What it does** (on a copy of `llm_request.contents` per call—never mutating Firestore UI events):
  1. **Completed-turn `SKILL.md` stubbing**: Stubs **all** completed-turn `load_skill` rubrics (`ci < turn_start`). Because `load_skill` sits in `parts[1]` *after* `parts[0]` report data, stubbing it never invalidates prefix caching on `system_instruction + tools + report_data` while saving **`~1,000–1,400` uncached input tokens on every follow-up turn**.
  2. **Superseded reports → 1-line pointer**: Only the **latest** output of each report/schedule type (`fetch_plan_audit_data`, `get_schedule`, `analyze_workout`, `fetch_checkin_data`, `fetch_trend_data`) and `fetch_plan_context` stays verbatim; older ones become `"[superseded: the latest ... output is further below]"`.
  3. **Replaced / failed stagings → 1-line stub**: Superseded or `staged: 0` `stage_workout_changes` and `stage_training_plan` payloads are replaced with 1-line stubs.
  4. **Bounded applied summaries (`1` to `150+` items)**: Applied workout sets keep their coaching `message` and collapse the result into `"Applied N/N: ... [id]"` (for `<= 12` items) or a single counts + window summary line (`"Applied 100/100 (2027-01-01..2027-05-16): 40 create, 60 update"`, `~25` tokens) for large batches; per-week `apply_training_plan` events likewise collapse into one summary line.
- **What it solves**: Slashes uncached follow-up history tokens even when `<8,192`-token conversations have no sticky worker affinity, and prevents 100-workout batches from bloating subsequent chat turns.

### 2.9 4-Hour Context Window & Report-Preserving Session Compaction
- **Where**: [`integrations/session_service.py`](../integrations/session_service.py) (`CONTEXT_WINDOW = timedelta(hours=4)` in `CoachFirestoreSessionService.get_session`) and [`agent.py`](../agent.py) + [`coach/report_memory.py`](../coach/report_memory.py) (`EventsCompactionConfig(compaction_interval=10, overlap_size=2)`, `ReportMemorySummarizer`).
- **What it does**:
  - Sessions idle for > 4 hours automatically load zero old events (`after_timestamp`), starting with a clean context.
  - Every 10 runner messages within an active session, `ONBOARDING_MODEL` (`gemini-3.1-flash-lite`) summarizes older dialogue while `_without_bulky_responses` strips report outputs and `SKILL.md` text **out of the summarizer's own LLM input**, then re-attaches the latest `<report>` block verbatim afterward.
- **What it solves**: Caps long-conversation token growth, runs summarization on cheap `flash-lite` without paying to feed bulky reports into the summarizer, and preserves exact `[workout_id]`s across compactions.

---

## 3. Optimizations Per Use Case

### 3.1 Free-Text Coaching Chat & Calendar Checks (`get_schedule`)
Examples: *"Should I swap tomorrow's bike with another 6k run?"*, *"Pull up this week"*, *"I'm on holiday Dec 20–26, what runs are scheduled and how should we adjust them?"*

| Optimization | Code Location | What It Solves |
|---|---|---|
| **No-Skill / No-Tool Routing Rule** | [`instruction.py`](../coach/coaching/instruction.py) (`_ROUTING_RULES`: *"Plain chat: NO skill/tool"*) | Answers physiology, recovery, gear, and follow-up questions in **1 LLM call** using `<runner_profile>` + recent report memory (`<= 180w` bullets). |
| **Lightweight Calendar Check (`get_schedule`)** | [`get_schedule_tool.py`](../features/schedule_lookup/get_schedule_tool.py) + [`typed_dispatch.py`](../coach/coaching/typed_dispatch.py) (`_infer_typed_schedule`) + [`instruction.py`](../coach/coaching/instruction.py) | Fetches `<= 6` weeks of workouts + notes with **no `SKILL.md` (`-850` tok)**, **no `tp_get_fitness` / `volume_history` (`-500` tok)**, compact merged session lines, a **`<= 140w`** conflict/options reply cap, and **no unwanted UI report card**. |
| **Report Lookup Guard** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`track_turn_calls`, `guard_report_tools`, `is_turn_report`) | Blocks the LLM from calling `fetch_checkin_data`, `fetch_trend_data`, or `fetch_plan_audit_data` mid-turn as an ad-hoc calendar lookup (saves MCP latency, ~1–3k report tokens, and unwanted UI report cards). |
| **429 Single-Retry + Flash Fallback** | [`model_config.py`](../coach/model_config.py) (`MODEL_RETRY_OPTIONS`, `FallbackGemini`, `fallback_request`) | Caps 429 retries to 1 attempt before falling back to `gemini-3.8-flash` (rewriting `thought_signature` to `skip_thought_signature_validator` so cross-model signatures never error). |

---

### 3.2 Workout Analysis (`workout-analysis` & `bike-workout-analysis`)
Triggers: **"Analyze today's workout"** UI button, typed prompts (*"Analyze today's run"*, *"Analyze oct 15th — why was my HR so high?"*, *"Analyze today's tempo run. Did my HR drift too much in the last 3 km?"*), or free-text/post-race requests.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **Deterministic Pre-Dispatch (UI Button, Short & Rich Multi-Sentence Typed)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`QuickActionPlugin`, `dispatch_quick_action`) + [`typed_dispatch.py`](../coach/coaching/typed_dispatch.py) (`infer_typed_quick_action`, `_infer_typed_workout`, `_tail_blocks_pre_dispatch`) | Synthesizes `analyze_workout` + `load_skill` in Python (`SYNTHETIC_THOUGHT_SIGNATURE`) for unambiguous workout leads even with multi-sentence / multi-paragraph follow-up questions (no arbitrary word-count cap; bails out on comparisons, other dates/reports, injuries, mutations, `"race"`, or `"goal"`), **eliminating Call 1** (`2` LLM calls → **`1` LLM call**, saving ~3k–6k input tokens + Call-1 thinking tokens). |
| **Turn-0 Full-Prefix Cache Warming (`SYNTHESIS_GUARD_STATE_KEY`)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`dispatch_quick_action`, `drop_disabled_tool_calls`) | Keeps the full `(system_instruction + tools)` prefix intact on Turn 0 while `drop_disabled_tool_calls` strips any stray tool calls on synthesis. |
| **Sport-Family Skill Auto-Swap in Code** | [`model_callbacks.py`](../coach/coaching/model_callbacks.py) (`align_workout_skill`) | When a date-only prompt (*"Analyze oct 22nd. Did my cadence drop..."*) pre-dispatches `workout-analysis` on a cycling day, swaps the loaded `SKILL.md` in `contents` to `bike-workout-analysis` before the LLM call—avoiding a second `load_skill` LLM turn. |
| **Zero-LLM "No Workout Found" Short-Circuit** | [`analyze_workout_tool.py:L192-L195`](../features/workout_analysis/analyze_workout_tool.py#L192-L195) + [`shared/ui_channel.py`](../shared/ui_channel.py) (`reply`) | If no completed workout exists on the requested date, renders a coded widget citing recent sessions and sets `skip_summarization = True` → **`0` follow-up LLM calls** (prevents the model from fishing across other dates). |
| **Pre-Aligned Structured Laps vs. Targets** | [`analyze_workout_tool.py:L268-L278`](../features/workout_analysis/analyze_workout_tool.py#L268-L278) (`align_laps`, `format_structured_execution`) | When a workout has a structured builder, aligns FIT/stream laps to planned steps in Python and omits the redundant raw lap dump (`include_laps=alignment is None`), cutting telemetry bloat and math errors. |
| **Indoor Weather Skip** | [`analyze_workout_tool.py:L140-L155,L252`](../features/workout_analysis/analyze_workout_tool.py#L140-L155) (`_is_indoor_workout`) | Skips Open-Meteo fetch and weather prompt section on Zwift/trainer/treadmill sessions. |
| **Prefix-Preserving Synthesis Guard (Free-Text 2-Call)** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis` → `SYNTHESIS_GUARD_STATE_KEY`) | On non-race free-text workout analyses that used Call 1 routing, keeps Call 2's prefix byte-identical to Call 1 (preserving the implicit cache) while `drop_disabled_tool_calls` blocks extra tool calls. *(Skipped on races so the coach can offer `request_new_goal`.)* |

---

### 3.3 Check-In Report & Race Predictor (`check-in-report` & `check-in-report:project`)
Triggers: **"Check-in"** UI button, typed *"Weekly check-in"* / *"How was my week?"*, free-text check-in requests, and the Dashboard Race Predictor.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **Zero-LLM Race Predictor Endpoint** | [`refresh_race_projection_tool.py`](../features/check_in_report/refresh_race_projection_tool.py) + [`quick_actions.py`](../coach/coaching/quick_actions.py) (`PROJECT_RACE` in `SKILL_FREE_ACTIONS`) | Computes and caches the 12-week key-session race projection in pure Python with `skip_summarization = True` → **`0` LLM calls, `0` tokens**, and deletes the ephemeral session immediately. |
| **1-Call Pre-Dispatch & Turn-0 Cache Warming** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`QUICK_ACTIONS["check-in-report"]`, `SYNTHESIS_GUARD_STATE_KEY`) + [`typed_dispatch.py`](../coach/coaching/typed_dispatch.py) (`_CHECKIN_LEADS`) | Skips Call 1 routing while keeping the full static prefix + tools intact so follow-up turns hit the Turn-0 implicit prefix cache. |
| **UI State Offload (`checkin_report_data`)** | [`fetch_checkin_data_tool.py:L140-L142`](../features/check_in_report/fetch_checkin_data_tool.py#L140-L142) + [`features/check_in_report/SKILL.md`](../features/check_in_report/SKILL.md) | Streams full PMC, HRV/RHR series, and projection driver charts directly to the React SPA via `stateDelta`; the LLM receives a compact pre-aggregated text summary and outputs **judgment bullets only** (never repeating tables). |
| **Cache-First Key-Workout Summaries** | [`fetch_checkin_data_tool.py:L69-L76,L120-L125`](../features/check_in_report/fetch_checkin_data_tool.py#L69-L76) | Reads `users/{id}/training_log` from Firestore instead of re-fetching and parsing raw FIT telemetry for every workout in the 90-day projection window. |
| **Warm-Cache Synthesis Guard (Free-Text / Multi-Turn)** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis`) + [`quick_actions.py`](../coach/coaching/quick_actions.py) (`SYNTHESIS_GUARD_STATE_KEY`) | Preserves the warm `(system_instruction + tools + history)` prefix cache on Step 2 of 2-call turns and across all follow-up turns. |

---

### 3.4 Trend Analysis (`trend-analysis`)
Triggers: **"Trend Analysis"** UI button, typed *"Analyze my trends for the last 12 weeks"*, or free-text long-horizon questions.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **1-Call Pre-Dispatch (With Optional `weeks` Extraction)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`QUICK_ACTIONS["trend-analysis"]`) + [`typed_dispatch.py`](../coach/coaching/typed_dispatch.py) (`_TREND_LEAD_RE`) | Parses `weeks` (`6..52`) in Python and skips Call 1 routing while keeping the full prefix intact to warm the Turn-0 cache for follow-up turns. |
| **Recent-Row Windowing (`LLM_RECENT_WEEKS`)** | [`fetch_trend_data_tool.py:L141-L159`](../features/trend_analysis/fetch_trend_data_tool.py#L141-L159) + `helpers/weekly_rows.py` | Full 26–52 week series goes to `trend_report_data` (for web charts) and pre-computed summary/capacity/pacing tables, while the raw weekly table and athlete comments sent to the LLM are capped to the most recent `LLM_RECENT_WEEKS` weeks (plus older injury niggles). |
| **Warm-Cache Synthesis Guard (Free-Text 2-Call)** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis`) | Keeps Call 1's cached prefix intact on Call 2 so 2-call fallback trend requests hit the full session prefix cache. |

---

### 3.5 Plan Audit (`plan-audit`)
Triggers: **"Plan Audit"** UI button, typed *"Audit my plan"*, rich multi-sentence/multi-paragraph briefs (*"Audit my 5k block from Nov 30th until Feb 7th. I'm aiming for 20:40... I have a holiday Dec 19–26."*), or conversational/multilingual plan audits.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **1-Call Pre-Dispatch (Dated Ranges, `next N weeks`, & Rich Multi-Sentence Briefs)** | [`typed_dispatch.py`](../coach/coaching/typed_dispatch.py) (`_infer_typed_audit`, `_tail_blocks_pre_dispatch`, `infer_typed_quick_action`) + [`quick_actions.py`](../coach/coaching/quick_actions.py) | Uses strict lead grammar + intent-based tail guards (no arbitrary word/newline/semicolon limits) to parse explicit date ranges and *"next N weeks"* even when followed by multi-sentence goal/holiday context, skipping Call 1 while warming the full Turn-0 prefix cache. |
| **Compact Weekly Session & Note Formatting** | [`weekly_buckets.py`](../shared/weekly_buckets.py) (`format_week_sessions`) + [`calendar_notes.py`](../shared/calendar_notes.py) (`add_notes_to_weeks`) | Drops per-session `TSS` (weekly `TSS` is in header), omits default `Run` prefix and duplicate title `km`, merges identical consecutive days (`Wed/Thu: '10km Easy Run'`), caps notes at 60 chars, and skips duplicate `Master Goal:` roadmap notes—saving **`~500` tokens per turn (`~1,000` across Turn 0 + Turn 1)** while keeping UI `audit_report_data` untouched. |
| **28-Day Cached 12-Week Volume & Long-Run History** | [`fetch_plan_audit_data_tool.py`](../features/plan_audit/fetch_plan_audit_data_tool.py) (`read_cached_volume_history`, `get_or_fetch_volume_history`) | Reuses pre-aggregated 12-week km & longest-run history (`users/{id}/cache/volume_history`) shared with `plan_builder`, emitting 2 compact context lines instead of 12 weeks of raw workouts. |
| **Strict `<= 200 Words`, Delta-Only & Codeable Recommendations** | [`features/plan_audit/SKILL.md`](../features/plan_audit/SKILL.md) | Forbids quoting workout titles, repeating weekly totals, or re-summing sessions, and directs `### Recommendations` to propose clean single-pattern sessions that map 1-to-1 to session codes on Turn 1. |

---

### 3.6 Workout Creator — Unified Cap-Free Calendar Edits (`1` to `150+` Changes)
Triggers: *"Move Friday's 6k run to Saturday"*, *"Agreed, stage your 21 recommendations"*, *"Stage 16 weeks of Wednesday Z2 rides"*, and the **"Update TrainingPeaks"** UI button.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **No `SKILL.md`, Zero Count Cap (`1..150+`)** | [`stage_workout_changes_tool.py`](../features/workout_creator/stage_workout_changes_tool.py) | Eliminates `load_skill` round-trips and removes any arbitrary `MAX_WORKOUT_CHANGES` cliff—preventing reasoning-token rationing loops (`-1,000` thinking tokens) and `plan-builder` bounce round-trips (`-10,000` tokens). |
| **Compact 1-Line, Multi-Date & Week-Line DSL** | [`compact_changes.py`](../features/workout_creator/helpers/compact_changes.py) (`expand_change_entries`) + `shared/session_codes/` | Stages 1 workout (`"2027-01-05: P 4x1.2k @4:08 r2'"`, `~10` tok), multi-date batches (`"2026-12-30,2026-12-31: E 8 -strides"`, `~5` tok/workout), or full weeks (`"2026-11-30 \| Tue: ... \| Sun: L 18"`, `~4` tok/workout → **100 workouts in ~400 output tokens** instead of ~3,800 tokens of JSON dicts). |
| **Zero-Burst Staging Reads & Bounded Preview Echo** | [`stage_workout_changes_tool.py`](../features/workout_creator/stage_workout_changes_tool.py) (`to_check`, `_preview_staged_lines`) | `BUILDER_CODE` builds deterministic strides directly without per-workout `tp_get_workout` MCP calls (`100` runs = only `1–2` `tp_get_workouts` chunk reads + `1` settings read), and caps the LLM tool-response echo at `12` preview lines while sending all items to the scrollable web card. |
| **Single-Call Staging (`message` + `ui_channel.reply`)** | [`stage_workout_changes_tool.py`](../features/workout_creator/stage_workout_changes_tool.py) + [`shared/ui_channel.py`](../shared/ui_channel.py) | Passes rationale in `message` (`<= 35w` if already discussed, else `<= 80w`) and sets `skip_summarization = True` → **staging completes in 1 LLM call**. |
| **Shared Throttled + Global-429-Cooldown + Resumable Apply** | [`workout_upsert.py`](../shared/workout_upsert.py) (`write_changes_throttled`) + [`apply_staged_changes_tool.py`](../features/workout_creator/apply_staged_changes_tool.py) | Clicking **Update TrainingPeaks** runs in pure Python (`0` LLM tokens) with `Semaphore(3)`, a shared global `429` cooldown gate (`2s → 4s → 8s`) that pauses all workers on rate limits, and partial-failure retention so retrying writes only remaining failed items. |

---

### 3.7 Plan Builder — New Multi-Week Training Blocks & Full-Block Grids
Triggers: **"Build Plan"** UI button (`plan-builder:intake`), agreeing to design a new goal block in chat, and clicking **"Apply to TrainingPeaks"** (`plan-builder:apply`).

| Optimization | Code Location | What It Solves |
|---|---|---|
| **1-Call `LOW`-Thinking Intake Opener (`plan-builder:intake`)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`PLAN_INTAKE`, `PLAN_INTAKE_STATE_KEY`), [`instruction.py`](../coach/coaching/instruction.py) (`_PLAN_INTAKE_RULES`), [`model_callbacks.py`](../coach/coaching/model_callbacks.py) (`thinking_for`) | Clicking **Build Plan** runs `fetch_plan_context` in code (no routing call, no `SKILL.md` yet), strips routing/tools, uses `_PLAN_INTAKE_RULES` (`<= 180 words`), and runs at **`LOW` thinking** → **1 cheap, fast opener call**. |
| **Auto-Expanded & Cached `fetch_plan_context`** | [`model_callbacks.py`](../coach/coaching/model_callbacks.py) (`expand_plan_builder_context`, `_can_reuse_plan_context`) + [`fetch_plan_context_tool.py`](../features/plan_builder/fetch_plan_context_tool.py) | When `load_skill("plan-builder")` is called in chat, appends `fetch_plan_context` into the **same** parallel tool step (saving an extra LLM step) and skips it completely if `plan_context_cache` already covers the window. Also caches calendar workouts (`temp:plan_workouts`) and zones for `stage_training_plan`. |
| **Prefix-Stable `<plan_builder_protocol>` Preloading** | [`skill_toolset.py:L171-L183`](../coach/coaching/skill_toolset.py#L171-L183) + [`profile_context.py:L55-L60`](../coach/coaching/profile_context.py#L55-L60) | Once `PLAN CONTEXT` or an unapplied staged plan is active, preloads `<plan_builder_protocol>` **after** `<runner_profile>` with **no mutating UUIDs**, keeping Turn 2 (stage) and Turn 3 (revise) `system_instruction` **100% byte-identical** for prefix caching. |
| **1-Line-Per-Week Session-Code Spec & Single-Call Staging** | [`stage_training_plan_tool.py`](../features/plan_builder/stage_training_plan_tool.py) | Generates a 12–24 week plan as **1 compact line per week** + `<= 120w` `message` in **1 `MEDIUM`-thinking LLM call**, ending immediately via `ui_channel.reply()` (`skip_summarization = True`). |
| **Delta-Only Plan Revisions (`base_staged_id`)** | [`stage_training_plan_tool.py`](../features/plan_builder/stage_training_plan_tool.py) (`merge_weeks`) | To tweak Week 4 of a 16-week staged plan, the LLM sends **only `W4`** with `base_staged_id` and a `<= 90–120w` delta-only `### Plan Update` `message` (`1` call total). |
| **Retry Cap (`MAX_PLAN_ATTEMPTS = 2`)** | [`stage_training_plan_tool.py`](../features/plan_builder/stage_training_plan_tool.py) | Stops retries via `ui_channel.reply()` after 2 invalid code attempts in one turn (keeping `MEDIUM` thinking so retries hit the warm prefix cache). |
| **Zero-LLM Throttled Week-by-Week Apply (`plan-builder:apply`)** | [`apply_training_plan_tool.py`](../features/plan_builder/apply_training_plan_tool.py) + [`workout_upsert.py`](../shared/workout_upsert.py) (`write_changes_throttled`) | Applies week-by-week via the shared throttled writer (`0` LLM calls), then collapses all apply events + staged spec + `PLAN_CONTEXT` into 1-line stubs in `report_memory.py`. |

---

### 3.8 Nutrition Planner (`nutrition-planner`) & Weather Lookup (`weather_lookup`)
Triggers: *"What gels/carbs should I take on Sunday's long run?"*, *"Will wind affect Thursday's tempo?"*

| Optimization | Code Location | What It Solves |
|---|---|---|
| **Tight Default Horizon (`days_forward = 3`)** | [`fetch_nutrition_context_tool.py`](../features/nutrition_planner/fetch_nutrition_context_tool.py) | Fetches only the next 3 days of planned workouts + Open-Meteo forecasts in parallel, returning a compact summary instead of full multi-week calendars. |
| **Prefix-Preserving Synthesis Guard on Step 2** | [`report_tool_guard.py:L42,L145-L170`](../coach/coaching/report_tool_guard.py#L42) (`_SYNTHESIS_TOOLS` includes `"fetch_nutrition_context"`) | Keeps Call 1's `(system_instruction + tools + history)` prefix cached on Call 2 while dropping any stray follow-up tool calls on read-only fueling turns. |

---

### 3.9 Onboarding & Goal Transitions (`onboarding_agent` & `request_new_goal`)
Triggers: New runner without a goal, or runner accepting a new goal after finishing a race.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **Dedicated Lightweight Model (`gemini-3.1-flash-lite`)** | [`model_config.py:L15`](../coach/model_config.py#L15) (`ONBOARDING_MODEL`) + [`onboarding_agent.py:L103-L105`](../coach/onboarding/onboarding_agent.py#L103-L105) | Runs conversational form-filling and structured `OnboardingAnswers` extraction on `flash-lite` (no coaching tools or skill catalog attached) instead of `gemini-4-argon`. |
| **Prefilled Existing Profile (`temp_onboarding_data`)** | [`profile_router.py:L96-L98`](../coach/profile_router.py#L96-L98) (`onboarding_prefill`) | Pre-populates known age, height, weight, PRs, training times, and shoes so re-onboarding for a new goal finishes in 1–2 short turns instead of re-asking 9 fields. |
| **Computed Goal-Race Notices (Zero Stored Bloat)** | [`instruction.py:L172-L205`](../coach/coaching/instruction.py#L172-L205) (`goal_notice`) | Injects `GOAL RACE DONE` / `SUB-GOAL RACE DONE` instructions dynamically from race dates only when applicable, never storing sticky notice prompts in session history. |
