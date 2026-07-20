# Stage 4 — Validation Rigor & Full Integration

## Purpose

This stage is the intellectual core of the project. We move beyond "does it run?" to "is it actually equivalent?" through a multi-layered validation stack. We also complete the integration: real HTTP endpoints, real streaming, real persistence. By the end, the system is functionally complete.

## What Success Looks Like

Start a migration via HTTP POST. Watch real events stream over SSE during an actual migration. When it completes, retrieve a validation scorecard showing results from multiple independent validators. The verdict (equivalent, likely equivalent, partial, broken) reflects the combined evidence.

## The Validation Stack

Four independent validators, each providing different evidence:

### Differential Testing

Compile the original COBOL with GnuCOBOL. Run both the COBOL binary and the Python translation on the same inputs. Compare outputs. If the COBOL won't compile, this validator degrades gracefully (it's informative but not blocking).

This is ground truth when available: same inputs, same outputs means behavioral equivalence for those cases.

### Property-Based Testing

Generate random inputs according to the I/O contract's type specifications using Hypothesis. Run the Python on many generated examples. Check that declared invariants hold.

This catches edge cases that handwritten tests miss. It's not proof of correctness, but it's strong evidence of robustness.

### LLM-as-Judge

Present the COBOL and Python side-by-side to a capable model. Ask structured questions: Do they compute the same thing? Are there control-flow differences? Data-type risks like rounding or overflow?

This catches semantic issues that execution-based tests might miss (dead code, subtle type coercions, encoding assumptions).

### Static Analysis

Run linters (ruff, pyflakes) on the generated Python. Check structural properties: does a main function exist, does its signature match the I/O contract.

This catches code quality issues and obvious structural problems that would make the code unmaintainable.

## Combined Verdict

The four validators produce independent scores. Combining them into a verdict:

- **Equivalent**: Differential passes completely, property testing passes, LLM judge scores high. Strong confidence.
- **Likely Equivalent**: Differential couldn't run (COBOL didn't compile) but property testing passes and judge scores high. Good confidence without ground truth.
- **Partial**: Mixed signals. Some tests pass, some concerns flagged. Might be usable with review.
- **Broken**: Significant differential failures or structural problems. Don't use without major revision.

Reflection uses these verdicts to guide recommendations. "Broken" means try again; "Equivalent" means finish.

## The HTTP Layer

**POST /api/migrations**: Accept source type and content/reference. Generate a run ID. Start the agent in a background task. Return the run ID immediately.

**GET /api/migrations/{id}/events**: SSE stream. Events flow through a queue from the agent task to the HTTP response generator. Heartbeats keep the connection alive. The stream ends with a "done" event.

**GET /api/migrations/{id}**: After completion, retrieve the full record: final code, tests, validation scores, verdict, event trace.

**GET /api/migrations**: Paginated history of all runs.

## Persistence

SQLite stores completed runs: source info, final code, final tests, validation JSON, event trace, verdict, timestamps. The database initializes on app startup. Finalize writes the row.

A run registry (in-memory map of run ID to async queue) coordinates between the background agent task and the SSE endpoint. It's process-local; restarts clear in-flight runs (acceptable for a course project).

## Event Schema

Every event has a type and payload. Types: planner_decision, analysis_ready, draft_created, tests_generated, test_run, validation_scored, lesson_learned, error, done. Payloads are structured and typed—the frontend will depend on this contract.

## API Safety

Validate inputs at the boundary. Limit source sizes. For repos, only accept GitHub URLs. Generated code still runs in sandboxed temp directories with AST safety checks. Never expose raw exceptions—always structured error responses.

## Verification Criteria

- HTTP POST starts a real migration
- SSE stream shows real events during migration
- GET retrieves a complete record with validation scores
- At least three of four validators produce non-null results
- Verdict is computed and stored
- Database contains the run after completion

## Boundary

Don't build the polished UI yet—curl and basic browser checks are sufficient. Don't run comprehensive benchmarks. The goal is integration completeness, not evaluation.
