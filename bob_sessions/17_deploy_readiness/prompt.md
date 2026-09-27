Read `backend/app/main.py`, `backend/app/jobs.py`, `backend/pipeline/llm/config.py`,
`backend/pipeline/execution/verification.py` (the `dart_analyze` check), `backend/codegen_check/pubspec.yaml`, and
`z_legend_game/z_legend_game_flutter/lib/designer/api/level_api.dart` (paths relative to `neuro-symbolic-level-designer/`).

## Working rules (token budget)
Write code plus small unit tests for the new logic only. **Do not run anything** (no tests, no builds, no
`docker build`, no deploys): I run everything and report errors back. Report briefly.

**Secrets:** never read, print, copy, or bake `.env` or `creds.json` into anything. They must be excluded from the
Docker build context.

## Goal
Deploy the backend to Google Cloud Run and the Flutter web build to Vercel, behaving exactly like localhost
(live Gemini on Vertex AI, uploads, default grassland pack, Try Out, bundle download, `dart_analyze` check passing).

## 1. Credentials: Application Default Credentials (`config.py`)
- If `GOOGLE_APPLICATION_CREDENTIALS` is **unset**, use Application Default Credentials (on Cloud Run: the service
  account). If it is set, keep today's checks (file must exist). `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`,
  `LLM_MODE`, model settings still come from the environment.
- Make sure the Gemini client is created without a credentials file in that case.
- Tests: config without `GOOGLE_APPLICATION_CREDENTIALS` in live mode is valid; set but missing file still fails.

## 2. CORS (`main.py`)
- Keep the localhost regex. Add origins from `CORS_ORIGINS` (comma-separated exact origins, e.g.
  `https://my-app.vercel.app`). Test: an allowed origin gets the CORS header, an unknown one does not.

## 3. Frontend API URL (`level_api.dart`)
- `--dart-define=API_URL=https://...` wins over `assets/config.json` when non-empty; `config.json` stays the local
  default. Small test for the precedence (inject the define value through a parameter).

## 4. Backend container (`backend/Dockerfile`, `.dockerignore`)
- Build context: `neuro-symbolic-level-designer/` (the image needs `backend/` and `game-assets/`, and whatever
  `asset_packs` reads; check the paths the app resolves at runtime).
- Python version and dependencies as used locally (same lock/requirements). Run `uvicorn app.main:app` on
  `0.0.0.0:$PORT` (default 8080), one worker.
- **Flutter SDK in the image** (stable, same version as the local `flutter --version`, pinned) so the `dart_analyze`
  check runs; run `flutter pub get` in `backend/codegen_check/` at build time, so no network is needed at runtime.
  Keep the Flutter layer before the app code layer for caching.
- `.dockerignore`: `.env`, `creds.json`, `**/*.zip`, `backend/data/`, `.venv`, `**/build/`, `**/.dart_tool/`
  (except what the image builds itself), `z_legend_game/`, `eval/` outputs if large, `.git`.
- Data dir: keep `backend/data` (Cloud Run's in-memory disk; fine for one instance). If the app writes elsewhere, say so.

## 5. Vercel config
- `z_legend_game/z_legend_game_flutter/vercel.json` for a static deploy of `build/web` (no build command; the
  developer builds locally with `flutter build web --release --dart-define=API_URL=...`). Add cache headers only if
  trivial.

## Done when
The code is written, and the report lists the environment variables the Cloud Run service needs.

---

## Prompt 2: finish task 17

Same rules: write code only, **do not run anything**. Report briefly.

Review: sections 1, 2 and 4 are done and fine. Missing:
1. **Section 3:** `level_api.dart`: `const String.fromEnvironment('API_URL')` wins over `assets/config.json` when
   non-empty (inject the value through a parameter of `fromConfig` for the test). Add one small test.
2. **Section 5:** skip `vercel.json` (we deploy `build/web` directly; no config needed).
3. `verification.py`: `DART_TIMEOUT_S` from the environment variable `DART_TIMEOUT_S`, default 120 (the first cold
   `dart analyze` on Cloud Run can be slower than locally).
