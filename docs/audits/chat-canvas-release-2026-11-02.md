# Unified chat canvas — 2026-11-02

## Behaviour

Studio is removed from the public mode selector. Saved Studio selections migrate to Auto. A direct request to build a site, slides, infographic or UI prototype chooses the existing artifact executor for that turn; it does not change the user's saved chat mode. Full applications with a backend continue through the project executor. Existing plan restrictions and usage accounting remain in effect.

The canvas appears when an assistant artifact is available. Desktop keeps the resizable panel; mobile uses a full-screen drawer. Closing is remembered per conversation for the browser session, including subsequent previews, navigation and reload. An attachment card reopens the selected version. Ordinary images and uploaded HTML do not automatically open a canvas.

Edits carry an explicit `canvas_target` through the durable generation request. It must belong to an assistant artifact in the bound conversation. Multiple saved outputs without a selection prompt the user to open the intended work. Creating a new work never silently reuses the previous HTML. Old versions remain immutable and can be selected for editing.

## Validation

- Targeted backend checks: 191 passed, zero failures/errors (`output/chat-canvas-2026-11-02/backend-tests.xml`).
- Final focused backend rerun, including a short noun-only edit submitted from the canvas form: 30 passed. The form makes its edit intent explicit before dispatch.
- Linux candidate: 1,326 cases versus 1,296 on the deployed baseline. Both have the same 26 existing failures; zero new failures (`test-comparison.json`). The full backend suite is therefore **not** claimed to be green.
- Production bundle: 8 new canvas checks plus 10 existing canvas/version checks, at 320–1440 px and in light/dark themes.
- General browser suite: 180 distinct cases passed. The run was resumed after updating obsolete expectations for Studio suggestions and the presentation starter; the two final log segments contain 92 and 88 passing cases. The final production canvas rerun covers the subsequent one-line edit-intent correction. No browser exceptions occurred in the successful runs.
- Export: HTML, PNG, PDF, PPTX and full-height PNG/PDF.
- Real model acceptance in isolated storage: site creation (24.8 s), exact-source edit preserving menu/prices/address (15.2 s), independent infographic (22.7 s). All three persisted usable HTML; selected mode stayed Auto, and the old file hash stayed unchanged. Estimated text-model cost for this successful run: $0.1087. This is a synthetic acceptance run, not a production latency or price guarantee.
- Initial acceptance harness failed because it compared text across nested HTML spans without normalising whitespace. The actual edit was correct. The harness was corrected and the complete three-step run passed.
- Interface checks explicitly cover first-preview timing, closing, later updates, navigation/reload, old-version selection, exact edit targets, legacy Studio preferences, inline images and uploaded HTML.

## Release boundaries

The release uses the existing frontend branding/navigation and export implementation from the server. Unrelated local changes to BrandMark and studioExport are preserved in the working folder and excluded from publication. The normalised theme file matches the server. The release source manifest contains only the 23 relevant runtime files.

Backend candidate is based on the current deployed image, retaining the bounded Qwen embedding integration and schema 025. There are no database migrations or environment changes. Publication verifies source hashes and idle queues, backs up the previous application and frontend, retains old hashed assets for open tabs, swaps the frontend entry document last, and rolls back on a failed release check.

## Deployment

Published at 2026-11-02 04:04:08 UTC (07:04 Moscow). Backup: `/opt/gpt-ultra-web/.backups/chat-canvas-20261102T040342Z`. Public routes, exact frontend entry hash, immutable asset caching, API readiness, worker readiness, runtime source hashes, hidden Studio mode, enabled Qwen retrieval and schema 025 all passed verification.

Post-publication browser verification against the public origin: all 8 new canvas scenarios passed, with API fixtures to avoid writes to real accounts. This checks the published assets and browser headers; the earlier isolated real-model run checks generation and persistence.

An initial release check imported a legacy API module without the normal configuration bootstrap. Although public availability checks passed, the release script correctly restored the previous application and frontend. The check was corrected to load application configuration first; the second publication and all release checks passed. No user data or environment settings were changed.

Detailed evidence: `output/chat-canvas-2026-11-02/` (ignored local test artifacts), including `deployment.json`, `checks.json`, both browser-suite segments, production canvas logs and real-model artifacts.
