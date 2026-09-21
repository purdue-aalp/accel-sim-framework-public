# Issue triage: on-demand LLM server and past-issue lookup

Design notes for `.github/workflows/issue-triage.yml`. The constraints that
stop a wrong edit are in `.claude/rules/issue-triage.md`; this file holds the
reasoning and the numbers.

## Pipeline

```
issue opened
  -> dump issue.json, clone gpgpu-sim
  -> ensure-llm-server.sh          start the llama.cpp server if it is down
  -> issue_rag.py index + query    related-issues/<n>.md, top 6
  -> classify                      bug | question | other
  -> issue-related (judge)         duplicate-answered | related | unrelated
  -> question + duplicate-answered:  one issue-answer pass      (short path)
     question otherwise:             2 researchers + composer
     bug / other:                    issue-triage
  -> post comment, labels (+ possible-duplicate)
```

## On-demand server

The server is a 29 GB Q8 model on two V100s. From its log over 106 h
(2026-09-14 to 09-19): 187 requests in 8 bursts, 2.7 h busy — a 2.6% duty
cycle. No two bursts were less than an hour apart. With a 60-minute idle limit
it would have been up 10% of the time. A cold start costs 45 s of model load
plus the slurm queue, against jobs that run 4-25 minutes.

The launcher lives in purdue-aalp/github-ci (`llm-server/`, its README has the
protocol). What matters here:

- Every consumer calls `ensure.py` first. It is idempotent and safe under
  concurrent jobs: tested with three simultaneous callers on two hosts, one
  slurm job resulted.
- Idle detection reads the server's own `/slots`, so nothing depends on NFS
  visibility or on two hosts' clocks. A lease-file handshake was the first
  design and was dropped for exactly that reason: NFS caches negative lookups
  and mtimes for up to a minute.
- An idle server gives up its GPUs, and gpu01 has no GRES. `start-server.sh`
  refuses to load onto cards someone else is using and says which.

## Past-issue lookup

### Corpus

296 issues, 1.4 MB of text. 217 have a reply from a maintainer
(`author_association` OWNER/MEMBER/COLLABORATOR), 166 of those are closed. At
this size a vector database buys nothing: vectors are a 2.9 MB JSON file and a
query is a pure-Python dot product over 296 x 1024 floats (~50 ms).

Not indexed yet, and worth adding if recall disappoints: the 59 GitHub
Discussions, and upstream gpgpu-sim's 195 issues.

### Cards

One per issue: cleaned body, maintainer replies only, the reporter's last word,
state, labels, era. Cleaning matters more than the ranker. Pasted logs dominated
raw BM25 — an issue with a 300-line log matched every other issue with a long
log — so fenced blocks over 8 lines are cut to their first and last 3.

Only the question side (title + body) is embedded. The task is "has this been
asked before", which is question-to-question similarity; embedding the answers
too pulls in issues that merely mention the same files.

### Ranking

BM25 and embedding cosine, fused by reciprocal rank (k=60). RRF needs no score
calibration between the two. Candidates with cosine under 0.5 are dropped unless
BM25 ranks them in its top 3.

Embeddings: Qwen3-Embedding-0.6B (Q8, 640 MB), served by a second llama-server
in the same slurm job as the main model (port 8081). The CUDA build of llama.cpp
does not load on raid (no `libcudart`), which ruled out running it on the
runner's CPU without a second build. Full index build: 25 s. Incremental
refresh (GitHub `since=`): 1 s.

Measured cosine: random issue pairs p50 0.43, p90 0.59; genuine duplicates
0.57-0.87.

### How good is it

Ground truth is thin. Maintainer comments that reference an earlier issue give
15 pairs, and most are not duplicates — they are root-cause links ("this is the
`dst->empty()` assertion from #134") that no text similarity could find from the
new issue's body alone. On all 15: recall@6 is 0.40 for BM25, 0.33 for
embeddings. On the 5 that are real near-duplicates (F2FP undefined instruction
x2, L1 cache deadlock, PyTorch support, Jenkins paths), both rankers put the
match in the top 3, every time.

A paraphrased F2FP question ("simulator crashes: unknown opcode") retrieves all
four historical F2FP issues as its top four.

So: retrieval finds restated questions reliably, and does not find
same-root-cause-different-symptom. The second kind still goes through full
research, which is what happened before retrieval existed.

### Why a judge pass

Top-6 retrieval is mostly noise for a novel issue (for #558, all six candidates
were unrelated). Handing six irrelevant old threads to the researchers would
distract a 27B model more than help it. The judge reads only the issues, no
source, deletes what it does not vouch for, and costs about a minute.

`duplicate-answered` takes the short path only when the card also says a
maintainer answered; bash checks that, not the model. If the short pass yields
no `### Answer`, the workflow falls back to the full research path.
`ISSUE_RAG_SHORTCUT=0` (repo var) keeps retrieval as leads only.

### Eras

Every card carries `era: 1.x` or `2.x`, from its filing date against the v2.0.0
release (2026-08-25). 2.0 rewrote enough of the simulator and tracer that a 1.x
answer's specifics — paths, flags, configs, supported CUDA/GPU generations —
cannot be reused unverified, while its reasoning often still holds. Today all
but a handful of cards are 1.x, so in practice every reused answer is
re-verified against the 2.x tree, and the reply says what changed.

The era is the *issue's*, not the reporter's. A reporter may still be on 1.x;
the skill tells the agent to notice that and to say which version it verified
against, since only the 2.x trees are in the workspace.

### Safety

Old issue text is as attacker-controlled as new issue text. Agents stay
read-only with no shell; retrieval is a bash pre-step rather than a tool; cards
open with a line marking their content as data. The bot's own past comments are
excluded from cards so it cannot cite itself. The bot never closes an issue or
declares a duplicate: it labels `possible-duplicate` and links the old issue.

## Refuted / deferred

- **Keyword search only** (or letting the agent grep a directory of old issues):
  zero infrastructure, but misses paraphrases, and raw BM25 was dominated by
  logs.
- **Whole catalogue in the 262k context** instead of retrieval: fits today
  (~25k tokens of one-line summaries) but costs a minute of prompt eval per
  issue and grows linearly.
- **LLM-distilled Q/A summaries per card**: ~220 calls at 18 tok/s for the first
  build. Deferred; cleaned raw text retrieves well enough.
- **A separate index-refresh workflow**: unnecessary at 1 s per incremental
  refresh inside the triage job, and it removes staleness as a failure mode.
