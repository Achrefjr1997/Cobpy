from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cobol_migrator.agent.graph import run_migration
from cobol_migrator.ingest import load_source


def print_event(event_type: str, payload: dict) -> None:
    """Print events to stderr for visibility during CLI runs."""
    print(f"[{event_type}] {json.dumps(payload, indent=2)}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="COBOL to Python Migration Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # From a file
  %(prog)s --cobol-file program.cbl

  # From stdin (snippet mode)
  echo 'DISPLAY "HI"' | %(prog)s --snippet

  # From a URL
  %(prog)s --url https://example.com/program.cbl

  # From a GitHub repo
  %(prog)s --repo https://github.com/user/cobol-project
""",
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--cobol-file",
        type=Path,
        help="Path to a COBOL source file",
    )
    source_group.add_argument(
        "--snippet",
        action="store_true",
        help="Read COBOL from stdin",
    )
    source_group.add_argument(
        "--url",
        type=str,
        help="URL to fetch COBOL source from",
    )
    source_group.add_argument(
        "--repo",
        type=str,
        help="GitHub repository URL to clone and extract COBOL from",
    )

    parser.add_argument(
        "--step-budget",
        type=int,
        default=25,
        help="Maximum planner iterations (default: 25)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress event output, only print final code",
    )
    parser.add_argument(
        "--create-dummy-files",
        action="store_true",
        help="Create dummy input files for programs with external dependencies",
    )

    args = parser.parse_args()

    try:
        if args.cobol_file:
            if not args.cobol_file.exists():
                print(f"Error: File not found: {args.cobol_file}", file=sys.stderr)
                return 1
            cobol_source = args.cobol_file.read_text()
            source_type = "snippet"
            source_ref = str(args.cobol_file)
        elif args.snippet:
            cobol_source = sys.stdin.read()
            source_type = "snippet"
            source_ref = "stdin"
        elif args.url:
            print(f"Fetching COBOL from URL: {args.url}", file=sys.stderr)
            cobol_source = load_source("url", args.url)
            source_type = "url"
            source_ref = args.url
        elif args.repo:
            print(f"Cloning repository: {args.repo}", file=sys.stderr)
            cobol_source = load_source("repo", args.repo)
            source_type = "repo"
            source_ref = args.repo
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(f"Error loading source: {e}", file=sys.stderr)
        return 1

    emit = None if args.quiet else print_event

    options = f"budget: {args.step_budget} steps"
    if args.create_dummy_files:
        options += ", dummy files: enabled"
    print(f"Starting migration ({options})...", file=sys.stderr)

    final_state = run_migration(
        cobol_source=cobol_source,
        source_type=source_type,
        source_ref=source_ref,
        step_budget=args.step_budget,
        emit=emit,
        create_dummy_files=args.create_dummy_files,
    )

    print("", file=sys.stderr)
    print(f"Migration complete in {final_state.get('step_count', 0)} steps", file=sys.stderr)

    drafts = final_state.get("python_drafts", [])
    test_runs = final_state.get("test_runs", [])
    lessons = final_state.get("lessons_learned", [])

    if lessons:
        print(f"Lessons learned: {len(lessons)}", file=sys.stderr)

    if drafts:
        final_draft = drafts[-1]
        print(f"Final draft ID: {final_draft.id}", file=sys.stderr)
        print(f"Total drafts: {len(drafts)}", file=sys.stderr)

        if test_runs:
            last_run = test_runs[-1]
            status = "PASSED" if last_run.passed else "FAILED"
            print(f"Final test status: {status}", file=sys.stderr)

        print("", file=sys.stderr)
        print("=== Generated Python Code ===", file=sys.stderr)
        print(final_draft.code)
    else:
        print("No Python code was generated.", file=sys.stderr)
        if final_state.get("error"):
            print(f"Error: {final_state['error']}", file=sys.stderr)
        return 1

    if test_runs and not test_runs[-1].passed:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
