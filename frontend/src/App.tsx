import { useEffect, useRef, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Play,
  Square,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  Brain,
  Code2,
  TestTube2,
  Lightbulb,
  FileCode,
  Sparkles,
  Terminal,
  Copy,
  Check,
  Zap,
  FileText,
  Ban,
  Upload,
  Download,
  Shield,
} from "lucide-react";
import Editor from "@monaco-editor/react";
import {
  fetchHealth,
  startMigration,
  stopMigration,
  uploadAndMigrate,
  getDownloadUrl,
  subscribeEvents,
  type AgentEvent,
  type MigrationRequest,
} from "./lib/api";

const queryClient = new QueryClient();

const SAMPLE_COBOL = `       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY "HELLO, WORLD".
           STOP RUN.`;

const SAMPLE_COBOL_COMPLEX = `       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCULATE-PAY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-HOURS     PIC 9(3)V99 VALUE 40.00.
       01 WS-RATE      PIC 9(3)V99 VALUE 15.50.
       01 WS-GROSS-PAY PIC 9(5)V99.
       01 WS-TAX       PIC 9(5)V99.
       01 WS-NET-PAY   PIC 9(5)V99.
       PROCEDURE DIVISION.
           MULTIPLY WS-HOURS BY WS-RATE
               GIVING WS-GROSS-PAY.
           COMPUTE WS-TAX = WS-GROSS-PAY * 0.20.
           SUBTRACT WS-TAX FROM WS-GROSS-PAY
               GIVING WS-NET-PAY.
           DISPLAY "GROSS PAY: " WS-GROSS-PAY.
           DISPLAY "TAX: " WS-TAX.
           DISPLAY "NET PAY: " WS-NET-PAY.
           STOP RUN.`;

interface EventCardProps {
  event: AgentEvent;
  index: number;
  isLatest: boolean;
}

