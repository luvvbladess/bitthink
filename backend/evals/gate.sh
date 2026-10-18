#!/bin/sh
# Run inside the candidate backend image before activation. Model/API calls are
# deliberately absent; live regression selection is a separate explicit job.
set -eu
python -m evals.quality --report "${1:-/tmp/bitthink-quality.json}"
