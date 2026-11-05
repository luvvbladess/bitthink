# Local conversations link — 3 November 2026

Reviewed new desktop_link API/hub, client presence channel and renderer command handling, website ComputerLink and OrchestratorTools. Fixed clearing previous-account snapshot on logout/server change; queued commands stop after link termination/replacement; malformed list snapshots and non-object protocol frames no longer disconnect the link. Website link/detail queries are scoped by account and selected session state remounts per account.

Added always-available Бит Клиент entry in chat sidebar, independent of answer mode. Drawer explains automatic connection, same-account login, open client/project, offline state and Windows download. Desktop 1440px/mobile 390px functional and visual checks passed; no overflow, close/download work. Impeccable detector returned no findings.

Backend targeted tests and full baseline/candidate checks: 1335 baseline vs 1349 candidate, same 29 pre-existing failures, no new failures. Client unit tests check local-only payload without file paths/tool arguments, queue, deny approval and missing session. Native dev and packaged 0.9.8 tests prove project snapshot, website create command, real local runner, result snapshot, logout. Full Windows package checks pass. Real public update feed and full NSIS download pass client/library SHA-512 verification, without installation into user profile.

Backend + worker + site deployed with backups /opt/gpt-ultra-web/.backups/local-link-20261102T233415Z and /opt/gpt-ultra-web/.backups/link-discovery-20261102T233834Z. Website assets/index/source published; old hashed assets retained. Release verifier passed. BitClient 0.9.8 published, SHA256 3d6975db179d4be8fad4a112e20046be0ebd1e53464056854fd3e5c2a5a94e0d. Publication backup /opt/gpt-ultra-web/.backups/bitclient-20261102T233510Z.

The link is presence-based: client must stay open; this is not a durable cloud backup of all local history. Snapshot shows up to 20 recent local sessions and 16 clipped messages; complete histories/files/drafts stay local. No new database migration. Frontend built on local E drive because cloud-drive dependency extraction failed; successful build and deployed bundle verified.
