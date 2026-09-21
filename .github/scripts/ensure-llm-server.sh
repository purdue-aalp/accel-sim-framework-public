#!/bin/bash
# Make sure the local llama.cpp server is up before a step that uses opencode.
#
# The server runs on demand: purdue-aalp/github-ci's llm-server/ensure.py starts
# it if it is down, waits for it, and keeps it from idling out under this job.
# Concurrent jobs are fine. Where github-ci is not deployed (a fork's runner)
# this is a no-op, on the assumption that the server there is always on.

CI_DIR="${AALP_CI_DIR:-/scratch/tgrogers-disk01/a/tgrghci/github-ci}"
ENSURE="$CI_DIR/llm-server/ensure.py"

if [ ! -x "$ENSURE" ]; then
  echo "::warning::$ENSURE not found; assuming an always-on llama.cpp server"
  exit 0
fi
exec "$ENSURE" "$@"
