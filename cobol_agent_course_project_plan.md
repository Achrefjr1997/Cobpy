# COBOL → Python 3 Agentic Migrator — Course Project Plan

**Stack at a glance:** LangGraph agent · FastAPI backend · Vite + React frontend
**Focus areas:** (1) a robust agentic loop, (2) layered validation of generated code
**Deliberately out of scope:** Docker sandboxing, k8s, vector-DB memory, multi-dialect support, enterprise observability

---

## 1. What We're Building

An AI agent that takes COBOL source — as a snippet, a file URL, or a Git repo — and produces a working Python 3 translation plus a test suite that demonstrates the translation behaves the same as the original.

It's **agentic, not a pipeline**: the LLM decides at every turn what to do next (translate? test? reflect? re-translate?) based on a shared state object. There is no fixed sequence of stages.

The user interacts with it through a Vite + React frontend that talks to a FastAPI backend, which runs the LangGraph agent and streams progress back to the UI.

---

## 2. Scope

### In
- Three input modes: paste snippet, paste a URL to a `.cbl` file, paste a public GitHub URL.
- Agentic loop driven by LangGraph with full state-based memory.
- Multi-technique validation (see §5 — this is the intellectual core).
- FastAPI backend exposing REST + Server-Sent Events (SSE) for live agent progress.
- Vite + React frontend with code editor, live agent trace, and results view.
- SQLite for run history.

### Out (we explicitly skip these)
- Docker / containerized sandboxes — we run generated Python in a subprocess with a timeout and that's enough for a course project.
- Auth, user accounts, rate limits.
- Private repos, cloud buckets, multi-dialect parsing.
- Cross-run learning / vector memory.

---

## 3. System Architecture (Simple)

```
┌──────────────────┐   HTTP + SSE   ┌──────────────────────┐
│  Vite + React    │ ◀────────────▶ │   FastAPI backend    │
│  frontend        │                │                      │
│                  │                │  ┌────────────────┐  │
│  - input form    │                │  │ LangGraph      │  │
│  - live trace    │                │  │ agent          │  │
│  - result view   │                │  │                │  │
└──────────────────┘                │  │  state ←→ nodes│  │
                                    │  └───────┬────────┘  │
                                    │          │           │
                                    │   ┌──────▼────────┐  │
                                    │   │ subprocess    │  │
                                    │   │ runner + GnuCOBOL │
                                    │   └───────────────┘  │
                                    │                      │
                                    │   SQLite (runs log)  │
                                    └──────────────────────┘
```

Three clear layers. No orchestration frameworks, no queues. A run is just a long-lived FastAPI request that streams events.

---

## 4. The Agentic Loop (Focus Area 1)

### 4.1 Why agent, not pipeline

A pipeline would be `parse → translate → test → done`. Our agent instead has a **planner node** that reads the whole state and picks the next action every turn. This lets it loop: translate → test → (tests fail) → reflect → translate again → test → done. It backtracks when needed. That's the whole point.

### 4.2 State (this IS the memory)

One `TypedDict` passed through every node. Every decision reads from and writes to it.

```
AgentState {
  # Input
  source_type: "snippet" | "url" | "repo"
  source_ref: str
  cobol_source: str                    # the actual code

  # Understanding
  program_summary: str | None          # plain-English what it does
  io_contract: dict | None             # {inputs: [...], outputs: [...]}

  # Translation
  python_drafts: list[Draft]           # history of attempts, each with an id
  current_draft_id: str | None

  # Tests & validation
  generated_tests: str | None
  test_runs: list[TestRun]             # each run's pass/fail + stderr
  validation_scores: dict              # results from each validation technique

  # Agent cognition (crucial)
  plan: str                            # planner's current thinking
  tool_call_history: list[ToolCall]    # avoid repeating failures
  lessons_learned: list[str]           # things the reflector wrote down
  next_action: str                     # planner's emitted decision
  step_count: int
  step_budget: int                     # hard cap, e.g. 25
  done: bool
  error: str | None
}
```

The key insight: **because history is in state, the planner can see what it already tried and avoid repeating it.** That's where "robustness" comes from.

### 4.3 Nodes

