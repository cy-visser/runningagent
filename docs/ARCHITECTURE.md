# Running Coach: Architecture

The AI Running Coach is a running coach and exercise physiologist available through two front ends sharing one **Vertex AI Agent Runtime** deployment: **Gemini Enterprise** (A2A chat) and a **Cloud Run Web App** protected by **Identity-Aware Proxy (IAP)**. It reads training data from **TrainingPeaks** and weather from **Open-Meteo**, stores profiles, KMS-encrypted credentials, sessions, and training logs in **Firestore**, and coaches with Gemini models.

| | |
|---|---|
| Front ends | Gemini Enterprise app "Running Coach" (A2A) **and/or** Cloud Run `running-coach-web` (React + FastAPI behind IAP) |
| Agent runs on | Vertex AI Agent Runtime, custom container, `europe-west4` |
| Framework | Agent Development Kit (ADK) `Workflow` |
| Models | Gemini flash (coaching), Gemini flash-lite (onboarding, history summaries) |
| Security | Cloud Run Direct IAP (ES256 JWT) + Cloud KMS envelope encryption (`running-coach/tp-cookie`) |
| Data | Firestore Enterprise (`running-coach` DB), TrainingPeaks via MCP, Open-Meteo |

<img src="diagrams/01_system_context.svg" alt="System context" style="border: 1px solid #dadce0; border-radius: 8px; max-width: 100%;" />

---

## 1. ADK workflow

<img src="diagrams/02_adk_workflow.svg" alt="ADK workflow" style="border: 1px solid #dadce0; border-radius: 8px; max-width: 100%;" />

The root agent is an ADK `Workflow` with one deterministic router and four nodes:

- **`profile_router`** (no LLM) resolves the authenticated runner's email (`user:auth_email` from the Cloud Run Web App, `session.user_id` email from Gemini Enterprise, or `DEV_RUNNER_EMAIL` in local `adk web`), looks up `users` in Firestore via the `users_by_email` index, verifies that `users/{runner_id}/private/trainingpeaks` holds a KMS-encrypted TrainingPeaks cookie, and routes to one node. Re-reading Firestore on web turns ensures profile edits saved in the Web App take effect on the very next coaching message.
- **`tp_not_connected_node`** returns a fixed onboarding instruction pointing to `WEB_APP_URL` when a runner has no profile or encrypted TrainingPeaks credential yet.
- **`onboarding_node`** runs `onboarding_agent` in *task mode*. It collects either a **single goal** or a **goal plan** (stepping-stone sub-goals leading to a North Star race) as a structured `OnboardingAnswers` object, geocodes the runner's city, and merges the profile into Firestore while preserving `email`.
- **`coaching_node`** runs `coaching_agent` in *chat mode*. Its instruction is an ADK *InstructionProvider* (`build_coach_instruction`) that derives the date, profile summary, active goal block, and goal notices from `user_profile` on every model call.
- **`tp_unavailable_node`** returns a fixed message when TrainingPeaks cannot be reached or a stored cookie has expired, preventing a known runner from ever being misrouted to onboarding.

**Goal plans.** A plan stores `north_star` and `sub_goals`, each a full training block with a `start_date` and a finishing race (`race_date`). `utils/goals.py` derives `current_goal` with the same keys as a single goal (`training_goal`, `timeline`, `goal_set_date`), keeping trajectory, taper, and race projection maths unified.

**Session handling.** A custom Firestore session service automatically resumes the runner's previous session (keyed cleanly per surface: `<email>` on Gemini Enterprise and `web_<email>` on the Web App). Every 10 turns, ADK event compaction summarises older history.

---

## 2. Tool calling & structured report state

<img src="diagrams/03_skill_facades.svg" alt="Skill facades" style="border: 1px solid #dadce0; border-radius: 8px; max-width: 100%;" />

The coaching agent uses two layers rather than calling 60+ raw TrainingPeaks MCP tools directly:

