import { useState, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { AgentEvent } from "../lib/api";

interface LogEntryProps {
  event: AgentEvent;
  index: number;
  isLatest: boolean;
}

function formatTimestamp(index: number): string {
  const seconds = (index * 3.1).toFixed(1);
  return `00:${seconds.padStart(4, "0")}`;
}

const stepConfig: Record<string, { code: string; color: string }> = {
  planner_decision:  { code: "PLN", color: "#9AA3FF" },
  analysis_ready:    { code: "ANL", color: "#C39BFF" },
  draft_created:     { code: "GEN", color: "var(--teal)" },
  tests_generated:   { code: "TST", color: "#6FB8FF" },
  test_run:          { code: "TST", color: "#6FB8FF" },
  cobol_validation:  { code: "VAL", color: "var(--amber)" },
  lesson_learned:    { code: "LSN", color: "#FFD27A" },
  error:             { code: "ERR", color: "var(--rc8)" },
  cancelled:         { code: "CAN", color: "var(--rc16)" },
  done:              { code: "FIN", color: "var(--rc0)" },
};

function getMessage(event: AgentEvent): string {
  switch (event.type) {
    case "planner_decision":
      return event.payload.reasoning;
    case "analysis_ready":
      return event.payload.program_summary;
    case "draft_created":
      return `Draft ${event.payload.draft_id} generated — ${event.payload.code.split("\n").length} lines`;
    case "tests_generated":
      return `Test suite generated (${event.payload.tests.split("\n").filter(l => l.trim()).length} lines)`;
    case "test_run":
      return `${event.payload.passed ? "All" : "Some"} tests ${event.payload.passed ? "passed" : "failed"} · ${event.payload.duration_ms}ms`;
    case "lesson_learned":
      return event.payload.lesson;
    case "cobol_validation":
      return event.payload.message || (event.payload.passed ? "COBOL validation passed" : "COBOL validation failed");
    case "error":
      return event.payload.message;
    case "cancelled":
      return event.payload.message;
    case "done": {
      const v = event.payload?.verdict || "complete";
      const confidence = event.payload?.confidence != null ? ` · confidence ${event.payload.confidence.toFixed(2)}` : "";
      return `Migration ${v}${confidence}`;
    }
    default:
      return "";
  }
}

function getDetail(event: AgentEvent): string | null {
  switch (event.type) {
    case "test_run":
      return event.payload.output || event.payload.stderr || null;
    case "lesson_learned":
      return event.payload.root_cause || null;
    case "draft_created":
      return event.payload.rationale || null;
    case "cobol_validation":
      return event.payload.compiler_output || null;
    case "done":
      return event.payload?.issues?.join("\n") || null;
    default:
      return null;
  }
}

export default function LogEntry({ event, index, isLatest }: LogEntryProps) {
  const [isExpanded, setIsExpanded] = useState(isLatest);

  useEffect(() => {
    if (isLatest) {
      const timer = setTimeout(() => setIsExpanded(true), 0);
      return () => clearTimeout(timer);
    }
  }, [isLatest]);

  const step = stepConfig[event.type] || { code: "???", color: "var(--text-faint)" };
  const detail = getDetail(event);
  const canExpand = detail !== null;

  return (
    <div className={`log-entry${isLatest ? " active" : ""}`}>
      <span className="ts">{formatTimestamp(index)}</span>
      <span className="step" style={{ color: step.color }}>{step.code}</span>
      <div className="msg" style={{ flex: 1, minWidth: 0 }}>
        <span
          onClick={() => canExpand && setIsExpanded(!isExpanded)}
          style={{ cursor: canExpand ? "pointer" : "default" }}
        >
          {getMessage(event)}
        </span>
        <AnimatePresence initial={false}>
          {isExpanded && detail && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              style={{
                overflow: "hidden",
                marginTop: 8,
                padding: "8px 10px",
                background: "rgba(0,0,0,0.2)",
                border: "1px solid var(--line-soft)",
                fontSize: 11,
                lineHeight: 1.4,
                whiteSpace: "pre-wrap",
                color: "var(--text-faint)",
              }}
            >
              {detail}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