| Node | What it does |
|---|---|
| `planner` | LLM. Reads state, emits `next_action` ∈ {ANALYZE, TRANSLATE, GEN_TESTS, RUN_TESTS, VALIDATE, REFLECT, FINISH}. |
| `analyze` | LLM. Produces `program_summary` and `io_contract` from the COBOL source. |
| `translate` | LLM. Emits a new Python draft (or patches the current one). Appends to `python_drafts`. |
| `gen_tests` | LLM. Produces `pytest` tests from `io_contract`. |
| `run_tests` | Tool. Runs Python + pytest via subprocess with timeout, captures output. |
| `validate` | Tool + LLM. Runs the validation stack from §5 and updates `validation_scores`. |
| `reflect` | LLM. Reads failures, writes a `lesson_learned`, suggests whether to re-translate, re-test, or give up. |
| `finalize` | Writes the final artifacts to SQLite, sets `done=True`. |

### 4.4 Graph topology

Every node returns to `planner`. The planner's conditional edge routes based on `next_action`. That cycle — state updated, planner re-reads, planner chooses — is the loop.

```
        ┌──────────────┐
   ┌───▶│   planner    │────┐
   │    └──────────────┘    │
   │            │           │
   │      (conditional)     │
   │            │           │
   │   ┌────────┼────────┐  │
   │   ▼        ▼        ▼  ▼
   │ analyze translate ... finalize → END
   │   │        │        │
   └───┴────────┴────────┘
```

### 4.5 Robustness guards (these are what make it "robust")

- **Step budget.** Hard cap of ~25 planner turns. After that, force `FINISH` with whatever we have.
- **Repeat detection.** If the last 3 `tool_call_history` entries are identical, the planner is forced to reflect instead of acting.
- **Lessons feedback.** Every `reflect` call appends to `lessons_learned`, and the planner prompt always includes that list. So "we already tried X and it failed because Y" stays visible.
- **Draft versioning.** Translations are never overwritten — each attempt is a new `Draft` with an id. The agent can roll back to an earlier draft.
- **Structured planner output.** Planner returns JSON (`{reasoning, next_action, target_draft_id}`). If the LLM returns malformed JSON, we retry once, then force `REFLECT`.
- **Escape hatch.** If `step_count` reaches budget and nothing is passing, the agent still returns the best draft + the validation report honestly labeled as "unverified."

---

## 5. Validation Techniques (Focus Area 2)

This is the academically interesting part. No single technique is enough — we stack four, and the `validate` node runs them and writes each score to state. The `reflect` node uses the combined picture to decide what to do next.

### 5.1 Differential testing against GnuCOBOL
Compile the original COBOL with `cobc` (GnuCOBOL), run it on generated inputs, capture stdout. Run the Python translation on the same inputs. Compare outputs exactly (with tolerance for numeric rounding). **This is the strongest signal of behavioral equivalence** — it's ground truth, not LLM opinion.

### 5.2 Property-based testing with Hypothesis
For numeric/string routines, use `hypothesis` to generate random inputs within the domains declared in `io_contract`. Assert invariants the agent extracted during `analyze` (e.g., "output is monotonic in input", "output length ≤ input length"). Catches edge cases hand-written tests miss.

### 5.3 LLM-as-judge (semantic equivalence)
A separate LLM call reviews the COBOL and the Python side-by-side and answers structured questions: *Do they compute the same thing? Any control-flow differences? Any data-type risks?* Returns a score + rationale. This catches cases where tests pass but the translation is still subtly wrong (e.g., wrong rounding mode for `COMP-3`). Weaker evidence than §5.1 but catches different things.

### 5.4 Static sanity checks
Run `ruff` and `pyflakes` on the Python. Also parse the Python AST and check basic structural expectations from `io_contract` (e.g., "a function named `main` exists", "it takes N arguments"). Cheap, fast, filters obviously broken drafts before we spend tokens on semantic review.

### 5.5 Combined verdict
The `validate` node writes:
```
validation_scores = {
  differential: {passed: 18, failed: 2, details: [...]},
  property:     {passed: 45, failed: 0},
  llm_judge:    {score: 0.8, concerns: ["rounding in line 34"]},
  static:       {ruff_errors: 0, structural_ok: true},
}
```
The `reflect` node reads this and classifies: `equivalent` / `likely_equivalent` / `partial` / `broken`, and decides next action. The thresholds are simple rules (e.g., differential fail-rate > 10% → `broken`, else look at LLM-judge).

This layered validation is the project's biggest contribution — most student projects stop at "the code compiles." We actually check behavior.

---

## 6. FastAPI Backend Design

