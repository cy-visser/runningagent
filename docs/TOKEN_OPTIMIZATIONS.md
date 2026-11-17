# Running Coach: Token, Call & Prefix-Cache Optimizations

This document maps **every token, LLM-call, thinking-budget, and prefix-cache optimization** implemented in `running_coach`—what it does, **where it lives in code**, and **what problem it solves**—organized first by **cross-cutting engine invariants** and then **per use case (each feature + free-text chat)**.

---

## 1. Executive Matrix by Use Case

| Use Case | Trigger | LLM Calls | Model & Thinking | Prompt / Cache Mode | Key Token Savers |
|---|---|---:|---|---|---|
| **Auth / Routing** | Every request | **0** | Pure Python | N/A | Deterministic `profile_router` + coded error nodes |
| **Free-Text Chat (Q&A)** | Typed coaching message | **1** | `argon` (`MEDIUM`) | Full prompt (cached) | No skill/tool load; stale thoughts stripped; compact `<runner_profile>` |
| **Workout Analysis** | UI button / standalone typed | **1** (`0` if none found) | `argon` (`MEDIUM`) | **Trimmed** (fresh) / **Cached** (warm) | Pre-dispatch skips routing call; `align_workout_skill` swaps run↔bike in code; `reply()` ends turn on missing workout |
| **Check-In Report** | UI button / standalone typed | **1** | `argon` (`MEDIUM`) | **Trimmed** (fresh) / **Cached** (warm) | Pre-dispatch; charts sent via `stateDelta` (not LLM prose); `guard_report_tools` blocks lookup misuse |
| **Race Predictor** | Web `/api/race-predictor` | **0** | Pure Python | Ephemeral session deleted | `SKILL_FREE_ACTIONS` + `skip_summarization=True` |
| **Trend Analysis** | UI button / standalone typed | **1** | `argon` (`MEDIUM`) | **Trimmed** (fresh) / **Cached** (warm) | Pre-dispatch; only last `LLM_RECENT_WEEKS` rows sent to LLM while full 26–52w goes to UI state |
| **Plan Audit** | UI button / standalone typed | **1** | `argon` (`MEDIUM`) | **Trimmed** (fresh) / **Cached** (warm) | Pre-dispatch; 28d cached `volume_history`; delta-only `<= 200w` output cap |
| **Any Report (Free Text)** | Conversational / Dutch / custom | **2** | `argon` (`MEDIUM`) | **Full cached prefix on Call 1 & Call 2** | `mark_report_synthesis` keeps Call 1 prefix intact on Call 2 (~5.7k+ cache hit) while dropping stray tool calls |
| **Workout Creator (Stage)** | Chat edit (`<= 10` items) | **1** | `argon` (`LOW` on confirm/retry, else `MEDIUM`) | Full prompt (cached) | No `SKILL.md`; compact session codes (`E 8`); `message` arg + `ui_channel.reply()` skips Call 2 |
| **Workout Creator (Apply)** | "Update TrainingPeaks" button | **0** (button) / **1** (`LOW` chat) | Pure Python (button) | N/A (button) | `SKILL_FREE_ACTIONS` + `ui_channel.reply()`; applied/replaced stagings stubbed in history |
| **Plan Builder (Intake)** | "Build Plan" UI button | **1** | `argon` (`LOW`) | **Trimmed** (`_PLAN_INTAKE_RULES`, 0 tools) | `fetch_plan_context` pre-dispatched in code; no `SKILL.md` loaded yet |
| **Plan Builder (Stage / Edit)** | Runner agrees / tweaks weeks | **1** | `argon` (`LOW`) | **Byte-identical full prefix + `<plan_builder_protocol>`** | 1-line/week codes; delta-only `base_staged_id` revisions; `ui_channel.reply()` skips Call 2 |
| **Plan Builder (Apply)** | "Apply to TrainingPeaks" (per week) | **0** | Pure Python | N/A | Silent per-week `plan-builder:apply` + `skip_summarization`; all apply events collapse to 1 line in history |
| **Nutrition / Weather** | Chat fueling or forecast request | **2** | `argon` (`MEDIUM`) | Full cached prefix on Call 1 & Call 2 | Compact 3-day window; `mark_report_synthesis` preserves prefix cache on Call 2 |
| **Onboarding / New Goal** | Unonboarded or `request_new_goal` | **1 / turn** | `gemini-3.1-flash-lite` | Task mode (`OnboardingAnswers`) | Cheap flash-lite model + prefilled `temp_onboarding_data` skips known fields |

