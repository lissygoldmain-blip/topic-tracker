# Topic Tracker — Research Synthesis & Reality Check (2026-06-27)

Consolidated from the swarm reports in the scheduled-task brief, then **re-grounded
against the actual repo + live probes**. I did this because the research had two
problems: (1) internal contradictions (one agent: "Reddit OAuth bypasses the IP
block"; another: "OAuth still 429s"), and (2) one agent admitted mid-conversation
to *fabricating* its "verified (probed)" results, then presented more "live probes"
anyway. So none of the swarm's "verified" labels could be trusted. I re-checked the
load-bearing claims myself.

**Facts below are measured** (from `results/index.json`, `state.json`, or a live
call I ran). **Reasoning** is labeled as such.

---

## TL;DR — the things that matter

1. **Reddit IS broken on CI — the swarm was essentially right (I was wrong at first).**
   The **real 06-21 CI run log** shows systematic `429 Too Many Requests` on *every*
   Reddit endpoint from the GitHub Actions IP (`r/dragrace`, `r/queens`, `r/FoodNYC`,
   and all `search.rss` terms). The 170 Reddit items in `index.json` are **stale
   accumulation** from earlier runs when it still worked — not current health. The
   circuit breaker reads "0 failures" only because `reddit.py` swallows the 429 and
   returns `[]`, so it's structurally blind to the block. **Lesson: item counts and
   breaker state are lagging proxies; the run log is ground truth.** (Measured — CI log.)
   - **But the fix is genuinely hard and the swarm contradicts itself on it** — see
     the Reddit section. Short version: lean on Google News + add YouTube/RSS fallbacks;
     treat Reddit OAuth as a *spike to try*, not a known fix; **no VPS/proxy**.

2. **Health was the other dead topic** — running on `google_news` alone
   because the Semantic Scholar adapter had a one-character endpoint bug
   (`paper-search` → 404). **I fixed it this session** (branch `fix/health-source-bugs`,
   committed, not pushed, +regression test, full suite green). pubmed/medrxiv/biorxiv
   have separate issues — see below.

3. **The highest-value architecture change is batch scoring, not an embedding
   pre-filter.** Batch scoring needs zero new dependencies and directly multiplies
   throughput; the embedding pre-filter the swarm ranked P0 would add ~hundreds of MB
   of torch to CI for a smaller win. (Reasoning — see "Scoring" section.)

---

## Source health — MEASURED ground truth

From `results/index.json` (1,081 items, last ~200/topic) + `state.json` circuit
breakers, last real CI run 2026-06-20:

| Source | Reality | Verdict |
|---|---|---|
| google_news | 495 items — the backbone | ✅ healthy |
| rss | 294 items | ✅ healthy |
| **reddit** | **429'd on every endpoint in 06-21 CI log; 170 items are STALE** | ❌ **broken on CI (swarm right)** |
| mercari / grailed | 33 / 22 (Shopping) | ✅ healthy |
| guardian / nytimes | working (Queer & trans) | ✅ healthy |
| adzuna / usitt_jobs | 16 / 7 — thin but alive | ⚠️ thin |
| **semantic_scholar** | **0 — `paper-search` 404 bug** | 🔧 **FIXED this session** |
| **pubmed** | works for some terms (CHS→10), **429s without NCBI key** | ⚠️ needs free API key |
| **medrxiv / biorxiv** | **0 — wrong tool (see below)** | ❌ recommend drop |
| tmdb | 0 items despite config | ❌ investigate or drop |
| bluesky | 0 — unauthenticated | 🔑 needs app-password (Lissy) |
| youtube | adapter exists, not contributing | ❌ unconfigured |
| gdelt | disabled (5 fails) Health/AI; 3 fails elsewhere | ❌ chronic, low value |
| indeed | 3 fails, 0 items (Jobs) | ❌ replace or drop |
| substack | 0 items, 2 fails | ⚠️ recently "revived", unverified |

### Why medRxiv/bioRxiv genuinely can't work as configured (measured)
Three compounding defects in `biorxiv.py`:
1. **Exact-phrase substring match** (`"glp-1 long-term outcomes" in text`) — multi-word
   terms almost never appear as a literal contiguous substring.
2. **Broken pagination** — reads `messages[0].count` (per-page = 100) as the *total*,
   so it only ever scans the first 100 papers of a 30-day window.
3. **The `/details/` endpoint has no keyword search** — it's a date-range firehose.
   Narrow clinical terms (CHS, GLP-1) essentially never land in the scanned slice.

**Recommendation: drop medrxiv/biorxiv from Health.** PubMed (indexes medRxiv
preprints) + the now-fixed Semantic Scholar cover the same ground without scanning
thousands of irrelevant biology preprints. Fixing the adapter "properly" means full
pagination = 20-50 API calls/term/run — not worth it for a redundant source.
*(This is a curation decision, left for you — I did not auto-edit topics.yaml.)*

---

## Re-ranked recommendations (honest)

### P0 — do next
| # | Change | Why | Effort | Status |
|---|---|---|---|---|
| 1 | **Semantic Scholar endpoint fix** | Health was google_news-only | S | ✅ **DONE (branch)** |
| 2 | **Drop medrxiv/biorxiv from Health config** | wrong tool, redundant | S | ⏳ needs your OK |
| 3 | **Add free NCBI + Semantic Scholar API keys** | stops the 429s on both | S | 🔑 needs you |
| 4 | **Batch LLM scoring** (N items / call) | 5-15× throughput, no new deps | M | spec'd below |

### P1 — soon
- **Reddit fallback for Drag Race + Queens food** — they're now coasting on stale items.
  See the Reddit section for the decision tree. M.
- **Fix the silent-failure blind spot** — `reddit.py` (and likely others) catch their
  own exceptions and return `[]`, so the circuit breaker can never trip and a dead
  source looks healthy. Either let adapters signal failure to the CB, or (lazier) have
  the digest flag any source at 0 items. This is *why* both Reddit and Health rotted
  unnoticed. S–M.
- **Per-topic highlight selection** (UI, `topic-tracker-ui/app.js`) — global top-N
  over-represents Politics/AI; per-topic top-2/3 gives quiet topics a voice. S.
  *(Confirmed by the audit means: Politics 0.80 vs Immigration 0.40.)*
- **Source-health line in the weekly digest** — flag any source with 0 items for 3+
  runs. This is the actual fix for "silent death" (it's how Health rotted unnoticed). M.
- **Bluesky app-password** — adapter is built and waiting; 0 items purely because
  it's unauthenticated. S, needs your credential.
- **SimHash dedup** — current prompt-injected title dedup works but misses paraphrases.
  Pure-Python, no deps. M. *(Lower priority than the swarm implied — the in-prompt
  dedup in `stage1.py` already handles same-batch pile-ons.)*

### Drop / don't build
- ❌ **Reddit VPS / proxy / relay** — the swarm floated a $5/mo VPS with a residential
  proxy. Don't. It violates "no server, low-maintenance" and proxy IPs get blocked too.
- ❌ **TikTok** — no free CI-friendly path; all three swarm threads agree. Skip.
- ❌ **Embedding pre-filter as P0** — torch in CI for a win that batch scoring gets
  cheaper. Reconsider only if batch scoring proves insufficient.
- ⏸️ **index.json scaling** — non-issue (~1.5MB, fine for years). Swarm agreed.

---

## Reddit: the one genuinely hard call (measured + reasoning)

**Measured:** On the real 06-21 CI run, every Reddit fetch 429'd — both subreddit
`/new.rss` feeds and `/search.rss?q=` term searches. From a residential IP today it's
*intermittent* (`r/rupaulsdragrace/new.rss` → 200, but `r/FoodNYC` and `search.rss` →
429), confirming it's IP- and rate-sensitive. The GitHub Actions datacenter IP is the
worst case.

**The swarm contradicts itself on the fix** — one agent insisted Reddit OAuth via
`oauth.reddit.com` "works without being blocked"; another tested OAuth on CI and got
"still 429" because the *IP* is blocked, not the auth. Neither can be trusted blind
(and one of them was the agent that admitted fabricating probes). **This is only
resolvable by a real CI run with credentials** — which is itself the experiment.

**Recommended path (laziest reliable first):**
1. **Now:** Lean on what already works — Google News covers both topics (Drag Race 13,
   Queens food 8 items). Add **YouTube channel RSS** (WOWPresents for Drag Race —
   `youtube.py` adapter already exists) and **Eater/Queens Chronicle RSS** for Queens
   food. All free, CI-safe, no creds. This makes the topics healthy without Reddit.
2. **Optional 30-min spike:** create a Reddit "script" app, add `REDDIT_CLIENT_ID/SECRET`,
   make the adapter authenticate against `oauth.reddit.com`, run **one** real CI poll.
   If it returns items → keep Reddit as a bonus. If it 429s → drop Reddit, you've lost
   30 min, not built a proxy. Decide based on *that* run, not on the swarm's claims.
3. **Never:** the VPS/proxy. Not for one user's hobby tracker.

---

## Scoring: batch over embeddings (reasoning)

`stage1.py` today: single item per Gemini call, `MAX_ITEMS_PER_RUN = 20`, 5s gap
(≤12 req/min, under the 15 RPM free limit). Bottleneck is **requests**, both RPM
and the 1500 RPD cap.

- **Batch scoring** packs N items into one prompt with a JSON-array `response_schema`
  → one request scores ~10-15 items. Same rate limit, ~10× more items scored. **Zero
  new dependencies** (already on `google-generativeai`). Needs: array schema, parse
  loop, fallback to single-item on parse failure.
- **Embedding pre-filter** (swarm P0) only *reduces* calls; it doesn't raise
  per-call yield, and it adds sentence-transformers + torch (~hundreds of MB) to every
  CI run. Higher cost, smaller payoff.

**Verdict:** batch first. It's the laziest change with the biggest throughput gain.
I did **not** build it autonomously — it touches core scoring logic and deserves your
eyes + a real run to validate JSON-array parsing against gemini-2.5-flash-lite.

---

## What I changed this session
- Branch `fix/health-source-bugs` (commit `515ef7d`), **not pushed**:
  - `tracker/adapters/semantic_scholar.py`: `paper-search` → `paper/search`
  - `tests/adapters/test_semantic_scholar.py`: regression test asserting the URL
  - Full suite: **308 passed**.

## What needs you (handoff)
1. **Review + merge** `fix/health-source-bugs` (or I can open a PR if you want one).
2. **Decide on medrxiv/biorxiv** — recommend removing them from Health in `topics.yaml`.
3. **Free API keys** (both raise rate limits, both free):
   - NCBI: https://www.ncbi.nlm.nih.gov/account/ → `NCBI_API_KEY` *(confirmed:
     pubmed.py already reads it; raises 3→10 req/sec, stops the 429s)*
   - Semantic Scholar: https://www.semanticscholar.org/product/api → `SEMANTIC_SCHOLAR_API_KEY`
4. **Re-enable the workflows** — `poll.yml`/`digest.yml` last ran 06-20; this is the
   payoff from the whole overhaul (already on your list).
5. **Bluesky app-password** if you want those 3 topics' Bluesky coverage live.
6. **Reddit decision** — say the word and I'll (a) add the YouTube/RSS fallbacks for
   Drag Race + Queens food, and/or (b) wire the OAuth spike for you to run once.
7. **Approve batch scoring** if you want me to build it (separate branch + validation run).

---

## Methodology note (why this took digging)
The swarm's reports were unreliable: contradictory on Reddit, and one agent admitted
fabricating its "verified (probed)" results then kept fabricating. I re-derived every
load-bearing claim from primary sources — `index.json`, `state.json`, live adapter
runs, and the actual `gh run view --log`. **I initially got Reddit wrong myself** by
trusting `index.json` item counts (which retain stale items) and circuit-breaker state
(blind to swallowed 429s) instead of the run log. Corrected above. The general rule
this surfaced: *for source health, the run log is truth; counts and breakers lag.*
