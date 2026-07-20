#!/usr/bin/env python3
"""
View and analyze migration run logs.

Usage:
    # List all logs
    python scripts/view_log.py --list
    
    # View latest log
    python scripts/view_log.py --latest
    
    # View specific log
    python scripts/view_log.py <run_id>
    
    # View only events
    python scripts/view_log.py <run_id> --events
    
    # View only test executions
    python scripts/view_log.py <run_id> --tests
    
    # Export to readable format
    python scripts/view_log.py <run_id> --export output.txt
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"


def list_logs() -> None:
    """List all available log files."""
    if not LOGS_DIR.exists():
        print(f"Logs directory not found: {LOGS_DIR}")
        return
    
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not logs:
        print("No logs found.")
        return
    
    print(f"Found {len(logs)} log file(s) in {LOGS_DIR}:\n")
    
    for log_file in logs[:20]:
        try:
            with open(log_file) as f:
                first_line = f.readline()
                last_line = None
                for line in f:
                    last_line = line
            
            start_entry = json.loads(first_line)
            
            if last_line:
                end_entry = json.loads(last_line)
                status = end_entry.get("verdict", "unknown")
                duration = end_entry.get("duration_ms", 0)
                duration_str = f"{duration/1000:.1f}s" if duration else "?"
                drafts = end_entry.get("total_drafts", "?")
                steps = end_entry.get("total_steps", "?")
            else:
                status = "incomplete"
                duration_str = "?"
                drafts = "?"
                steps = "?"
            
            print(f"  {log_file.stem}")
            print(f"    Started: {start_entry.get('start_time', '?')}")
            print(f"    Status: {status} | Duration: {duration_str} | Drafts: {drafts} | Steps: {steps}")
            print()
            
        except Exception as e:
            print(f"  {log_file.stem} - Error reading: {e}")


def view_log(
    run_id: str,
    events_only: bool = False,
    tests_only: bool = False,
    export_file: str | None = None,
) -> None:
    """View a specific log file."""
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return
    
    output_lines = []
    
    def out(text: str) -> None:
        output_lines.append(text)
        if not export_file:
            print(text)
    
    out(f"=== Log: {run_id} ===")
    out(f"File: {log_file}")
    out("")
    
    with open(log_file) as f:
        for line in f:
            entry = json.loads(line)
            entry_type = entry.get("type")
            
            if events_only and entry_type != "event":
                continue
            if tests_only and entry_type != "test_execution":
                continue
            
            timestamp = entry.get("timestamp", "")[:19]
            
            if entry_type == "run_started":
                out(f"[{timestamp}] === RUN STARTED ===")
                out(f"    Run ID: {entry.get('run_id')}")
                
            elif entry_type == "input":
                out(f"[{timestamp}] INPUT")
                out(f"    Source: {entry.get('source_type')} - {entry.get('source_ref', '')[:50]}")
                out(f"    Budget: {entry.get('step_budget')} steps")
                cobol = entry.get("cobol_source", "")
                out(f"    COBOL: {len(cobol)} chars")
                out(f"    ---COBOL SOURCE---")
                for cline in cobol.split("\n")[:20]:
                    out(f"    {cline}")
                if cobol.count("\n") > 20:
                    out(f"    ... ({cobol.count(chr(10)) - 20} more lines)")
                out(f"    ---END COBOL---")
                
            elif entry_type == "event":
                event_type = entry.get("event_type")
                payload = entry.get("payload", {})
                
                if event_type == "planner_decision":
                    out(f"[{timestamp}] PLANNER -> {payload.get('next_action')}")
                    out(f"    Step: {payload.get('step_count')}")
                    out(f"    Reasoning: {payload.get('reasoning', '')}")
                    
                elif event_type == "draft_created":
                    out(f"[{timestamp}] DRAFT CREATED")
                    out(f"    ID: {payload.get('draft_id')}")
                    out(f"    Parent: {payload.get('parent_id')}")
                    out(f"    Rationale: {payload.get('rationale', '')[:200]}")
                    code = payload.get("code", "")
                    out(f"    ---PYTHON CODE ({len(code)} chars)---")
                    for cline in code.split("\n"):
                        out(f"    {cline}")
                    out(f"    ---END CODE---")
                    
                elif event_type == "test_run":
                    status = "PASSED" if payload.get("passed") else "FAILED"
                    out(f"[{timestamp}] TEST {status}")
                    out(f"    Draft: {payload.get('draft_id')}")
                    out(f"    Duration: {payload.get('duration_ms')}ms")
                    if not payload.get("passed"):
                        out(f"    ---STDERR---")
                        for eline in payload.get("stderr", "").split("\n")[:30]:
                            out(f"    {eline}")
                        out(f"    ---END STDERR---")
                        
                elif event_type == "lesson_learned":
                    out(f"[{timestamp}] LESSON LEARNED")
                    out(f"    Lesson: {payload.get('lesson', '')}")
                    out(f"    Recommended: {payload.get('recommended_action')}")
                    if payload.get("root_cause"):
                        out(f"    Root cause: {payload.get('root_cause')}")
                    
                elif event_type == "analysis_ready":
                    out(f"[{timestamp}] ANALYSIS COMPLETE")
                    out(f"    Summary: {payload.get('program_summary', '')}")
                    io = payload.get("io_contract", {})
                    if io:
                        out(f"    Inputs: {io.get('inputs', [])}")
                        out(f"    Outputs: {io.get('outputs', [])}")
                        out(f"    Invariants: {io.get('invariants', [])}")
                        
                elif event_type == "tests_generated":
                    tests = payload.get("tests", "")
                    out(f"[{timestamp}] TESTS GENERATED ({len(tests)} chars)")
                    
                elif event_type == "done":
                    out(f"[{timestamp}] DONE")
                    
                else:
                    out(f"[{timestamp}] EVENT: {event_type}")
                    
            elif entry_type == "test_execution":
                status = "PASSED" if entry.get("passed") else "FAILED"
                out(f"[{timestamp}] TEST EXECUTION: {status}")
                out(f"    Draft: {entry.get('draft_id')}")
                out(f"    Duration: {entry.get('duration_ms')}ms")
                out(f"    ---PYTHON CODE---")
                for pline in entry.get("python_code", "").split("\n"):
                    out(f"    {pline}")
                out(f"    ---TEST CODE---")
                for tline in entry.get("test_code", "").split("\n")[:30]:
                    out(f"    {tline}")
                out(f"    ---STDOUT---")
                for sline in entry.get("stdout", "").split("\n")[:20]:
                    out(f"    {sline}")
                out(f"    ---STDERR---")
                for eline in entry.get("stderr", "").split("\n")[:30]:
                    out(f"    {eline}")
                out(f"    ---END---")
                    
            elif entry_type == "state_update":
                node = entry.get("node")
                update = entry.get("update", {})
                keys = list(update.keys())
                out(f"[{timestamp}] STATE UPDATE from {node}")
                out(f"    Keys: {keys}")
                
            elif entry_type == "error":
                out(f"[{timestamp}] ERROR: {entry.get('error')}")
                out(f"    Context: {entry.get('context', {})}")
                
            elif entry_type == "run_completed":
                out(f"")
                out(f"[{timestamp}] === RUN COMPLETED ===")
                out(f"    Verdict: {entry.get('verdict')}")
                out(f"    Success: {entry.get('success')}")
                out(f"    Steps: {entry.get('total_steps')}")
                out(f"    Drafts: {entry.get('total_drafts')}")
                out(f"    Tests: {entry.get('total_tests')}")
                out(f"    Duration: {entry.get('duration_ms', 0)/1000:.1f}s")
                lessons = entry.get("lessons_learned", [])
                if lessons:
                    out(f"    Lessons learned:")
                    for lesson in lessons:
                        out(f"      - {lesson}")
                final_code = entry.get("final_code")
                if final_code:
                    out(f"    ---FINAL CODE---")
                    for fline in final_code.split("\n"):
                        out(f"    {fline}")
                    out(f"    ---END---")
            
            out("")
    
    if export_file:
        with open(export_file, "w") as f:
            f.write("\n".join(output_lines))
        print(f"Exported to {export_file}")


def get_latest_log() -> str | None:
    """Get the run_id of the most recent log."""
    if not LOGS_DIR.exists():
        return None
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if logs:
        return logs[0].stem
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="View migration run logs")
    parser.add_argument("run_id", nargs="?", help="Run ID to view")
    parser.add_argument("--list", action="store_true", help="List all logs")
    parser.add_argument("--latest", action="store_true", help="View latest log")
    parser.add_argument("--events", action="store_true", help="Show only events")
    parser.add_argument("--tests", action="store_true", help="Show only test executions")
    parser.add_argument("--export", type=str, help="Export to file")
    
    args = parser.parse_args()
    
    if args.list:
        list_logs()
    elif args.latest:
        latest = get_latest_log()
        if latest:
            view_log(latest, args.events, args.tests, args.export)
        else:
            print("No logs found.")
    elif args.run_id:
        view_log(args.run_id, args.events, args.tests, args.export)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
