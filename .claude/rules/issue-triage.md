---
description: Issue-triage workflow, on-demand LLM server, and past-issue retrieval
paths:
  - ".github/workflows/issue-triage.yml"
  - ".github/scripts/issue_rag.py"
  - ".github/scripts/ensure-llm-server.sh"
  - ".github/skills/issue-triage.md"
  - ".github/opencode/agent/issue-*.md"
---

# Issue triage: on-demand LLM server and past-issue lookup

Design, measurements and refuted options: `docs/issue-triage-rag.md`. Read it
before redesigning any of this.

## LLM server

- The llama.cpp server is **on demand** (purdue-aalp/github-ci, `llm-server/`):
  it exits after 60 idle minutes. Every workflow step that runs `opencode` must
  be preceded by `.github/scripts/ensure-llm-server.sh`, or it finds no server.
- Concurrent jobs share one server. Never start, stop or health-gate it from a
  workflow by any other means; `ensure.py` owns the race handling.
- Repo vars must not start with `GITHUB_` (reserved) — hence `AALP_CI_DIR`.

## Past-issue lookup (`issue_rag.py`)

- **Standard library only.** It runs under the runner's bare `python3`.
- **Never fatal.** No token, no embedding server, empty index: triage must still
  run exactly as it did before retrieval existed. Embeddings are optional; BM25
  alone is the fallback.
- The index directory is shared by all runners on the host. Writers hold the
  `flock`; files are replaced atomically because readers take no lock.
- Cards exclude bot and `🤖 **AI …` comments, or the bot learns from itself.
  Only `OWNER`/`MEMBER`/`COLLABORATOR` replies count as an answer.
- Changing card text, `embed_text()` or the embedding model: bump `SCHEMA` or
  the `--embed-model` label so stored vectors are rebuilt, never mixed.
- `ERAS` holds the release dates that split 1.x from 2.x. Add the next major
  release there; the skill's "Past issues" section explains eras to the agents.

## Agents

- All agents stay read-only (`bash: false`): issue text, old and new, is
  attacker-controlled. Retrieval is a bash pre-step, not an agent tool.
- A past issue is a lead to verify against the current tree, never evidence.
- `duplicate-answered` needs the judge's verdict **and** `answered by a
  maintainer: yes` on the card; bash enforces the second. The short path falls
  back to full research when it yields no `### Answer`.
- The bot never closes or calls an issue a duplicate. `possible-duplicate` is a
  label the workflow adds; a maintainer decides.
