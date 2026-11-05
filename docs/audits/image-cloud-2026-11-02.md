# Image routing in cloud Orchestrator — 2026-11-02

The previous fix excluded computer_task_id turns, so actual background Orchestrator jobs still used tools and SVG. Ordinary chat and cloud jobs now enter the image executor; local computer automation remains separate. Image responses use the shared raster-plus-HTML-canvas pipeline. Follow-up edits reuse persisted image bytes. Explicit SVG source requests retain their code workflow.

Real provider acceptance used isolated SQLite/uploads with computer_task_id bound and director mode: Russian PC-services cover generated as a 1,786,080-byte raster plus canvas; follow-up “у тебя нижнее устройство плохо получилось. поправь пж” produced a new 1,295,551-byte raster plus canvas. Both outputs checked for PNG/JPEG signatures, persisted image metadata and HTML img, with no SVG deliverable. Evidence: output/image-cloud-2026-11-02/results.json.

Full Linux baseline and candidate: 1335 collected cases each, same 29 pre-existing failures, no new failures. Candidate built from the current backend image. Before deployment backend and worker were on different images; both have now been recreated with the tested candidate. Queues idle, services healthy, release verifier and source hash checks passed. Backup: /opt/gpt-ultra-web/.backups/image-cloud-20261102T205439Z. No client installer change required.