1. **Skills** (`skills/*/SKILL.md`) hold the coaching protocol and output template for each task, loaded on demand via `load_skill`.
2. **Facade tools** (`tools.py`): each skill has one facade function that runs MCP calls, Open-Meteo lookups, and Firestore reads in parallel, computes physiological metrics in deterministic Python, and returns a compact summary.
   - `fetch_checkin_data` and `fetch_trend_data` also write structured JSON payloads (`checkin_report_data` and `trend_report_data`, `version: 1`) into `tool_context.state` via `utils/report_data.py`. The Cloud Run Web App BFF extracts these whitelisted `stateDelta` keys from `/run_sse` and streams `event: report` frames so interactive charts (PMC, CTL ring, weekly km, aerobic efficiency, load-capacity ladder) render from the exact numbers used in the prose.

<img src="diagrams/04_tool_call_sequence.svg" alt="Tool call sequence" style="border: 1px solid #dadce0; border-radius: 8px; max-width: 100%;" />

---

## 3. Integrations, credentials, and data

- **TrainingPeaks & Cloud KMS:** Runners upload their `Production_tpAuth` cookie in the Web App. The backend validates it live against TrainingPeaks and encrypts it with Cloud KMS (`AAD = b"users/{runner_id}"`) into `users/{runner_id}/private/trainingpeaks`. Inside Agent Runtime, `services/tp_credentials.py` decrypts the runner's cookie (5-minute TTL cache) and `services/tp_mcp.py` maintains an LRU pool of `tp-mcp` stdio toolsets keyed by cookie hash.
- **Open-Meteo:** Geocoding (cached on the profile), exact-hour historical run weather, and forecasts for fueling/schedule audits.
- **Firestore (`running-coach` Enterprise DB):**
  - `users/{runner_id}`: runner profile + `email` (indexed via `google_firestore_index.users_by_email`).
  - `users/{runner_id}/private/trainingpeaks`: KMS ciphertext + metadata (`tp_athlete_id`, `tp_name`, `kms_key_version`).
  - `users/{runner_id}/training_log/{workout_id}`: structured workout history indexed by date (`google_firestore_index.training_log_by_date`).
  - `users/{runner_id}/workout_analyses/{workout_id}`: 90-day TTL projection cache (`google_firestore_field.workout_analyses_ttl`).

---

## 4. Deployment and security

<img src="diagrams/05_deployment.svg" alt="Deployment" style="border: 1px solid #dadce0; border-radius: 8px; max-width: 100%;" />

- **Terraform** provisions APIs, two least-privilege service accounts (`running-coach-agent` with `cryptoKeyDecrypter` and `running-coach-web` with `cryptoKeyEncrypter`), the `running-coach/tp-cookie` KMS key, Firestore Enterprise indexes/TTL, and `gs://traces_runningagent`.
- **`deploy.sh --target ge|web|both`** always deploys the shared agent to Agent Runtime via `agents-cli deploy`, then conditionally registers in Gemini Enterprise (`ge|both`) and/or deploys `running-coach-web` to Cloud Run with Direct IAP (`--no-allow-unauthenticated --iap`) via `webapp/deploy.sh` (`web|both`).
- **Defense-in-depth auth:** Cloud Run Direct IAP gates access via IAM (`roles/iap.httpsResourceAccessor`), and the FastAPI backend independently verifies the `X-Goog-IAP-JWT-Assertion` ES256 signature and audience on every `/api/*` call.

## 5. Observability

- **OpenTelemetry → Cloud Trace / Logging** for end-to-end latency visibility.
- **Privacy-preserving telemetry (`NO_CONTENT`)**: prompts and completions are uploaded as JSONL to `gs://traces_runningagent/completions/` rather than emitted in trace attributes.

---

*Diagrams are written in d2 (`docs/diagrams/*.d2`). To regenerate them:*

```bash
cd docs/diagrams && for f in *.d2; do d2 --layout=elk "$f" "${f%.d2}.svg"; done
```