---

## 2. Cross-Cutting Engine Optimizations (Active Across All Coaching Turns)

Before looking at individual features, these eight mechanisms run across the whole agent to keep baseline input/output tokens low and **protect Vertex AI's implicit prefix cache**:

### 2.1 Zero-LLM Workflow Routing
- **Where**: [`coach/profile_router.py`](../coach/profile_router.py) (`profile_router`, `not_linked_node`, `tp_not_connected_node`, `profile_unavailable_node`) and [`agent.py`](../agent.py).
- **What it does**: Resolves authentication, Firestore profile lookup, KMS TrainingPeaks credential presence, and onboarding vs. coaching routing in deterministic Python, while warming the runner's `tp-mcp` session in the background (`_schedule_tp_warmup`).
- **What it solves**: Eliminates any coordinator/supervisor LLM call (`0` tokens for routing or unlinked/error states).

### 2.2 Vertical Feature Facades Instead of 60+ Raw MCP Tools
- **Where**: [`coach/coaching/coaching_agent.py`](../coach/coaching/coaching_agent.py) (`coaching_agent_tools`) + `features/*/*_tool.py`.
- **What it does**: Wraps 60+ raw TrainingPeaks MCP tools (`tp_*`), Open-Meteo APIs, and Firestore reads behind **11 compact domain tools** that join data in parallel and pre-compute physiological metrics (`Pa:Hr`, `EF`, `rIF`, `CTL/ATL/TSB`, week-over-week `%`, lap-step alignment) in Python.
- **What it solves**: Saves **~8,000–12,000 tool-schema input tokens on every call** and prevents multi-hop MCP chattiness (3–6 sequential LLM tool loops collapse into 1 tool step).

### 2.3 On-Demand Skills & Compact 1-Line Catalog
- **Where**: [`coach/coaching/skill_toolset.py`](../coach/coaching/skill_toolset.py) (`CompactSkillToolset`, `CoachLoadSkillTool`, `format_skill_catalog`).
- **What it does**:
  - Replaces ADK's verbose multi-tool skill loader with a single `load_skill` declaration and a 7-line `<available_skills>` summary (~`160` tokens).
  - Strips unnecessary metadata from `CoachLoadSkillTool.run_async`, returning only `{"skill_name", "instructions"}`.
- **What it solves**: Keeps ~`6,000+` tokens of task-specific `SKILL.md` protocols out of every request until the exact turn that needs one.

### 2.4 Single Compressed, Prefix-Cache-Safe `<runner_profile>` Injection
- **Where**: [`coach/coaching/profile_context.py`](../coach/coaching/profile_context.py) (`ensure_profile_context`, `inject_profile_context`), [`coach/coaching/instruction.py`](../coach/coaching/instruction.py) (`build_coach_instruction`, `build_profile_context`, `format_profile_summary`), and [`coach/coaching/goal_plan_summary.py`](../coach/coaching/goal_plan_summary.py) (`format_goal_plan`).
- **What it does**:
  - Compresses runner demographics, PRs, shoes, multi-block goal plans (with Riegel North-Star equivalents), key events, and goal reasoning into a dense ~`540`-token `<runner_profile>` block (~50% smaller than prose formatting; omits empty/"no injuries" fields).
  - Injects `<runner_profile>` into `system_instruction` **once per call** (never persisted in session events) and places it **before** conditional `<plan_builder_protocol>` blocks, with static `_COACH_ROLE` + `_ROUTING_RULES` + `_CONTRACT_RULES` first.
