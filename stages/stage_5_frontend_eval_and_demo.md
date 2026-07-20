# Stage 5 — Polish, Evaluation & Presentation

## Purpose

Make the system presentable and prove it works. This stage has two parallel tracks: building a real UI that showcases the agent's capabilities, and running systematic evaluation to generate the numbers that go in the course report. By the end, you have a demo you can present and a report you can submit.

## What Success Looks Like

A professor (or recruiter, or curious colleague) can:
1. Open the app, paste COBOL, start a migration
2. Watch the agent think in real-time—see decisions, failures, lessons, retries
3. View the final result with validation scorecard
4. Download the artifacts
5. Browse past runs

Meanwhile, you have benchmark results showing success rates across diverse programs and ablation data showing that reflection actually helps.

## The User Interface

Three views connected by routing:

### Input View

The entry point. Choose how to provide COBOL (paste it, give a URL, point to a GitHub repo). Submit to start a migration and immediately navigate to the run view. The form remembers last input for quick iteration.

### Run View

The showcase view. Two modes based on state:

**During migration**: A live timeline showing every agent event as it happens. Planner decisions reveal reasoning. Draft creation is diffable against previous drafts. Test results show pass/fail with expandable details. Lesson callouts highlight when the agent learned something. The user watches the agent think.

**After completion**: The timeline collapses or becomes secondary. Primary focus shifts to results: the final Python in an editor, the generated tests, and a scorecard summarizing all validation results with a prominent verdict badge.

The transition is automatic—when "done" arrives, the view smoothly shifts focus.

### History View

A paginated list of all past runs. Shows when, what type, verdict, with links to view any run. Useful for comparing approaches or revisiting work.

## Visual Components

**Timeline Event**: Renders one event with appropriate icon and styling. Planner decisions show reasoning. Drafts are collapsed by default with option to see diff. Test failures show truncated stderr. Lessons get callout styling.

**Draft Diff**: Side-by-side or inline comparison between consecutive drafts. Shows what changed after reflection.

**Scorecard Card**: The four validators in a glanceable format. Progress bars for pass rates. Concerns listed for the LLM judge. A dominant verdict badge sets expectations at a glance.

**Monaco Editor**: Lazy-loaded code editor for viewing final Python and tests. Syntax highlighting, read-only, professional appearance.

## Benchmark Evaluation

Collect 8-10 diverse COBOL programs:
- Trivial (hello world) — sanity check
- Control flow (fizzbuzz, nested conditionals)
- Numeric (factorial, fibonacci, arithmetic with packed decimals)
- Strings (word count, string manipulation)
- Arrays (sorting via OCCURS)
- Composite (multi-paragraph programs)

Run each through the agent. Record: whether it finished, how many turns it took, pass rates from each validator, final verdict, wall time. Output to CSV.

This produces the results table for the report. Expect a mix of verdicts—perfect scores on everything would be suspicious; some programs are genuinely harder.

## Ablation Study

Disable reflection and re-run the benchmark. Mechanically: make the planner treat REFLECT as if it were TRANSLATE or FINISH.

Compare success rates with and without reflection. This answers "does the learning mechanism actually help?" The difference quantifies reflection's contribution.

## Demo Script

A 5-minute walkthrough:
1. **Setup** (30 sec): Show the running system
2. **Input** (30 sec): Paste a tricky COBOL program (one that fails first try)
3. **Live trace** (2 min): Narrate as the agent works—first attempt fails, lesson learned appears, second attempt incorporates the lesson, tests pass, validation runs
4. **Results** (1 min): Show the scorecard, browse the code, download artifacts
5. **Evidence** (1 min): Show history of past runs, reference ablation results

The demo tells a story: the agent thinks, fails, learns, and succeeds.

## Report Structure

The course report documents the system:

- **Abstract**: One paragraph summary of what was built and key findings
- **Problem & Motivation**: Why agentic (learning loop) rather than pipeline (single shot)
- **Architecture**: Two services, their responsibilities, how they communicate
- **The Agent Loop**: State design, node responsibilities, robustness guards
- **Validation Stack**: Four techniques, why each matters, how verdicts combine
- **Evaluation**: Benchmark programs, metrics collected, results table
- **Ablation**: Reflection on vs off, quantified impact
- **Discussion**: What worked well, what surprised you, honest assessment
- **Limitations**: Acknowledge what's out of scope (sandboxing, COBOL dialects, etc.)
- **Future Work**: Natural extensions if this were to continue

Populate with real numbers from the benchmarks. The report should be honest about limitations—this is a course project with intentionally narrow scope, not a production system.

## Verification Criteria

- All three UI views render correctly
- Live streaming visibly updates the timeline
- Scorecard displays validation results on completion
- Download produces a valid zip with code, tests, validation JSON
- Benchmark CSV has at least 8 programs with non-trivial results
- Ablation shows measurable difference in success rate
- Demo can be executed without code changes or errors
- Report contains real numbers, not placeholders

## Boundary

This is the final stage. Resist scope creep. The goal is completion and presentation, not new features. If something isn't working, fix it. If something is missing from earlier stages, finish it. But don't add complexity—close out.
