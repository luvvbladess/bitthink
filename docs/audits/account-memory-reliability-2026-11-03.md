# Account memory reliability — 2026-11-03

Scope: persistent account profile across private chats: self-declared profession and knowledge level, explicit/repeated interests, language, tone, format and answer length.

Changes:
- Collect bounded chronological user history across owned private conversations; exclude shared rooms, other authors, secrets and explicitly temporary requests.
- Extract a full updated profile, highlight the latest message when resolving contradictions, omit unknown fields. A topic must be explicit or appear across two chats; profession cannot be inferred from a question.
- Compare the original memory row before writing; stale background extraction cannot overwrite a manual edit, clear or disable.
- Clear/manual edits create a source cutoff so deleted facts are not relearned from old messages. No schema migration.
- Coalesce background tasks and defer explicit preference updates within the debounce window rather than losing them. Answers are not blocked by memory extraction.
- Include enabled memory in the bounded DOCX writing path as well as existing chat/orchestrator paths.

Validation uses isolated SQLite fixtures and synthetic users; no production account profiles were read or modified. Actual model results and baseline/candidate comparison are retained under output/account-memory-2026-11-03. The full repository suite has pre-existing failures; the release gate requires zero newly failing cases, plus successful real-model acceptance. This does not make inferred interests infallible: the profile is bounded, asynchronous, editable and subordinate to the current request.


The original Nano extractor failed actual-model acceptance (temporary Word request stored as permanent profile, outdated short-answer preference retained, repeated interests omitted). Source filtering and latest-message precedence were hardened; extraction now uses Luna with a bounded 2000-token output, existing debounce and two-hour ordinary refresh interval. This adds a small background model call, without an embedding dependency.

Full test comparison: baseline 1355 cases / 28 pre-existing failures; candidate 1361 cases / the same 28 failures; zero new failures. Focused memory and DOCX tests pass within that suite. Actual-model acceptance verifies self-declared profession, interests and Python level; preferred Russian/short/practical replies in a fresh chat; replacement by detailed replies; no one-off persistence after clear; recurring topics without invented profession; account separation; disabled memory remaining unchanged.


Deployment completed: 2026-11-03T18:50:29.141647+00:00. Backup: /opt/gpt-ultra-web/.backups/account-memory-20261103T185008Z. Both backend and worker are healthy and run the tested image. Two independent actual-model acceptance runs passed, followed by deployed-module smoke checks and the published-release readiness check.