function EventCard({ event, index, isLatest }: EventCardProps) {
  const [isExpanded, setIsExpanded] = useState(isLatest);

  useEffect(() => {
    if (isLatest) {
      const timer = setTimeout(() => setIsExpanded(true), 0);
      return () => clearTimeout(timer);
    }
  }, [isLatest]);

  const getEventConfig = () => {
    switch (event.type) {
      case "planner_decision":
        return {
          icon: Brain,
          label: "Planning",
          color: "cyan",
          bgGlow: "shadow-cyan-500/20",
          borderColor: "border-cyan-500/50",
          iconBg: "bg-cyan-500/20",
          textColor: "text-cyan-400",
        };
      case "cobol_validation":
        return {
          icon: Shield,
          label: event.payload.passed ? "COBOL Valid" : "COBOL Invalid",
          color: event.payload.passed ? "emerald" : "red",
          bgGlow: event.payload.passed ? "shadow-emerald-500/20" : "shadow-red-500/20",
          borderColor: event.payload.passed ? "border-emerald-500/50" : "border-red-500/50",
          iconBg: event.payload.passed ? "bg-emerald-500/20" : "bg-red-500/20",
          textColor: event.payload.passed ? "text-emerald-400" : "text-red-400",
        };
      case "analysis_ready":
        return {
          icon: FileCode,
          label: "Analysis",
          color: "violet",
          bgGlow: "shadow-violet-500/20",
          borderColor: "border-violet-500/50",
          iconBg: "bg-violet-500/20",
          textColor: "text-violet-400",
        };
      case "draft_created":
        return {
          icon: Code2,
          label: "Code Generated",
          color: "emerald",
          bgGlow: "shadow-emerald-500/20",
          borderColor: "border-emerald-500/50",
          iconBg: "bg-emerald-500/20",
          textColor: "text-emerald-400",
        };
      case "tests_generated":
        return {
          icon: FileText,
          label: "Tests Generated",
          color: "blue",
          bgGlow: "shadow-blue-500/20",
          borderColor: "border-blue-500/50",
          iconBg: "bg-blue-500/20",
          textColor: "text-blue-400",
        };
      case "test_run": {
        const passed = event.payload.passed;
        return {
          icon: TestTube2,
          label: passed ? "Tests Passed" : "Tests Failed",
          color: passed ? "green" : "red",
          bgGlow: passed ? "shadow-green-500/20" : "shadow-red-500/20",
          borderColor: passed ? "border-green-500/50" : "border-red-500/50",
          iconBg: passed ? "bg-green-500/20" : "bg-red-500/20",
          textColor: passed ? "text-green-400" : "text-red-400",
        };
      }
      case "lesson_learned":
        return {
          icon: Lightbulb,
          label: "Insight",
          color: "amber",
          bgGlow: "shadow-amber-500/20",
          borderColor: "border-amber-500/50",
          iconBg: "bg-amber-500/20",
          textColor: "text-amber-400",
        };
      case "done":
        return {
          icon: Sparkles,
          label: "Complete",
          color: "emerald",
          bgGlow: "shadow-emerald-500/20",
          borderColor: "border-emerald-500/50",
          iconBg: "bg-emerald-500/20",
          textColor: "text-emerald-400",
        };
      case "error":
        return {
          icon: XCircle,
          label: "Error",
          color: "red",
          bgGlow: "shadow-red-500/20",
          borderColor: "border-red-500/50",
          iconBg: "bg-red-500/20",
          textColor: "text-red-400",
        };
      case "cancelled":
        return {
          icon: Ban,
          label: "Cancelled",
          color: "gray",
          bgGlow: "shadow-gray-500/20",
          borderColor: "border-gray-500/50",
          iconBg: "bg-gray-500/20",
          textColor: "text-gray-400",
        };
      default:
        return {
          icon: Zap,
          label: "Event",
          color: "gray",
          bgGlow: "shadow-gray-500/20",
          borderColor: "border-gray-500/50",
          iconBg: "bg-gray-500/20",
          textColor: "text-gray-400",
        };
    }
  };

  const config = getEventConfig();
  const Icon = config.icon;

  const renderContent = () => {
    switch (event.type) {
      case "planner_decision":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Next Action
              </span>
              <span
                className={`px-2 py-0.5 rounded text-xs font-bold ${config.iconBg} ${config.textColor}`}
              >
                {event.payload.next_action}
              </span>
              <span className="text-xs text-gray-600">
                Step {event.payload.step_count}
              </span>
            </div>
            <div className="space-y-2">
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Reasoning
              </span>
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                {event.payload.reasoning}
              </p>
            </div>
            {event.payload.target_draft_id && (
              <div className="text-xs text-gray-500 font-mono">
                Target: {event.payload.target_draft_id.slice(0, 12)}...
              </div>
            )}
          </div>
        );

      case "cobol_validation":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span
                className={`px-2 py-1 rounded text-xs font-bold ${event.payload.passed ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}
              >
                {event.payload.passed ? "VALID" : "INVALID"}
              </span>
            </div>
            <p className="text-sm text-gray-300">{event.payload.message}</p>
            {event.payload.cobol_output && (
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                  COBOL Output
                </span>
                <pre className="mt-1 p-2 bg-black/50 rounded text-xs text-emerald-300 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  {event.payload.cobol_output}
                </pre>
              </div>
            )}
            {event.payload.compiler_output && (
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-red-400">
                  Compiler Errors
                </span>
                <pre className="mt-1 p-2 bg-red-950/30 rounded text-xs text-red-300 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  {event.payload.compiler_output}
                </pre>
              </div>
            )}
          </div>
        );

      case "analysis_ready":
        return (
          <div className="space-y-3">
            <div>
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Program Summary
              </span>
              <p className="text-sm text-gray-300 mt-1 leading-relaxed">
                {event.payload.program_summary}
              </p>
            </div>
            {event.payload.io_contract && (
              <div className="space-y-2">
                <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                  I/O Contract
                </span>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="bg-black/30 rounded p-2">
                    <div className="text-violet-400 mb-1">Inputs</div>
                    {event.payload.io_contract.inputs.map((inp: { name: string; type: string }, i: number) => (
                      <div key={i} className="text-gray-400">
                        {inp.name}: {inp.type}
                      </div>
                    ))}
                    {event.payload.io_contract.inputs.length === 0 && (
                      <div className="text-gray-600">None</div>
                    )}
                  </div>
                  <div className="bg-black/30 rounded p-2">
                    <div className="text-violet-400 mb-1">Outputs</div>
                    {event.payload.io_contract.outputs.map((out: { name: string; type: string }, i: number) => (
                      <div key={i} className="text-gray-400">
                        {out.name}: {out.type}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        );

      case "draft_created":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-4 text-xs text-gray-500">
              <span className="font-mono">
                ID: {event.payload.draft_id.slice(0, 12)}...
              </span>
              {event.payload.parent_id && (
                <span className="font-mono">
                  Parent: {event.payload.parent_id.slice(0, 8)}...
                </span>
              )}
            </div>
            <div>
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Rationale
              </span>
              <p className="text-sm text-gray-300 mt-1 leading-relaxed">
                {event.payload.rationale}
              </p>
            </div>
            <div>
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Generated Code
              </span>
              <pre className="mt-2 p-3 bg-black/50 rounded-lg text-xs text-emerald-300 font-mono overflow-x-auto max-h-48 overflow-y-auto">
                {event.payload.code}
              </pre>
            </div>
          </div>
        );

      case "tests_generated":
        return (
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
              Test Suite
            </span>
            <pre className="mt-1 p-3 bg-black/50 rounded-lg text-xs text-blue-300 font-mono overflow-x-auto max-h-48 overflow-y-auto">
              {event.payload.tests}
            </pre>
          </div>
        );

      case "test_run":
        return (
          <div className="space-y-3">
            <div className="flex items-center gap-4">
              <span
                className={`px-2 py-1 rounded text-xs font-bold ${event.payload.passed ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}
              >
                {event.payload.passed ? "PASSED" : "FAILED"}
              </span>
              <span className="text-xs text-gray-500">
                {event.payload.duration_ms}ms
              </span>
              <span className="text-xs text-gray-600 font-mono">
                Draft: {event.payload.draft_id.slice(0, 8)}...
              </span>
            </div>
            {(event.payload.output || event.payload.stderr) && (
              <div className="space-y-2">
                {event.payload.output && (
                  <div>
                    <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                      Output
                    </span>
                    <pre className="mt-1 p-2 bg-black/50 rounded text-xs text-gray-300 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                      {event.payload.output}
                    </pre>
                  </div>
                )}
                {event.payload.stderr && (
                  <div>
                    <span className="text-xs font-mono uppercase tracking-wider text-red-400">
                      Stderr
                    </span>
                    <pre className="mt-1 p-2 bg-red-950/30 rounded text-xs text-red-300 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                      {event.payload.stderr}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        );

      case "lesson_learned":
        return (
          <div className="space-y-3">
            <div>
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Lesson
              </span>
              <p className="text-sm text-amber-200 mt-1 leading-relaxed">
                {event.payload.lesson}
              </p>
            </div>
            {event.payload.root_cause && (
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                  Root Cause
                </span>
                <p className="text-sm text-gray-300 mt-1">
                  {event.payload.root_cause}
                </p>
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
                Recommended
              </span>
              <span className="px-2 py-0.5 rounded text-xs font-bold bg-amber-500/20 text-amber-400">
                {event.payload.recommended_action}
              </span>
            </div>
          </div>
        );

      case "done":
        return (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Total Drafts</span>
                <div className="text-emerald-400 font-mono text-lg">
                  {event.payload?.total_drafts ?? "—"}
                </div>
              </div>
              <div>
                <span className="text-gray-500">Test Runs</span>
                <div className="text-emerald-400 font-mono text-lg">
                  {event.payload?.total_test_runs ?? "—"}
                </div>
              </div>
              <div>
                <span className="text-gray-500">Verdict</span>
                <div className="text-cyan-400 font-mono text-lg capitalize">
                  {event.payload?.verdict ?? "—"}
                </div>
              </div>
              <div>
                <span className="text-gray-500">Confidence</span>
                <div className="text-cyan-400 font-mono text-lg">
                  {event.payload?.confidence != null
                    ? `${(event.payload.confidence * 100).toFixed(1)}%`
                    : "—"}
                </div>
              </div>
            </div>

            {event.payload?.issues && event.payload.issues.length > 0 && (
              <div className="mt-3 p-3 bg-amber-950/30 border border-amber-800/50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  <span className="text-xs font-mono uppercase tracking-wider text-amber-400">
                    Issues Detected
                  </span>
                </div>
                <ul className="space-y-1">
                  {event.payload.issues.map((issue: string, i: number) => (
                    <li key={i} className="text-sm text-amber-200 flex items-start gap-2">
                      <span className="text-amber-500 mt-0.5">&bull;</span>
                      <span>{issue}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {event.payload?.external_dependency && (
              <div className="text-xs text-gray-500">
                External resource: {event.payload.external_resource}
              </div>
            )}

            {event.payload?.used_dummy_files && (
              <div className="text-xs text-blue-400 flex items-center gap-1">
                <FileText className="w-3 h-3" />
                Tests used auto-generated mock files with synthetic data
              </div>
            )}
          </div>
        );

      case "error":
        return (
          <div className="text-red-300">
            <span className="text-xs font-mono uppercase tracking-wider text-red-500">
              Error Details
            </span>
            <p className="mt-1">{event.payload.message}</p>
          </div>
        );

      case "cancelled":
        return (
          <div className="text-gray-300">
            <span className="text-xs font-mono uppercase tracking-wider text-gray-500">
              Migration Stopped
            </span>
            <p className="mt-1">{event.payload.message}</p>
          </div>
        );

      default:
        return (
          <div className="text-gray-400 text-sm">
            Unknown event type: {(event as { type: string }).type}
          </div>
        );
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -20, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className="relative"
    >
      {/* Timeline connector */}
      <div className="absolute left-5 top-12 bottom-0 w-px bg-gradient-to-b from-gray-700 to-transparent" />

      <div
        className={`
          relative bg-gray-900/80 backdrop-blur-sm rounded-xl border
          ${config.borderColor} ${isLatest ? `shadow-lg ${config.bgGlow}` : ""}
          transition-all duration-300 hover:bg-gray-900/90
        `}
      >
        {/* Header */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center gap-3 p-4 text-left"
        >
          <div className={`p-2 rounded-lg ${config.iconBg}`}>
            <Icon className={`w-5 h-5 ${config.textColor}`} />
          </div>

          <div className="flex-1">
            <div className={`font-medium ${config.textColor}`}>
              {config.label}
            </div>
            <div className="text-xs text-gray-500 font-mono">
              {event.type}
            </div>
          </div>

          <motion.div
            animate={{ rotate: isExpanded ? 180 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronDown className="w-5 h-5 text-gray-500" />
          </motion.div>
        </button>

        {/* Content */}
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-4 pt-0 border-t border-gray-800/50">
                <div className="pt-4">{renderContent()}</div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

function StatusBadge({
  status,
}: {
  status: "idle" | "running" | "success" | "error" | "partial" | "cancelled";
}) {
  const configs = {
    idle: {
      icon: Terminal,
      label: "Ready",
      className: "bg-gray-800 text-gray-400 border-gray-700",
    },
    running: {
      icon: Play,
      label: "Running",
      className: "bg-cyan-950 text-cyan-400 border-cyan-800 animate-pulse",
    },
    success: {
      icon: CheckCircle2,
      label: "Success",
      className: "bg-emerald-950 text-emerald-400 border-emerald-800",
    },
    error: {
      icon: XCircle,
      label: "Failed",
      className: "bg-red-950 text-red-400 border-red-800",
    },
    partial: {
      icon: AlertTriangle,
      label: "Partial",
      className: "bg-amber-950 text-amber-400 border-amber-800",
    },
    cancelled: {
      icon: Ban,
      label: "Cancelled",
      className: "bg-gray-800 text-gray-400 border-gray-600",
    },
  };

  const config = configs[status];
  const Icon = config.icon;

  return (
    <div
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border ${config.className}`}
    >
      <Icon className="w-4 h-4" />
      <span className="text-sm font-medium">{config.label}</span>
    </div>
  );
}

function MigratorApp() {
  const [sourceType, setSourceType] = useState<"snippet" | "file">("snippet");
  const [sourceRef, setSourceRef] = useState(SAMPLE_COBOL);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [createDummyFiles, setCreateDummyFiles] = useState(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [finalCode, setFinalCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  });

  const handleFileSelect = (file: File) => {
    setUploadedFile(file);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result;
      if (typeof text === "string") {
        setSourceRef(text);
      }
    };
    reader.readAsText(file);
  };

  const handleStartMigration = async () => {
    setEvents([]);
    setFinalCode(null);
    setIsStreaming(true);
    setIsStopping(false);

    try {
      let response;

      if (sourceType === "file" && uploadedFile) {
        response = await uploadAndMigrate(uploadedFile, 25, createDummyFiles);
      } else {
        const request: MigrationRequest = {
          source_type: "snippet",
          source_ref: sourceRef,
          step_budget: 25,
          create_dummy_files: createDummyFiles,
        };
        response = await startMigration(request);
      }

      setRunId(response.run_id);

      const cleanup = subscribeEvents(response.run_id, (event) => {
        setEvents((prev) => [...prev, event]);

        if (event.type === "draft_created") {
          setFinalCode(event.payload.code);
        }

        if (event.type === "done") {
          setIsStreaming(false);
          setIsStopping(false);
        }
      });

      return cleanup;
    } catch (error) {
      console.error("Failed to start migration:", error);
      setIsStreaming(false);
      setIsStopping(false);
    }
  };

  const handleStopMigration = async () => {
    if (!runId || !isStreaming) return;

    setIsStopping(true);
    try {
      await stopMigration(runId);
    } catch (error) {
      console.error("Failed to stop migration:", error);
      setIsStopping(false);
    }
  };

  const handleCopyCode = async () => {
    if (finalCode) {
      await navigator.clipboard.writeText(finalCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownloadCode = () => {
    if (runId) {
      window.open(getDownloadUrl(runId), "_blank");
    }
  };

  useEffect(() => {
    return () => {
      setIsStreaming(false);
    };
  }, []);

  const testsPassed = events.some(
    (e) => e.type === "test_run" && e.payload.passed
  );
  const hasError = events.some((e) => e.type === "error");
  const wasCancelled = events.some((e) => e.type === "cancelled");
  const doneEvent = events.find((e) => e.type === "done");
  const isDone = doneEvent !== undefined;

  const confidence = doneEvent?.type === "done" ? doneEvent.payload?.confidence : null;

  const getStatus = (): "idle" | "running" | "success" | "error" | "partial" | "cancelled" => {
    if (isStreaming) return "running";
    if (wasCancelled) return "cancelled";
    if (hasError) return "error";
    if (isDone && testsPassed) return "success";
    if (isDone) return "partial";
    return "idle";
  };

  const canStart =
    !isStreaming &&
    health?.status === "ok" &&
    (sourceType === "snippet" ? sourceRef.trim().length > 0 : uploadedFile !== null);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-gray-100">
      {/* Gradient background effects */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-violet-500/5 rounded-full blur-3xl" />
      </div>

      {/* Header */}
      <header className="relative border-b border-gray-800/50 bg-gray-900/30 backdrop-blur-sm">
        <div className="max-w-screen-2xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-2 bg-gradient-to-br from-cyan-500 to-violet-500 rounded-xl">
                <Terminal className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold bg-gradient-to-r from-cyan-400 to-violet-400 bg-clip-text text-transparent">
                  COBOL &rarr; Python Migrator
                </h1>
                <p className="text-xs text-gray-500 font-mono">
                  Agentic AI-powered legacy code transformation
                </p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <StatusBadge status={getStatus()} />

              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-800/50 border border-gray-700/50">
                {healthLoading ? (
                  <span className="text-gray-500 text-sm">Checking...</span>
                ) : health?.status === "ok" ? (
                  <>
                    <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                    <span className="text-emerald-400 text-sm">Connected</span>
                  </>
                ) : (
                  <>
                    <span className="w-2 h-2 bg-red-500 rounded-full" />
                    <span className="text-red-400 text-sm">Disconnected</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="relative max-w-screen-2xl mx-auto p-6 h-[calc(100vh-5rem)] overflow-hidden">
        <div className="grid grid-cols-12 gap-6 h-full">
          {/* Left Panel - Input */}
          <div className="col-span-4 flex flex-col min-h-0">
            <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl border border-gray-800/50 p-5 flex flex-col h-full min-h-0 overflow-hidden">
              <div className="flex items-center justify-between mb-4 flex-shrink-0">
                <h2 className="text-lg font-semibold text-gray-200 flex items-center gap-2">
                  <FileCode className="w-5 h-5 text-cyan-400" />
                  Source Input
                </h2>
                {runId && (
                  <span className="text-xs text-gray-600 font-mono bg-gray-800/50 px-2 py-1 rounded">
                    {runId.slice(0, 8)}
                  </span>
                )}
              </div>

              {/* Source type selector */}
              <div className="flex gap-2 mb-4 flex-shrink-0">
                {(["snippet", "file"] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => setSourceType(type)}
                    disabled={isStreaming}
                    className={`
                      flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2
                      ${sourceType === type
                        ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/50"
                        : "bg-gray-800/50 text-gray-400 border border-gray-700/50 hover:bg-gray-800"}
                      disabled:opacity-50 disabled:cursor-not-allowed
                    `}
                  >
                    {type === "snippet" ? (
                      <>
                        <Code2 className="w-4 h-4" />
                        Paste Code
                      </>
                    ) : (
                      <>
                        <Upload className="w-4 h-4" />
                        Upload File
                      </>
                    )}
                  </button>
                ))}
              </div>

              {/* Quick samples (only for snippet mode) */}
              {sourceType === "snippet" && (
                <div className="flex gap-2 mb-4 flex-shrink-0">
                  <button
                    onClick={() => setSourceRef(SAMPLE_COBOL)}
                    disabled={isStreaming}
                    className="text-xs px-2 py-1 rounded bg-gray-800/50 text-gray-400 hover:text-cyan-400 transition-colors disabled:opacity-50"
                  >
                    Hello World
                  </button>
                  <button
                    onClick={() => setSourceRef(SAMPLE_COBOL_COMPLEX)}
                    disabled={isStreaming}
                    className="text-xs px-2 py-1 rounded bg-gray-800/50 text-gray-400 hover:text-cyan-400 transition-colors disabled:opacity-50"
                  >
                    Payroll Calc
                  </button>
                </div>
              )}

              {/* Input area */}
              <div className="flex-1 min-h-0 mb-4">
                {sourceType === "snippet" ? (
                  <div className="h-full rounded-xl overflow-hidden border border-gray-700/50">
                    <Editor
                      height="100%"
                      defaultLanguage="cobol"
                      value={sourceRef}
                      onChange={(value) => setSourceRef(value || "")}
                      theme="vs-dark"
                      options={{
                        minimap: { enabled: false },
                        fontSize: 13,
                        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                        lineNumbers: "on",
                        scrollBeyondLastLine: false,
                        padding: { top: 12, bottom: 12 },
                        readOnly: isStreaming,
                      }}
                    />
                  </div>
                ) : (
                  <div className="h-full flex flex-col gap-4">
                    {/* File upload area */}
                    <div
                      onClick={() => !isStreaming && fileInputRef.current?.click()}
                      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const droppedFile = e.dataTransfer.files[0] as File | undefined;
                        if (!isStreaming && droppedFile) {
                          handleFileSelect(droppedFile);
                        }
                      }}
                      className={`
                        flex flex-col items-center justify-center p-8 rounded-xl border-2 border-dashed
                        transition-all cursor-pointer
                        ${uploadedFile
                          ? "border-cyan-500/50 bg-cyan-950/10"
                          : "border-gray-700/50 bg-gray-800/20 hover:border-gray-600/50 hover:bg-gray-800/30"}
                        ${isStreaming ? "opacity-50 cursor-not-allowed" : ""}
                      `}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".cbl,.cob,.cobol,.cpy,.txt"
                        className="hidden"
                        disabled={isStreaming}
                        onChange={(e) => {
                          const selected = e.target.files?.[0] as File | undefined;
                          if (selected) {
                            handleFileSelect(selected);
                          }
                        }}
                      />
                      <Upload className={`w-10 h-10 mb-3 ${uploadedFile ? "text-cyan-400" : "text-gray-500"}`} />
                      {uploadedFile ? (
                        <>
                          <p className="text-cyan-400 font-medium">{uploadedFile.name}</p>
                          <p className="text-xs text-gray-500 mt-1">
                            {(uploadedFile.size / 1024).toFixed(1)} KB
                          </p>
                        </>
                      ) : (
                        <>
                          <p className="text-gray-400 font-medium">Drop a COBOL file here</p>
                          <p className="text-xs text-gray-500 mt-1">
                            or click to browse (.cbl, .cob, .cobol, .txt)
                          </p>
                        </>
                      )}
                    </div>

                    {/* Preview of uploaded file */}
                    {uploadedFile && sourceRef && (
                      <div className="flex-1 min-h-0 rounded-xl overflow-hidden border border-gray-700/50">
                        <Editor
                          height="100%"
                          defaultLanguage="cobol"
                          value={sourceRef}
                          theme="vs-dark"
                          options={{
                            minimap: { enabled: false },
                            fontSize: 13,
                            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                            lineNumbers: "on",
                            scrollBeyondLastLine: false,
                            padding: { top: 12, bottom: 12 },
                            readOnly: true,
                          }}
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Options */}
              <div className="mb-4 p-3 bg-gray-800/30 rounded-xl border border-gray-700/30 flex-shrink-0">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={createDummyFiles}
                    onChange={(e) => setCreateDummyFiles(e.target.checked)}
                    disabled={isStreaming}
                    className="mt-1 w-4 h-4 rounded border-gray-600 bg-gray-700 text-cyan-500 focus:ring-cyan-500/50"
                  />
                  <div>
                    <span className="font-medium text-gray-300 text-sm">
                      Create mock files with synthetic data
                    </span>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Generate temporary input files with synthetic data for file-dependent programs
                    </p>
                  </div>
                </label>
              </div>

              {/* Action buttons */}
              <div className="flex gap-3">
                <motion.button
                  onClick={handleStartMigration}
                  disabled={!canStart}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className={`
                    flex-1 py-4 rounded-xl font-semibold text-lg transition-all
                    flex items-center justify-center gap-3
                    ${isStreaming
                      ? "bg-gray-800 text-gray-400 cursor-not-allowed"
                      : "bg-gradient-to-r from-cyan-500 to-violet-500 text-white hover:shadow-lg hover:shadow-cyan-500/25"}
                    disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-none
                  `}
                >
                  {isStreaming ? (
                    <>
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                      >
                        <Zap className="w-5 h-5" />
                      </motion.div>
                      {isStopping ? "Stopping..." : "Processing..."}
                    </>
                  ) : (
                    <>
                      <Play className="w-5 h-5" />
                      Start Migration
                    </>
                  )}
                </motion.button>

                <AnimatePresence>
                  {isStreaming && (
                    <motion.button
                      initial={{ opacity: 0, width: 0 }}
                      animate={{ opacity: 1, width: "auto" }}
                      exit={{ opacity: 0, width: 0 }}
                      onClick={handleStopMigration}
                      disabled={isStopping}
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      className={`
                        px-6 py-4 rounded-xl font-semibold transition-all
                        flex items-center justify-center gap-2
                        ${isStopping
                          ? "bg-gray-700 text-gray-400 cursor-not-allowed"
                          : "bg-red-600 hover:bg-red-700 text-white hover:shadow-lg hover:shadow-red-500/25"}
                      `}
                    >
                      {isStopping ? (
                        <Ban className="w-5 h-5 animate-pulse" />
                      ) : (
                        <Square className="w-5 h-5" />
                      )}
                      <span className="whitespace-nowrap">
                        {isStopping ? "Stopping" : "Stop"}
                      </span>
                    </motion.button>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* Center Panel - Agent Events */}
          <div className="col-span-4 flex flex-col min-h-0">
            <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl border border-gray-800/50 p-5 flex flex-col h-full min-h-0 overflow-hidden">
              <div className="flex items-center justify-between mb-4 flex-shrink-0">
                <h2 className="text-lg font-semibold text-gray-200 flex items-center gap-2">
                  <Brain className="w-5 h-5 text-violet-400" />
                  Agent Reasoning
                </h2>
                <span className="text-xs text-gray-500 font-mono">
                  {events.length} events
                </span>
              </div>

              <div className="flex-1 overflow-y-auto min-h-0 pr-2 space-y-3 scrollbar-thin">
                {events.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-gray-600">
                    <Brain className="w-12 h-12 mb-4 opacity-30" />
                    <p className="text-sm">Agent events will appear here</p>
                    <p className="text-xs mt-1">Start a migration to begin</p>
                  </div>
                ) : (
                  <AnimatePresence>
                    {events.map((event, index) => (
                      <EventCard
                        key={index}
                        event={event}
                        index={index}
                        isLatest={index === events.length - 1}
                      />
                    ))}
                  </AnimatePresence>
                )}
              </div>
            </div>
          </div>

          {/* Right Panel - Output */}
          <div className="col-span-4 flex flex-col min-h-0">
            <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl border border-gray-800/50 p-5 flex flex-col h-full min-h-0 overflow-hidden">
              <div className="flex items-center justify-between mb-4 flex-shrink-0">
                <h2 className="text-lg font-semibold text-gray-200 flex items-center gap-2">
                  <Code2 className="w-5 h-5 text-emerald-400" />
                  Generated Python
                </h2>
                {finalCode && (
                  <div className="flex items-center gap-2">
                    {/* Download button */}
                    {isDone && runId && (
                      <motion.button
                        onClick={handleDownloadCode}
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-900/30 text-emerald-400 hover:bg-emerald-900/50 transition-colors border border-emerald-700/30"
                      >
                        <Download className="w-4 h-4" />
                        <span className="text-xs">.py</span>
                      </motion.button>
                    )}
                    {/* Copy button */}
                    <motion.button
                      onClick={handleCopyCode}
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-800/50 text-gray-400 hover:text-emerald-400 transition-colors"
                    >
                      {copied ? (
                        <>
                          <Check className="w-4 h-4" />
                          <span className="text-xs">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-4 h-4" />
                          <span className="text-xs">Copy</span>
                        </>
                      )}
                    </motion.button>
                  </div>
                )}
              </div>

              {/* Result status */}
              {isDone && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mb-4 flex-shrink-0"
                >
                  <div
                    className={`
                      p-4 rounded-xl border flex items-start gap-3
                      ${testsPassed
                        ? "bg-emerald-950/30 border-emerald-800/50 text-emerald-400"
                        : hasError
                          ? "bg-red-950/30 border-red-800/50 text-red-400"
                          : "bg-amber-950/30 border-amber-800/50 text-amber-400"}
                    `}
                  >
                    <div className="mt-0.5">
                      {testsPassed ? (
                        <CheckCircle2 className="w-5 h-5" />
                      ) : hasError ? (
                        <XCircle className="w-5 h-5" />
                      ) : (
                        <AlertTriangle className="w-5 h-5" />
                      )}
                    </div>
                    <div className="flex-1">
                      <div className="font-medium flex items-center gap-3">
                        <span>
                          {testsPassed
                            ? "Migration Successful"
                            : hasError
                              ? "Migration Failed"
                              : "Migration Completed with Issues"}
                        </span>
                        {confidence != null && (
                          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-black/30 border border-current/30">
                            {(confidence * 100).toFixed(1)}% confidence
                          </span>
                        )}
                      </div>
                      <div className="text-xs opacity-70 mt-0.5">
                        {testsPassed
                          ? "All tests passed, code is ready to use"
                          : hasError
                            ? "An error occurred during migration"
                            : "Review the code and issues below"}
                      </div>

                      {!testsPassed && !hasError && doneEvent?.payload?.issues && (
                        <div className="mt-3 space-y-1">
                          {doneEvent.payload.issues.map((issue: string, i: number) => (
                            <div key={i} className="text-xs flex items-start gap-2 text-amber-300/80">
                              <span className="text-amber-500">&bull;</span>
                              <span>{issue}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </motion.div>
              )}

              {/* Code output */}
              <div className="flex-1 min-h-0 rounded-xl overflow-hidden border border-gray-700/50">
                {finalCode ? (
                  <Editor
                    height="100%"
                    defaultLanguage="python"
                    value={finalCode}
                    theme="vs-dark"
                    options={{
                      minimap: { enabled: false },
                      fontSize: 13,
                      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                      lineNumbers: "on",
                      scrollBeyondLastLine: false,
                      padding: { top: 12, bottom: 12 },
                      readOnly: true,
                    }}
                  />
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-gray-600 bg-gray-800/20">
                    <Code2 className="w-12 h-12 mb-4 opacity-30" />
                    <p className="text-sm">Generated code will appear here</p>
                    <p className="text-xs mt-1">Waiting for migration...</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <MigratorApp />
    </QueryClientProvider>
  );
}

export default App;
