Read @neuro-symbolic-level-designer/z_legend_game/AGENTS.md and @neuro-symbolic-level-designer/ARCHITECTURE.md
sections 1.2, 7 and 8. Look at the running API in `backend/app/main.py` for the exact request and response shapes.

## Goal
Build the Level Designer screen in the Flutter web app. The user enters a prompt, chooses a spritesheet source,
optionally adds tilesets and maps, starts generation, watches the 3 pipeline stages, sees the result, and presses
**Try Out** to play the generated level, loaded from the backend at runtime.

All paths are relative to `neuro-symbolic-level-designer/z_legend_game/z_legend_game_flutter/`.
Do not change `backend/` except where section 1 says so.

## 1. Fix first: runtime loading does not work on the web (blocker)
`LevelSource.network` uses Flutter's `NetworkAssetBundle`, which uses `dart:io` `HttpClient`. `dart:io` HTTP does not
work on Flutter web, so "Try Out" would fail in the browser.
- Add the `http` package. Create `lib/game/level/http_asset_bundle.dart`: `HttpAssetBundle extends CachingAssetBundle`,
  constructor takes a base `Uri` and an optional `http.Client` (for tests). `load(key)` does `GET baseUrl.resolve(key)`,
  returns the bytes as `ByteData`, and throws a `FlutterError` with the URL and status code for non-200 responses.
- `LevelSource.network(Uri baseUrl, {http.Client? client})` uses `HttpAssetBundle`. Remove the `NetworkAssetBundle` use.
- Open issue from Log-17: `LevelLoader` uses a fixed `Vector2(64, 32)`. Use the map's `tileWidth` and `tileHeight`.

## 2. API client (`lib/designer/api/`)
- Read the base URL from `assets/config.json` (`apiUrl`).
- `level_api.dart` (uses `http`, injectable `http.Client` for tests):
  - `Future<List<AssetPack>> listAssetPacks()`
  - `Future<CreateJobResult> createLevel(LevelRequest request)`: `multipart/form-data` with `prompt`, `asset_pack`,
    and files under `spritesheets`, `tilesets`, `maps` (bytes + file name).
  - `Future<JobStatus> getJob(String jobId)`
  - `Uri bundleUrl(String jobId)` -> `<apiUrl>/api/levels/<jobId>/bundle/`
- Typed models (`models.dart`) for asset packs, job status (status, per-stage status, error code and message,
  warnings, summary), and validation errors (`422` body `{errors: [{field, message}]}` -> `ApiValidationException`).
- A network failure (backend not running) throws `ApiUnavailableException` with the base URL.

## 3. Level Designer screen (`lib/designer/level_designer_screen.dart`)
Follow the look of the existing start screen (dark background). The layout works from 800 px wide up; on wide
screens use two columns (inputs left, progress and result right).

**Inputs (input contract, ARCHITECTURE.md 1.2):**
- Prompt: multi-line text field, required, 1 to 2000 characters, with a character counter.
- Spritesheet source (required), two choices:
  - "Built-in asset pack" (default): a dropdown filled from `GET /api/asset-packs`, showing name and description.
  - "Upload spritesheets": pick 1 to 10 PNG files (use `file_picker` with `withData: true`, web compatible).
    Show an info note: "Custom spritesheet ingestion is not available yet. Use a built-in asset pack to generate
    a level." Uploads are still sent, so the backend returns the real result.
- Optional: "Existing tilesets" (`.tsx`, `.tsj`, up to 10) and "Existing maps" (`.tmx`, `.tmj`, up to 5).
  List the chosen files with a remove button each.
- Client-side checks that mirror the server (prompt length, file counts, extensions, 10 MB per spritesheet). The
  server stays the authority: show `422` field errors under the matching input.
- "Generate level" button, disabled while a job runs.

**Progress:**
- After `202`, poll `GET /api/levels/{job_id}` every 500 ms until `done` or `failed` (stop polling when the screen
  is disposed).
- Show 3 rows: "1. Data Ingestion", "2. Level Planning", "3. Execution", each with its state (pending, running,
  done, failed).
- On `failed`, show the error message. For `ingestion_not_implemented`, show: "Spritesheet ingestion is not
  available yet. Choose a built-in asset pack."
- Show job warnings.

**Result (on `done`):**
- The preview image from `<bundle_url>preview_level.png`.
- Summary: map size, tiles by material, entities by type, parsed legacy files.
- Do not show a playability or path validation badge. The backend does not report one yet.
- **Try Out** button: opens `GameScreen(source: LevelSource.network(bundleUrl))`. Esc returns to the designer with
  all inputs and the result still there.

**Backend offline:** if the asset pack list or a request fails with `ApiUnavailableException`, show
"Backend not reachable at <url>. Start it with: uv run uvicorn app.main:app --port 8000 (in backend/)" and a
"Retry" button.

## 4. App navigation
- Start screen: two buttons, "Level Designer" and "Play starter level".
- `GameScreen` takes a `LevelSource` (default: the bundled starter level). R restarts the same level from the same
  source.

## 5. Tests
- `test/http_asset_bundle_test.dart` with `package:http/testing.dart` `MockClient`: bytes and string loading, URL
  resolution against the base URL, non-200 throws.
- `test/network_level_loader_test.dart`: a `MockClient` serves the starter bundle files (read from the asset
  bundle in the test) for URLs under `http://test/api/levels/abc/bundle/`. `LevelLoader(LevelSource.network(...))`
  loads the map: 20 x 20, embedded tileset image loaded, 5 objects. This proves the Try Out loading path without
  a browser.
- `test/level_api_test.dart` with `MockClient`: asset pack list, create job (multipart fields and files present),
  `422` -> `ApiValidationException` with field errors, job status parsing, network error -> `ApiUnavailableException`.
- `test/level_designer_screen_test.dart` with a fake API: empty prompt shows an error; the happy path goes through
  the 3 stages and shows Try Out; `failed` with `ingestion_not_implemented` shows the message; backend offline shows
  the retry message.
- Keep all existing tests passing.

## Constraints
- Web only: no `dart:io` anywhere in `lib/`.
- Do not change the generated assets, `game-assets/`, `tools/`, `.bob/`, or the docs.
- Keep it small. No state management package; `StatefulWidget` or a `ChangeNotifier` is enough.

## Done when (from `z_legend_game_flutter/`)
- `dart analyze` 0 issues, `dart format --set-exit-if-changed .` passes, `flutter test` passes, `flutter build web`
  succeeds.
- `grep -rn "dart:io\|NetworkAssetBundle" lib/` returns nothing.
- Start the backend (`uv run uvicorn app.main:app --port 8000` in `backend/`) and the app
  (`flutter run -d web-server`), check both logs for errors, and report the result. Then list the manual browser
  checks for me: generate with the asset pack, the stages update, the preview shows, Try Out loads the level,
  Esc returns with inputs kept, two different prompts give different levels, and the upload-only error message.