- **What it solves**: Prevents profile duplication across turns and guarantees a stable byte-for-byte prefix (`~3,170` tokens with tool schemas) for Vertex AI implicit caching.

### 2.5 Internal Tool Hiding & Stable Tool Declarations
- **Where**: [`coach/coaching/model_callbacks.py`](../coach/coaching/model_callbacks.py) (`hide_internal_tools`, `INTERNAL_TOOLS`).
- **What it does**:
  - Removes code-only tools (`fetch_plan_context`, `apply_training_plan`, `refresh_race_projection`) from `llm_request.config.tools` while keeping them executable in `tools_dict`.
  - Hides the large `stage_training_plan` schema unless `plan-builder` is active in context.
  - Keeps `apply_staged_changes` **stably declared** rather than toggling it on/off when `staged_workout_changes` changes.
- **What it solves**: Saves schema tokens for internal/plan-builder tools on everyday turns **without** mutating `config.tools` (which would bust Gemini's prefix cache when staging/applying workouts).

### 2.6 Stripping Stale Reasoning (`thought` & `thought_signature`) from History
- **Where**: [`coach/coaching/model_callbacks.py`](../coach/coaching/model_callbacks.py) (`strip_stale_thoughts`).
- **What it does**: Drops `part.thought=True` blocks and encrypted `part.thought_signature` bytes from all **completed** prior turns (`i < last_runner_message`), keeping signatures only on the active turn's tool loop where Gemini validates them.
- **What it solves**: Encrypted Gemini reasoning signatures otherwise replay on every subsequent turn and account for **~35% of input tokens** in multi-turn coaching conversations.

### 2.7 Per-Request History Deduplication & Stubbing
- **Where**: [`coach/report_memory.py`](../coach/report_memory.py) (`keep_latest_reports_and_skills`, `_stale_skill_stub`, `_keep_latest_in_part`, `_without_replaced_staging`, `_compact_applied`, `_compact_plan`).
- **What it does** (on a copy of `llm_request.contents` per call—never mutating Firestore UI events):
  1. **Stale skills → 1-line stub**: Any `load_skill` response from an earlier completed turn becomes `"[skill instructions from an earlier turn: call load_skill again...]"`.
  2. **Superseded reports → 1-line pointer**: Only the **latest** output of each report type (`fetch_plan_audit_data`, `analyze_workout`, `fetch_checkin_data`, `fetch_trend_data`) and `fetch_plan_context` stays verbatim; older ones become `"[superseded: the latest ... output is further below]"`.
  3. **Replaced / failed stagings → 1-line stub**: Superseded or `staged: 0` `stage_workout_changes` and `stage_training_plan` payloads are replaced with 1-line stubs.
  4. **Applied changes / plans → 1-line summary**: Applied workout sets keep their coaching `message` and collapse the result into `"Applied N/N: ... [id]"`; per-week `apply_training_plan` events collapse into a single summary line and stub out `PLAN_CONTEXT`.
- **What it solves**: Prevents multi-turn sessions from snowballing to 20k–50k tokens as reports, skills, and staged JSON specs accumulate.

### 2.8 4-Hour Context Window & Report-Preserving Session Compaction
- **Where**: [`integrations/session_service.py`](../integrations/session_service.py) (`CONTEXT_WINDOW = timedelta(hours=4)` in `CoachFirestoreSessionService.get_session`) and [`agent.py`](../agent.py) + [`coach/report_memory.py`](../coach/report_memory.py) (`EventsCompactionConfig(compaction_interval=10, overlap_size=2)`, `ReportMemorySummarizer`).
- **What it does**:
  - Sessions idle for > 4 hours automatically load zero old events (`after_timestamp`), starting with a clean context.
  - Every 10 runner messages within an active session, `ONBOARDING_MODEL` (`gemini-3.1-flash-lite`) summarizes older dialogue while `_without_bulky_responses` strips report outputs and `SKILL.md` text **out of the summarizer's own LLM input**, then re-attaches the latest `<report>` block verbatim afterward.
- **What it solves**: Caps long-conversation token growth, runs summarization on cheap `flash-lite` without paying to feed bulky reports into the summarizer, and preserves exact `[workout_id]`s across compactions.

---

## 3. Optimizations Per Use Case

### 3.1 Free-Text Coaching Chat (Plain Q&A, Pushbacks, Follow-Ups)
Examples: *"Should I swap tomorrow's bike with another 6k run?"*, *"Ok prima, hoe hoog mag mijn hartslag morgen zijn?"*

| Optimization | Code Location | What It Solves |
|---|---|---|
| **No-Skill / No-Tool Routing Rule** | [`instruction.py`](../coach/coaching/instruction.py) (`_ROUTING_RULES`: *"Plain coaching chat: NO skill and NO tool"*) | Answers physiology, recovery, gear, and follow-up questions in **1 LLM call** using `<runner_profile>` + recent report memory (`~150–300 words` target). |
| **Report Lookup Guard** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`track_turn_calls`, `guard_report_tools`, `is_turn_report`) | Blocks the LLM from calling `fetch_checkin_data`, `fetch_trend_data`, or `fetch_plan_audit_data` mid-turn as an ad-hoc calendar lookup (saves MCP latency, ~1–3k report tokens, and unwanted UI report cards). |
| **Piggybacked Key-Event Logging** | [`instruction.py`](../coach/coaching/instruction.py) + [`record_key_event_tool.py`](../coach/coaching/record_key_event_tool.py) | Silently records injuries/illnesses/non-goal races into the compact `KEY EVENTS` profile lines (`1 factual line`) instead of relying on unbounded chat history. |
| **429 Single-Retry + Flash Fallback** | [`model_config.py`](../coach/model_config.py) (`MODEL_RETRY_OPTIONS`, `FallbackGemini`, `fallback_request`) | Caps 429 retries to 1 attempt before falling back to `gemini-3.8-flash` (rewriting `thought_signature` to `skip_thought_signature_validator` so cross-model signatures never error). |

