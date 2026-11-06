# AI Running Coach — Cloud Run Web App (`webapp/`)

This directory contains the web UI and FastAPI BFF for the **AI Running Coach**, deployed to **Cloud Run** behind **Identity-Aware Proxy (IAP)** and backed by **Vertex AI Agent Runtime**.

---

## Architecture

- **Frontend (`frontend/`)**: React 19 + TypeScript + Vite + Tailwind v4 + lazy-loaded Recharts (`@fontsource/space-grotesk` & `@fontsource/inter` self-hosted for strict CSP), organized into `src/app/` (shell & conversation), `src/features/{check_in_report,trend_analysis,schedule_audit,profile}/`, and `src/shared/`.
- **Backend (`backend/`)**: FastAPI + Uvicorn serving static SPA assets and `/api/*`:
  - Verifies Cloud Run Direct IAP ES256 JWT assertions (`X-Goog-IAP-JWT-Assertion`) against Google's public JWK keyset.
  - Reads and edits runner profiles in Firestore (`users/{runner_id}`), keeping `firstname`, `lastname`, and `email` immutable.
  - Validates `Production_tpAuth` cookies live against TrainingPeaks and encrypts them via **Cloud KMS** (`AAD = b"users/{runner_id}"`) into `users/{runner_id}/private/trainingpeaks` (the web SA holds `roles/cloudkms.cryptoKeyEncrypter` only — it cannot decrypt).
  - Streams coaching turns from Vertex AI Agent Runtime (`/run_sse`) as clean browser Server-Sent Events (`session`, `status`, `tool`, `delta`, `report`, `message`, `error`, `done`) with 15-second keepalive heartbeats.

---

## Local Development

### 1. Frontend Demo Mode (no backend or GCP credentials required)

```bash
cd frontend
npm install
npm run dev:demo
```

Open `http://localhost:5173` (supports `?view=ready`, `?view=onboarding`, `?view=checkin`, `?view=trend`, `?view=audit`, and `?view=profile`).

### 2. Full Local Stack (FastAPI Dev Mode + Vite Proxy)

```bash
# Terminal 1 — Backend on :8080 (loopback-only AUTH_MODE=dev)
cd backend
AUTH_MODE=dev \
DEV_USER_EMAIL=cyrille@cyvisser.altostrat.com \
GOOGLE_CLOUD_PROJECT=firestore-cyvisser \
FIRESTORE_DATABASE=running-coach \
AGENT_RUNTIME_RESOURCE="projects/840839653849/locations/europe-west4/reasoningEngines/2937164993696628736" \
TP_COOKIE_KMS_KEY="projects/firestore-cyvisser/locations/europe-west4/keyRings/running-coach/cryptoKeys/tp-cookie" \
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

# Terminal 2 — Frontend on :5173
cd frontend
npm run dev
```

---

## Tests

```bash
# Backend behavioural tests (4 tests)
cd backend && pytest tests/ -q

# Frontend co-located tests (5 tests) + TypeScript production build
cd frontend && npm test -- --run && npm run build
```

---

## Production Deployment

From `running_coach/`:

```bash
# Deploy Agent Runtime + Cloud Run Web App (IAP enabled)
./deploy.sh

# Or deploy Web App only (reusing existing Agent Runtime revision)
./webapp/deploy.sh
```

Grant an IAM user access through Cloud Run IAP:

```bash
gcloud iap web add-iam-policy-binding \
  --project=firestore-cyvisser \
  --resource-type=cloud-run \
  --service=running-coach-web \
  --region=europe-west4 \
  --member="user:cyrille@cyvisser.altostrat.com" \
  --role="roles/iap.httpsResourceAccessor"
```