Small and deliberate. Three endpoints are enough.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/migrations` | Start a new migration run. Body: `{source_type, source_ref_or_code}`. Returns `run_id`. |
| `GET` | `/api/migrations/{run_id}/events` | **SSE stream.** Emits agent events (planner decisions, draft updates, test results, lessons) as they happen. |
| `GET` | `/api/migrations/{run_id}` | Final result: Python code, test suite, validation report, full trace. |

Optional: `GET /api/migrations` for history.

**Why SSE over WebSockets:** one-way server-to-client streaming is all we need, SSE is simpler, works over plain HTTP, auto-reconnects in the browser. WebSockets would be overkill.

**Implementation notes:**
- The agent runs in a background task started by the `POST`. It pushes events into an `asyncio.Queue` keyed by `run_id`.
- The SSE endpoint drains that queue.
- Final state is persisted to SQLite when `done=True`.
- Generated Python is executed via `subprocess.run(..., timeout=10)` with network disabled at the OS level if easy, otherwise rely on the fact that inputs are student-controlled.

---

## 7. Vite + React Frontend Design

Single-page app, three views:

1. **Input view** — a textarea or URL field, source-type selector, "Start Migration" button. On submit → `POST /api/migrations` → navigate to trace view with `run_id`.
2. **Live trace view** — opens the SSE stream. Renders a timeline of agent events: planner decisions (with reasoning), translations (diffed against previous draft), test runs (pass/fail), lessons learned. This is the "watch the agent think" experience and it's what makes the project demo well.
3. **Result view** — once `done`, show: final Python code (Monaco or CodeMirror), the test suite, the validation scorecard, a "download" button.

**Tech:**
- Vite + React + TypeScript.
- TailwindCSS for styling (fast to set up).
- `@monaco-editor/react` for code display.
- `EventSource` API (built into browsers) for SSE — no library needed.
- React Query for the non-streaming endpoints.

---

## 8. Tech Stack

- **Agent:** LangGraph, LangChain, Anthropic or OpenAI API.
- **Backend:** FastAPI, Uvicorn, SQLModel (SQLite).
- **COBOL runtime:** GnuCOBOL (`apt install gnucobol` or brew). Used only for differential testing.
- **Testing libs (for generated tests):** pytest, hypothesis.
- **Static checks:** ruff, pyflakes.
- **Frontend:** Vite, React, TypeScript, Tailwind, Monaco.

---

## 9. Project Timeline (6 weeks, solo or pair)

| Week | Goal | Deliverable |
|---|---|---|
| 1 | Scaffolding | FastAPI skeleton, Vite app, SSE hello-world working end-to-end. |
| 2 | Agent core | LangGraph state + planner + translate + run_tests. Migrates a "HELLO WORLD" COBOL program. |
| 3 | Ingestion + analyze + reflect | Snippet/URL/repo input working. Reflection loop closes and agent actually recovers from failing tests. |
| 4 | Validation stack | GnuCOBOL differential testing, Hypothesis integration, LLM-judge, static checks. Scorecard in state. |
| 5 | Frontend polish | Live trace view working nicely, result view, history page. |
| 6 | Eval + demo prep | Run agent on 5–10 benchmark programs, collect metrics, write report, prep demo. |

---

## 10. How You'll Evaluate It (for the course write-up)

Pick 8–10 small COBOL programs (available in GnuCOBOL's test suite or online COBOL tutorials). For each, report:

- Did the agent finish within budget? (yes/no)
- How many planner turns did it take?
- Differential testing pass rate.
- Hypothesis pass rate.
- LLM-judge score.
- Did the code pass `ruff`?
- Final verdict category.

A table of these across programs is exactly what a course project report wants. You can also ablate: *disable reflection and rerun — does success rate drop?* That demonstrates the value of the agentic loop over a pipeline.

---

## 11. Risks (short version)

- **Agent loops without converging.** Mitigation: step budget + repeat detection + forced reflection. Already designed in.
- **LLM cost.** Mitigation: use a cheaper model for `analyze` and `reflect`, save the strong model for `translate` and `llm_judge`.
- **GnuCOBOL can't compile the input.** Mitigation: skip differential testing for that run, rely on other three validators, mark verdict as `likely_equivalent` not `equivalent`.
- **Generated Python does something nasty when executed.** Mitigation: subprocess with timeout; for a course project don't accept arbitrary internet code without skimming it. Could add a simple `ast`-based check that blocks `os.system`, `subprocess`, `socket` imports before running.

---

## 12. Stretch Goals (if time permits)

- "Explain this decision" button on trace events that shows the planner's full reasoning.
- Allow the user to intervene mid-run (add a hint, correct a mistake) — turns it into a human-in-the-loop agent.
- Persist `lessons_learned` across runs in SQLite and inject them into future planner prompts.
- A second model voting on translations (self-consistency).

---

*End of plan.*