---

### 3.2 Workout Analysis (`workout-analysis` & `bike-workout-analysis`)
Triggers: **"Analyze today's workout"** UI button, typed prompts (*"Analyze today's run"*, *"Analyze oct 22nd"*), or free-text/post-race requests.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **Deterministic Pre-Dispatch (UI Button & Standalone Typed)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`QuickActionPlugin`, `infer_typed_quick_action`, `dispatch_quick_action`) | Synthesizes `load_skill` + `analyze_workout` in Python (`SYNTHETIC_THOUGHT_SIGNATURE`), **eliminating Call 1** (`2` LLM calls → **`1` LLM call**, saving ~3k–6k input tokens + Call-1 thinking tokens). |
| **Fresh-Session Prompt & Tool Stripping** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`DISPATCHED_STATE_KEY`), [`instruction.py`](../coach/coaching/instruction.py), [`skill_toolset.py`](../coach/coaching/skill_toolset.py) | On Turn 1 (or standalone report chains with no prior chat turns), omits `SKILL ROUTING` (~`550` tok), `<available_skills>` (~`160` tok), and sets `config.tools = []` (~`1,520` tok) → **saves ~2,240 uncached input tokens**. |
| **Sport-Family Skill Auto-Swap in Code** | [`model_callbacks.py`](../coach/coaching/model_callbacks.py) (`align_workout_skill`) | When a date-only prompt (*"Analyze oct 22nd"*) pre-dispatches `workout-analysis` on a cycling day, swaps the loaded `SKILL.md` in `contents` to `bike-workout-analysis` before the LLM call—avoiding a second `load_skill` LLM turn. |
| **Zero-LLM "No Workout Found" Short-Circuit** | [`analyze_workout_tool.py:L192-L195`](../features/workout_analysis/analyze_workout_tool.py#L192-L195) + [`shared/ui_channel.py`](../shared/ui_channel.py) (`reply`) | If no completed workout exists on the requested date, renders a coded widget citing recent sessions and sets `skip_summarization = True` → **`0` follow-up LLM calls** (prevents the model from fishing across other dates). |
| **Pre-Aligned Structured Laps vs. Targets** | [`analyze_workout_tool.py:L268-L278`](../features/workout_analysis/analyze_workout_tool.py#L268-L278) (`align_laps`, `format_structured_execution`) | When a workout has a structured builder, aligns FIT/stream laps to planned steps in Python and omits the redundant raw lap dump (`include_laps=alignment is None`), cutting telemetry bloat and math errors. |
| **Indoor Weather Skip** | [`analyze_workout_tool.py:L140-L155,L252`](../features/workout_analysis/analyze_workout_tool.py#L140-L155) (`_is_indoor_workout`) | Skips Open-Meteo fetch and weather prompt section on Zwift/trainer/treadmill sessions. |
| **Prefix-Preserving Synthesis Guard (Free-Text 2-Call)** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis` → `SYNTHESIS_GUARD_STATE_KEY`) | On non-race free-text workout analyses that used Call 1 routing, keeps Call 2's prefix byte-identical to Call 1 (preserving the implicit cache) while `drop_disabled_tool_calls` blocks extra tool calls. *(Skipped on races so the coach can offer `request_new_goal` / `record_key_event`.)* |

---

### 3.3 Check-In Report & Race Predictor (`check-in-report` & `check-in-report:project`)
Triggers: **"Check-in"** UI button, typed *"Weekly check-in"* / *"How was my week?"*, free-text check-in requests, and the Dashboard Race Predictor.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **Zero-LLM Race Predictor Endpoint** | [`refresh_race_projection_tool.py`](../features/check_in_report/refresh_race_projection_tool.py) + [`quick_actions.py`](../coach/coaching/quick_actions.py) (`PROJECT_RACE` in `SKILL_FREE_ACTIONS`) | Computes and caches the 12-week key-session race projection in pure Python with `skip_summarization = True` → **`0` LLM calls, `0` tokens**, and deletes the ephemeral session immediately. |
| **1-Call Pre-Dispatch & Fresh-Session Stripping** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`_CHECKIN_LEADS`, `QUICK_ACTIONS["check-in-report"]`) | Skips Call 1 routing and strips ~`2,240` tokens of routing rules, skill catalog, and tool schemas on fresh sessions. |
| **UI State Offload (`checkin_report_data`)** | [`fetch_checkin_data_tool.py:L140-L142`](../features/check_in_report/fetch_checkin_data_tool.py#L140-L142) + [`features/check_in_report/SKILL.md`](../features/check_in_report/SKILL.md) | Streams full PMC, HRV/RHR series, and projection driver charts directly to the React SPA via `stateDelta`; the LLM receives a compact pre-aggregated text summary and outputs **judgment bullets only** (never repeating tables). |
| **Cache-First Key-Workout Summaries** | [`fetch_checkin_data_tool.py:L69-L76,L120-L125`](../features/check_in_report/fetch_checkin_data_tool.py#L69-L76) | Reads `users/{id}/training_log` from Firestore instead of re-fetching and parsing raw FIT telemetry for every workout in the 90-day projection window. |
| **Warm-Cache Synthesis Guard (Free-Text / Multi-Turn)** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis`) + [`quick_actions.py`](../coach/coaching/quick_actions.py) (`_has_prior_full_prompt_turn`) | Preserves the warm `(system_instruction + tools + history)` prefix cache on Step 2 of 2-call turns and on Turn 2+ pre-dispatches. |

---

### 3.4 Trend Analysis (`trend-analysis`)
Triggers: **"Trend Analysis"** UI button, typed *"Analyze my trends for the last 12 weeks"*, or free-text long-horizon questions.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **1-Call Pre-Dispatch (With Optional `weeks` Extraction)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`_TREND_LEAD_RE`, `QUICK_ACTIONS["trend-analysis"]`) | Parses `weeks` (`6..52`) in Python and skips Call 1 routing; strips ~`2,240` prompt/tool tokens on fresh sessions. |
| **Recent-Row Windowing (`LLM_RECENT_WEEKS`)** | [`fetch_trend_data_tool.py:L141-L159`](../features/trend_analysis/fetch_trend_data_tool.py#L141-L159) + `helpers/weekly_rows.py` | Full 26–52 week series goes to `trend_report_data` (for web charts) and pre-computed summary/capacity/pacing tables, while the raw weekly table and athlete comments sent to the LLM are capped to the most recent `LLM_RECENT_WEEKS` weeks (plus older injury niggles). |
| **Warm-Cache Synthesis Guard (Free-Text 2-Call)** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis`) | Keeps Call 1's cached prefix intact on Call 2 so 2-call fallback trend requests hit the full session prefix cache. |

---

### 3.5 Plan Audit (`plan-audit`)
Triggers: **"Plan Audit"** UI button, typed *"Audit my plan"*, *"Audit my 5k block from Nov 30th until Feb 7th. In which session..."*, or conversational/multilingual plan checks (*"Ok I stick with the ride, check this week and next week. Stick to the plan?"*).

| Optimization | Code Location | What It Solves |
|---|---|---|
| **1-Call Pre-Dispatch (Dated Ranges, `next N weeks`, + Tail Questions)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`_infer_typed_audit`, `infer_typed_quick_action`) | Parses explicit date ranges and *"next N weeks"* (even when followed by a read-only question!) in Python, skipping Call 1 and stripping ~`2,240` tokens on fresh sessions. |
| **Prefix-Cache Preservation on 2-Call & Multi-Turn Audits** | [`report_tool_guard.py`](../coach/coaching/report_tool_guard.py) (`mark_report_synthesis` → `SYNTHESIS_GUARD_STATE_KEY`) + [`quick_actions.py`](../coach/coaching/quick_actions.py) (`_has_prior_full_prompt_turn`) | When a conversational or Dutch audit prompt runs as a 2-call turn (or pre-dispatches mid-chat), keeps `system_instruction` and `config.tools` **100% byte-identical** to Call 1 / prior chat turns—turning ~`5,700+` tokens on Call 2 into a prefix-cache hit instead of `0` cached tokens, while `drop_disabled_tool_calls` still prevents extra tool calls. |
| **28-Day Cached 12-Week Volume & Long-Run History** | [`fetch_plan_audit_data_tool.py:L45,L71-L78`](../features/plan_audit/fetch_plan_audit_data_tool.py#L45) (`read_cached_volume_history`, `get_or_fetch_volume_history`) | Reuses pre-aggregated 12-week km & longest-run history (`users/{id}/cache/volume_history`) shared with `plan_builder`, emitting 2 compact context lines instead of 12 weeks of raw workouts. |
| **Strict `<= 200 Words` & Delta-Only Output Contract** | [`features/plan_audit/SKILL.md`](../features/plan_audit/SKILL.md) | Forbids quoting workout titles, repeating weekly totals shown on the web calendar card, or re-summing sessions internally—capping output + thinking tokens (~`350–450` output tokens). |

---

### 3.6 Workout Creator — Small Calendar Edits (`<= 10` Changes)
Triggers: *"Move Friday's 6k run to Saturday"*, *"Yes, apply those recommendations"*, and the **"Update TrainingPeaks"** UI button.

| Optimization | Code Location | What It Solves |
|---|---|---|
| **No `SKILL.md` File or `load_skill` Step** | [`skill_toolset.py`](../coach/coaching/skill_toolset.py) (`SKILL_FEATURES`) + [`stage_workout_changes_tool.py:L214-L223`](../features/workout_creator/stage_workout_changes_tool.py#L214-L223) | All rules live directly in the compact `stage_workout_changes` docstring, eliminating a `load_skill("workout-creator")` round-trip (**saves 1 full LLM call** on every edit). |
| **Compact Session-Code Grammar (`code`)** | [`stage_workout_changes_tool.py:L219-L222`](../features/workout_creator/stage_workout_changes_tool.py#L219-L222) + `shared/session_codes/` | The LLM writes `"code": "T 2x15' r2'"` (~`5` tokens) instead of nested TrainingPeaks workout-builder step JSON (~`250–500` output tokens per session); Python expands paces, WU/CD, strides, and TSS. |
| **Single-Call Staging (`message` + `ui_channel.reply`)** | [`stage_workout_changes_tool.py:L104-L114,L332-L334`](../features/workout_creator/stage_workout_changes_tool.py#L104-L114) + [`shared/ui_channel.py`](../shared/ui_channel.py) | The coach passes its `<= 80w` rationale in the tool's `message` parameter, and `reply()` sets `skip_summarization = True` → **staging completes in 1 LLM call instead of 2** (saving ~5k–8k re-read input tokens). |
| **`LOW` Thinking on Approvals, Confirmations & Retries** | [`model_callbacks.py:L251-L315`](../coach/coaching/model_callbacks.py#L251-L315) (`is_staged_approval`, `is_followup_confirmation`, `_has_workout_creator_step`, `_has_plan_builder_retry_step`) | Drops `thinking_level` from `MEDIUM` → **`LOW`** (without altering the prompt prefix!) when the runner says *"ok, stage the changes"* / *"yes update it"* or when retrying a `staged: 0` validation error. |
| **Delta-Only Retries, Temp TP Cache & Retry Cap (`3`)** | [`stage_workout_changes_tool.py:L56-L59,L280-L314`](../features/workout_creator/stage_workout_changes_tool.py#L56-L59) | On `needs_structure`, caches valid items in `temp:staging_ready_draft` and TP fetches in `temp:staging_tp_cache` so the model re-sends **only** the broken item(s); after `3` failed attempts, `reply()` ends the turn to prevent runaway loops. |
| **Overhaul Guard (`> 10` Changes → `plan-builder`)** | [`stage_workout_changes_tool.py:L54,L62-L75`](../features/workout_creator/stage_workout_changes_tool.py#L62-L75) (`plan_builder_redirect`) | Refuses `> 10` per-item changes and redirects to `plan-builder`'s 1-line-per-week format. |
| **Zero-LLM "Update TrainingPeaks" Button** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`"workout-creator"` in `SKILL_FREE_ACTIONS`) + [`apply_staged_changes_tool.py`](../features/workout_creator/apply_staged_changes_tool.py) | Clicking **Update TrainingPeaks** dispatches `apply_staged_changes` in Python and ends via `reply()` (`skip_summarization = True`) → **`0` LLM calls, `0` tokens**. *(Chat approvals take 1 `LOW`-thinking call to invoke `apply_staged_changes`, then `0` follow-up calls.)* |

---

### 3.7 Plan Builder — Full Training Blocks & Overhauls (`> 10` Sessions)
Triggers: **"Build Plan"** UI button (`plan-builder:intake`), agreeing to build/revise a block in chat, and clicking **"Apply to TrainingPeaks"** (`plan-builder:apply`).

| Optimization | Code Location | What It Solves |
|---|---|---|
| **1-Call `LOW`-Thinking Intake Opener (`plan-builder:intake`)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`PLAN_INTAKE`), [`instruction.py:L282-L300`](../coach/coaching/instruction.py#L282-L300) (`_PLAN_INTAKE_RULES`), [`model_callbacks.py:L292`](../coach/coaching/model_callbacks.py#L292) | Clicking **Build Plan** runs `fetch_plan_context` in code (no routing call, no `SKILL.md` yet), strips routing/tools, uses `_PLAN_INTAKE_RULES` (`<= 180 words`), and runs at **`LOW` thinking** → **1 cheap, fast opener call**. |
| **Auto-Expanded & Cached `fetch_plan_context`** | [`model_callbacks.py:L136-L199`](../coach/coaching/model_callbacks.py#L136-L199) (`expand_plan_builder_context`, `_can_reuse_plan_context`) + [`fetch_plan_context_tool.py`](../features/plan_builder/fetch_plan_context_tool.py) | When `load_skill("plan-builder")` is called in chat, appends `fetch_plan_context` into the **same** parallel tool step (saving an extra LLM step) and skips it completely if `plan_context_cache` already covers the window. Also caches calendar workouts (`temp:plan_workouts`) and zones for `stage_training_plan`. |
| **Prefix-Stable `<plan_builder_protocol>` Preloading** | [`skill_toolset.py:L171-L183`](../coach/coaching/skill_toolset.py#L171-L183) + [`profile_context.py:L51-L56`](../coach/coaching/profile_context.py#L51-L56) | Once `PLAN CONTEXT` or an unapplied staged plan is active, preloads `<plan_builder_protocol>` **after** `<runner_profile>` with **no mutating UUIDs** (injecting `staged_id` transiently in `contents` only if compacted out), keeping Turn 2 (stage) and Turn 3 (revise) `system_instruction` **100% byte-identical** for prefix caching. |
| **1-Line-Per-Week Session-Code Spec & Single-Call Staging** | [`stage_training_plan_tool.py:L83-L97,L178`](../features/plan_builder/stage_training_plan_tool.py#L83-L97) | A 12-week, 70-session plan is generated as **12 compact lines** (`"W1 | base | ... | Tue: I 6x1k r2' | Sun: L 20"`) + a `<= 120w` `message` in **1 `MEDIUM`-thinking LLM call** (`LOW` on syntax retries), ending immediately via `ui_channel.reply()` (`skip_summarization = True`) instead of generating ~15,000 tokens of workout JSON + a 2nd summary call. |
| **Delta-Only Plan Revisions (`base_staged_id`)** | [`stage_training_plan_tool.py:L96-L127`](../features/plan_builder/stage_training_plan_tool.py#L96-L127) (`merge_weeks`) | To tweak Week 4 of a 16-week staged plan, the LLM sends **only `W4`** with `base_staged_id` and a `<= 90–120w` delta-only `### Plan Update` `message` (`1` call total). |
| **Retry Cap (`MAX_PLAN_ATTEMPTS = 2`)** | [`stage_training_plan_tool.py:L33,L38-L45`](../features/plan_builder/stage_training_plan_tool.py#L38-L45) | Stops retries via `ui_channel.reply()` after 2 invalid code attempts in one turn (with retries running at `LOW` thinking). |
| **Zero-LLM Week-by-Week Apply (`plan-builder:apply`)** | [`quick_actions.py`](../coach/coaching/quick_actions.py) (`"plan-builder:apply"` in `SKILL_FREE_ACTIONS`) + [`apply_training_plan_tool.py`](../features/plan_builder/apply_training_plan_tool.py) | Applying a 16-week plan fires 16 silent per-week actions that re-expand codes, diff, write to TrainingPeaks, and set `skip_summarization = True` → **`0` LLM calls across all 16 weeks**, then collapses all 16 events + the staged spec + `PLAN_CONTEXT` into 1-line stubs in `report_memory.py`. |

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
