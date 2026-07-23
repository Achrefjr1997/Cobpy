import { useEffect, useRef, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import { motion, AnimatePresence } from "framer-motion";
import {
  Play,
  Square,
  Code2,
  Terminal,
  Copy,
  Check,
  Zap,
  Upload,
  Download,
  Share2,
} from "lucide-react";
import Editor from "@monaco-editor/react";
import {
  fetchHealth,
  startMigration,
  stopMigration,
  uploadAndMigrate,
  uploadZip,
  migrateFromZip,
  getDownloadUrl,
  subscribeEvents,
  startBatchMigration,
  subscribeBatchEvents,
  type AgentEvent,
  type BatchEvent,
  type MigrationRequest,
  type MigrationStartResponse,
  type ZipUploadResponse,
} from "./lib/api";
import RcBadge from "./components/RcBadge";
import FileExplorer, { type FileNode } from "./components/FileExplorer";
import { registerCobolLanguage } from "./lib/cobolTokenizer";
import TabStrip, { type Tab } from "./components/TabStrip";
import LogEntry from "./components/LogEntry";
import DependencyGraph from "./components/DependencyGraph";

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
       01 HOURS-WORKED     PIC 9(3)V9(2).
       01 HOURLY-RATE      PIC 9(3)V9(2).
       01 GROSS-PAY        PIC 9(5)V9(2).
       01 NET-PAY          PIC 9(5)V9(2).
       01 TAX-AMOUNT       PIC 9(4)V9(2).
       01 TAX-RATE         PIC V99 VALUE 0.20.
       PROCEDURE DIVISION.
           MOVE 40 TO HOURS-WORKED.
           MOVE 25 TO HOURLY-RATE.
           MULTIPLY HOURS-WORKED BY HOURLY-RATE
               GIVING GROSS-PAY.
           MULTIPLY GROSS-PAY BY TAX-RATE
               GIVING TAX-AMOUNT.
           SUBTRACT TAX-AMOUNT FROM GROSS-PAY
               GIVING NET-PAY.
           DISPLAY "NET PAY: " NET-PAY.
           STOP RUN.`;

function MigratorApp() {
  const [sourceType, setSourceType] = useState<"snippet" | "file" | "zip">("snippet");
  const [sourceRef, setSourceRef] = useState(SAMPLE_COBOL);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [createDummyFiles, setCreateDummyFiles] = useState(false);
  const [zipResult, setZipResult] = useState<ZipUploadResponse | null>(null);
  const [selectedZipProgram, setSelectedZipProgram] = useState<string>("");
  const [zipLoading, setZipLoading] = useState(false);
  const [zipError, setZipError] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [finalCode, setFinalCode] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [batchProgramResults, setBatchProgramResults] = useState<
    Record<string, { verdict: string; confidence?: number }>
  >({});
  const [rawBatchEvents, setRawBatchEvents] = useState<BatchEvent[]>([]);
  const [activeSourceFile, setActiveSourceFile] = useState<string>("");
  const [activeOutputFile, setActiveOutputFile] = useState<string>("");
  const [openSourceTabs, setOpenSourceTabs] = useState<Tab[]>([]);
  const [openOutputTabs, setOpenOutputTabs] = useState<Tab[]>([]);
  const [showSweep, setShowSweep] = useState(false);
  const [showGraph, setShowGraph] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);

  useEffect(() => { registerCobolLanguage(); }, []);

  // Auto-select first source file when data arrives (replaces render-time setState)
  useEffect(() => {
    if (sourceType === "zip" && zipResult) {
      const progs: { id: string; name: string }[] = [];
      for (const [id, info] of Object.entries(zipResult.dependency_graph)) {
        if (!info.file_path.toLowerCase().endsWith(".cpy")) {
          const name = info.file_path.split("/").pop() || info.file_path.split("\\").pop() || id;
          progs.push({ id, name });
        }
      }
      if (!activeSourceFile && progs.length > 0) {
        setActiveSourceFile(progs[0]!.id);
        setOpenSourceTabs([{ id: progs[0]!.id, label: progs[0]!.name }]);
      }
    } else if (sourceRef && !activeSourceFile) {
      const label = uploadedFile?.name || "snippet.cbl";
      setActiveSourceFile("source");
      setOpenSourceTabs([{ id: "source", label }]);
    }
  }, [sourceType, zipResult, activeSourceFile, sourceRef, uploadedFile]);

  // Auto-select first output file when results arrive (replaces render-time setState)
  useEffect(() => {
    const keys = Object.keys(finalCode);
    if (!activeOutputFile && keys.length > 0) {
      const first = keys[0]!;
      setActiveOutputFile(first);
      setOpenOutputTabs([{ id: first, label: `${first}.py` }]);
    }
  }, [finalCode, activeOutputFile]);

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

  const handleZipUpload = async (file: File) => {
    setZipError(null);
    setZipResult(null);
    setSelectedZipProgram("");
    setBatchId(null);
    setIsBatchRunning(false);
    setZipLoading(true);
    try {
      const result = await uploadZip(file);
      setZipResult(result);
      setSelectedZipProgram("*all*");
    } catch (err) {
      setZipError(err instanceof Error ? err.message : "ZIP upload failed");
    } finally {
      setZipLoading(false);
    }
  };

  const handleStartMigration = async () => {
    setEvents([]);
    setFinalCode({});
    setActiveSourceFile("");
    setActiveOutputFile("");
    setIsStreaming(true);
    setIsStopping(false);

    setShowSweep(true);
    setTimeout(() => {
      setShowSweep(false);
    }, 3200);

    try {
      if (sourceType === "zip" && zipResult && selectedZipProgram === "*all*") {
        const batchResp = await startBatchMigration(zipResult.job_id, createDummyFiles);
        setBatchId(batchResp.batch_id);
        setIsBatchRunning(true);
        setBatchProgramResults({});
        setRawBatchEvents([]);

        const cleanup = subscribeBatchEvents(batchResp.batch_id, (event) => {
          setRawBatchEvents((prev) => [...prev, event]);
          switch (event.type) {
            case "batch_started":
              setEvents((prev) => [...prev, {
                type: "planner_decision",
                payload: {
                  reasoning: `Batch migration started for ${event.payload.programs} programs: ${event.payload.migration_order.join(" → ")}`,
                  next_action: "BATCH",
                  target_draft_id: null,
                  step_count: 0,
                },
                run_id: batchResp.batch_id,
              }]);
              break;

            case "program_started":
              setEvents((prev) => [...prev, {
                type: "planner_decision",
                payload: {
                  reasoning: `Migrating ${event.payload.program_id} (${event.payload.index}/${event.payload.total})`,
                  next_action: "TRANSLATE",
                  target_draft_id: null,
                  step_count: event.payload.index,
                },
                run_id: batchResp.batch_id,
              }]);
              break;

            case "program_completed": {
              setBatchProgramResults((prev) => ({
                ...prev,
                [event.payload.program_id]: { verdict: event.payload.verdict },
              }));
              const verdictLabel = event.payload.verdict === "passed" ? "passed" : event.payload.verdict;
              setEvents((prev) => [...prev, {
                type: "cobol_validation",
                payload: {
                  passed: event.payload.verdict !== "error" && event.payload.verdict !== "errored",
                  message: `${event.payload.program_id} — ${verdictLabel}${event.payload.error ? `: ${event.payload.error}` : ""}`,
                },
                run_id: batchResp.batch_id,
              }]);
              break;
            }

            case "program_error":
              setBatchProgramResults((prev) => ({
                ...prev,
                [event.payload.program_id]: { verdict: "errored" },
              }));
              setEvents((prev) => [...prev, {
                type: "error",
                payload: { message: `${event.payload.program_id}: ${event.payload.error}` },
                run_id: batchResp.batch_id,
              }]);
              break;

            case "program_event": {
              const innerType = event.payload.event_type;
              const innerPayload = event.payload.event_payload;
              setEvents((prev) => [...prev, {
                type: innerType,
                payload: innerPayload,
                run_id: batchResp.batch_id,
              } as unknown as AgentEvent]);
              if (innerType === "draft_created" && innerPayload?.code) {
                const pid = event.payload.program_id.toLowerCase();
                setFinalCode((prev) => ({
                  ...prev,
                  [pid]: String(innerPayload.code),
                }));
                setActiveOutputFile(pid);
              }
              break;
            }

            case "batch_completed": {
              setIsStreaming(false);
              setIsBatchRunning(false);
              setIsStopping(false);
              const finalResults: Record<string, { verdict: string; confidence?: number }> = {};
              for (const [pid, r] of Object.entries(event.payload.program_results)) {
                finalResults[pid] = { verdict: r.verdict, confidence: undefined };
              }
              setBatchProgramResults(finalResults);
              if (event.payload.shared_model_code) {
                setFinalCode((prev) => ({
                  ...prev,
                  ["shared_models"]: event.payload.shared_model_code!,
                }));
              }
              const issuesList: string[] = Object.entries(event.payload.program_results)
                .filter(([, r]) => r.error)
                .map(([pid, r]) => `${pid}: ${r.error}`);
              if (event.payload.integration_issues) {
                issuesList.push(...event.payload.integration_issues.map(
                  (i: string) => `Integration: ${i}`
                ));
              }
              setEvents((prev) => [...prev, {
                type: "done",
                payload: {
                  verdict: event.payload.status === "completed" ? "passed" : "partial",
                  issues: issuesList,
                },
                run_id: batchResp.batch_id,
              }]);
              break;
            }

            case "batch_done":
              setIsStreaming(false);
              setIsBatchRunning(false);
              break;
          }
        });

        return cleanup;
      }

      let response: MigrationStartResponse;

      if (sourceType === "file" && uploadedFile) {
        response = await uploadAndMigrate(uploadedFile, 25, createDummyFiles);
      } else if (sourceType === "zip" && zipResult && selectedZipProgram) {
        response = await migrateFromZip(
          zipResult.job_id,
          selectedZipProgram,
          25,
          createDummyFiles,
        );
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
          const pid = response.run_id.toLowerCase();
          setFinalCode({ [pid]: event.payload.code });
          setActiveOutputFile(pid);
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
      const codeToShow = activeOutputFile && finalCode[activeOutputFile]
        ? finalCode[activeOutputFile]
        : Object.values(finalCode)[0];
      if (codeToShow) {
        await navigator.clipboard.writeText(codeToShow);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
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
    if (isStreaming || isBatchRunning) return "running";
    if (wasCancelled) return "cancelled";
    if (hasError) return "error";
    if (isDone && testsPassed) return "success";
    if (isDone) return "partial";
    return "idle";
  };

  const canStart =
    !isStreaming &&
    !isBatchRunning &&
    health?.status === "ok" &&
    (sourceType === "snippet" ? sourceRef.trim().length > 0 :
     sourceType === "zip" ? selectedZipProgram.length > 0 || zipResult !== null :
     uploadedFile !== null);

  // Build source files tree
  const sourceTree: FileNode[] = [];

  const ensureSourceTab = (id: string, label: string) => {
    setOpenSourceTabs((prev) => {
      if (prev.some((t) => t.id === id)) return prev;
      const next = [...prev, { id, label }];
      return next.length > 4 ? next.slice(-4) : next;
    });
  };

  if (sourceType === "zip" && zipResult) {
    const progs: FileNode[] = [];
    const cpy: FileNode[] = [];

    for (const [id, info] of Object.entries(zipResult.dependency_graph)) {
      const name = info.file_path.split("/").pop() || info.file_path.split("\\").pop() || id;
      const node: FileNode = {
        id,
        name,
        kind: "file",
      };
      if (info.file_path.toLowerCase().endsWith(".cpy")) {
        cpy.push(node);
      } else {
        progs.push(node);
      }
    }

    if (progs.length > 0) {
      sourceTree.push({ id: "programs", name: "PROGRAMS", kind: "folder", children: progs });
    }
    if (cpy.length > 0) {
      sourceTree.push({ id: "copybooks", name: "COPYBOOKS", kind: "folder", children: cpy });
    }
  } else {
    if (sourceRef) {
      const srcLabel = uploadedFile?.name || "snippet.cbl";
      sourceTree.push({
        id: "source",
        name: srcLabel,
        kind: "file",
      });
    }
  }

  const handleSelectSource = (id: string) => {
    setActiveSourceFile(id);
    if (sourceType === "zip" && zipResult) {
      const info = zipResult.dependency_graph[id];
      if (info) {
        const name = info.file_path.split("/").pop() || info.file_path.split("\\").pop() || id;
        ensureSourceTab(id, name);
      }
    }
  };

  // Build output files tree
  const outputTree: FileNode[] = (() => {
    const nodes: FileNode[] = [];
    for (const pid of Object.keys(finalCode)) {
      const isShared = pid === "shared_models";
      let status: FileNode["status"] = "ok";
      if (isShared && batchId) {
        const doneEv = events.find((e) => e.type === "done");
        if (doneEv && "payload" in doneEv && doneEv.payload) {
          const p = doneEv.payload as { issues?: string[] };
          if (p.issues?.some((i) => i.includes("Integration"))) {
            status = "warn";
          }
        }
      }
      nodes.push({
        id: pid,
        name: `${pid}.py`,
        kind: "file",
        status,
      });
    }
    return nodes;
  })();

  const ensureOutputTab = (pid: string) => {
    setOpenOutputTabs((prev) => {
      if (prev.some((t) => t.id === pid)) return prev;
      const next = [...prev, { id: pid, label: `${pid}.py` }];
      return next.length > 4 ? next.slice(-4) : next;
    });
  };

  if (activeOutputFile && !finalCode[activeOutputFile]) {
    // Reset if the current selection no longer exists
  }

  const handleSelectOutput = (id: string) => {
    setActiveOutputFile(id);
    if (finalCode[id]) {
      ensureOutputTab(id);
    }
  };

  const handleCloseSourceTab = (id: string) => {
    const remaining = openSourceTabs.filter((t) => t.id !== id);
    if (remaining.length === 0) return;
    setOpenSourceTabs(remaining);
    if (id === activeSourceFile) setActiveSourceFile(remaining[0]!.id);
  };

  const handleCloseOutputTab = (id: string) => {
    const remaining = openOutputTabs.filter((t) => t.id !== id);
    if (remaining.length === 0) return;
    setOpenOutputTabs(remaining);
    if (id === activeOutputFile) setActiveOutputFile(remaining[0]!.id);
  };

  // Derive job label
  const jobLabel = (() => {
    if (batchId) return batchId.slice(0, 8).toUpperCase();
    if (runId) return runId.slice(0, 8).toUpperCase();
    return "????";
  })();

  const sourceFileName = uploadedFile?.name || zipResult?.dependency_graph[selectedZipProgram]?.file_path?.split("/").pop()?.split("\\").pop() || "source.cbl";
  const outputFileName = Object.keys(finalCode).length > 0
    ? `${Object.keys(finalCode)[0]}.py`
    : "output.py";

  // Reduced motion handled via CSS @media (prefers-reduced-motion: reduce)
  

  const currentSourceCode = (() => {
    if (sourceType === "zip" && zipResult && activeSourceFile) {
      return zipResult.dependency_graph[activeSourceFile]?.source ?? sourceRef;
    }
    return sourceRef;
  })();

  const currentOutputCode = (() => {
    if (activeOutputFile && finalCode[activeOutputFile]) {
      return finalCode[activeOutputFile];
    }
    return Object.values(finalCode)[0];
  })();

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)", color: "var(--text)" }}>
      {/* Sweep animation */}
      {showSweep && (
        <div className="sweep-bar">
          <div className="sweep-bar-inner" />
        </div>
      )}

      {/* Header */}
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px 22px",
        borderBottom: "1px solid var(--line)",
        background: "var(--panel-2)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 14,
            fontWeight: 600,
            color: "var(--amber)",
          }}>
            //JOB
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 600, color: "var(--text)" }}>
            MIGR{jobLabel}
          </div>
          <div style={{
            width: 1,
            height: 20,
            background: "var(--line)",
          }} />
          <div style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 12.5,
            color: "var(--text-dim)",
          }}>
            {sourceFileName} &rarr; {outputFileName}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <RcBadge status={getStatus()} />

          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "5px 12px",
            border: "1px solid var(--line)",
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 12.5,
            fontWeight: 600,
            color: "var(--text-dim)",
          }}>
            {healthLoading ? (
              <span style={{ color: "var(--text-faint)" }}>Checking...</span>
            ) : health?.status === "ok" ? (
              <>
                <span style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "var(--teal)",
                  display: "inline-block",
                }} />
                SYSTEM CONNECTED
              </>
            ) : (
              <>
                <span style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "var(--rc16)",
                  display: "inline-block",
                }} />
                DISCONNECTED
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main workspace */}
      <PanelGroup orientation="horizontal" style={{ height: "calc(100vh - 57px)" }}>
        {/* ========== SYSIN Panel ========== */}
        <Panel defaultSize="36%" minSize="15%">
          <div className="panel-col" style={{ borderTop: "2px solid var(--amber-dim)", height: "100%" }}>
            <div className="panel-header">
              <span style={{ color: "var(--amber)" }}>SYSIN &middot; COBOL SOURCE</span>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "var(--text-faint)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>
                  {sourceType === "zip" && zipResult ? zipResult.programs_found : 1} FILE{sourceType === "zip" && zipResult && zipResult.programs_found !== 1 ? "S" : ""}
                </span>
                {sourceType === "zip" && zipResult && (
                  <button className="btn" style={{ fontSize: 10, padding: "3px 7px", display: "flex", alignItems: "center" }} onClick={() => setShowGraph(true)} title="Dependency graph">
                    <Share2 size={12} />
                  </button>
                )}
              </span>
            </div>

            <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
              {/* Source file explorer */}
              <FileExplorer
                title="MONOLITH_CORPUS"
                tree={sourceTree}
                activeId={activeSourceFile}
                onSelect={handleSelectSource}
                accent="amber"
              />

              {/* Source editor col */}
              <div className="editor-col">
                <TabStrip
                  tabs={openSourceTabs}
                  activeId={activeSourceFile}
                  onSelect={(id) => setActiveSourceFile(id)}
                  onClose={handleCloseSourceTab}
                  accent="amber"
                />

                {/* Punch-card ruler */}
                <div className="ruler">
                  <span className="seq">1.....6</span> 7 <span className="seq">8...12</span>....................................72
                </div>

                <div className="editor-wrap">
                  <Editor
                    height="100%"
                    defaultLanguage="cobol"
                    value={currentSourceCode}
                    onChange={(value) => !zipResult && setSourceRef(value || "")}
                    theme="vs-dark"
                    options={{
                      minimap: { enabled: false },
                      fontSize: 13,
                      fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
                      lineNumbers: "on",
                      scrollBeyondLastLine: false,
                      padding: { top: 12, bottom: 12 },
                      readOnly: isStreaming || sourceType !== "snippet",
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </Panel>

        <PanelResizeHandle className="resize-handle" />

        {/* ========== SYSPRINT Panel ========== */}
        <Panel defaultSize="28%" minSize="15%">
          <div className="panel-col" style={{ borderTop: "2px solid var(--line-soft)", height: "100%" }}>
            <div className="panel-header">
              <span style={{ color: "var(--text-dim)" }}>SYSPRINT &middot; AGENT LOG</span>
              <span style={{ color: "var(--text-faint)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>
                {events.length} EVENT{events.length !== 1 ? "S" : ""}
              </span>
            </div>

            <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
              {events.length === 0 ? (
                <div style={{
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--text-faint)",
                  fontFamily: "'IBM Plex Mono', monospace",
                  fontSize: 12,
                  gap: 8,
                }}>
                  <Terminal style={{ width: 32, height: 32, opacity: 0.3 }} />
                  <span>No events yet — start a migration</span>
                </div>
              ) : (
                events.map((event, index) => (
                  <LogEntry
                    key={`${event.type}-${index}`}
                    event={event}
                    index={index}
                    isLatest={index === events.length - 1}
                  />
                ))
              )}
            </div>
          </div>
        </Panel>

        <PanelResizeHandle className="resize-handle" />

        {/* ========== SYSOUT Panel ========== */}
        <Panel defaultSize="36%" minSize="15%">
          <div className="panel-col" style={{ borderTop: "2px solid var(--teal-dim)", height: "100%" }}>
            <div className="panel-header">
              <span style={{ color: "var(--teal)" }}>SYSOUT &middot; PYTHON</span>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {Object.keys(finalCode).length > 0 && (
                  <>
                    {Object.keys(finalCode).length > 1 && (
                      <button
                        className="btn"
                        onClick={async () => {
                          const JSZip = (await import("jszip")).default;
                          const zip = new JSZip();
                          for (const [pid, code] of Object.entries(finalCode)) {
                            zip.file(`${pid}.py`, code);
                          }
                          const blob = await zip.generateAsync({ type: "blob" });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = "migration-results.zip";
                          a.click();
                          URL.revokeObjectURL(url);
                        }}
                      >
                        <Download style={{ width: 12, height: 12 }} />
                        ALL (.ZIP)
                      </button>
                    )}
                    {isDone && runId && (
                      <button className="btn" onClick={handleDownloadCode}>
                        <Download style={{ width: 12, height: 12 }} />
                        .PY
                      </button>
                    )}
                    <button className="btn" onClick={handleCopyCode}>
                      {copied ? (
                        <Check style={{ width: 12, height: 12, color: "var(--teal)" }} />
                      ) : (
                        <Copy style={{ width: 12, height: 12 }} />
                      )}
                      {copied ? "COPIED!" : "COPY"}
                    </button>
                  </>
                )}
              </div>
            </div>

            <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
              {/* Output file explorer */}
              <FileExplorer
                title="MIGRATION_RESULTS"
                tree={outputTree}
                activeId={activeOutputFile}
                onSelect={handleSelectOutput}
                accent="teal"
              />

              {/* Output editor col */}
              <div className="editor-col">
                <TabStrip
                  tabs={openOutputTabs}
                  activeId={activeOutputFile}
                  onSelect={(id) => handleSelectOutput(id)}
                  onClose={handleCloseOutputTab}
                  accent="teal"
                />

                {/* Result banner */}
                {isDone && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="result-banner"
                    style={{
                      borderColor: testsPassed ? "var(--rc0)" : hasError ? "var(--rc8)" : "var(--rc4)",
                      color: testsPassed ? "var(--rc0)" : hasError ? "var(--rc8)" : "var(--rc4)",
                      background: `color-mix(in srgb, ${testsPassed ? "var(--rc0)" : hasError ? "var(--rc8)" : "var(--rc4)"} 8%, transparent)`,
                    }}
                  >
                    <span>
                      {testsPassed ? "\u2713 TESTS PASSED" : hasError ? "\u2717 TESTS FAILED" : "\u26A0 PARTIAL"}
                    </span>
                    {confidence != null && (
                      <span>CONFIDENCE {confidence.toFixed(2)}</span>
                    )}
                  </motion.div>
                )}

                <div className="editor-wrap">
                  {currentOutputCode ? (
                    <Editor
                      height="100%"
                      defaultLanguage="python"
                      value={currentOutputCode}
                      theme="vs-dark"
                      options={{
                        minimap: { enabled: false },
                        fontSize: 13,
                        fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
                        lineNumbers: "on",
                        scrollBeyondLastLine: false,
                        padding: { top: 12, bottom: 12 },
                        readOnly: true,
                      }}
                    />
                  ) : (
                    <div style={{
                      height: "100%",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--text-faint)",
                      fontFamily: "'IBM Plex Mono', monospace",
                      fontSize: 12,
                      gap: 8,
                    }}>
                      <Code2 style={{ width: 32, height: 32, opacity: 0.3 }} />
                      <span>No output yet — run a migration</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </Panel>
      </PanelGroup>

      {showGraph && zipResult && (
        <DependencyGraph
          graph={zipResult.dependency_graph}
          batchProgramResults={batchProgramResults}
          batchEvents={rawBatchEvents}
          migrationOrder={zipResult.migration_order}
          onSelectFile={(id) => {
            setActiveSourceFile(id);
            const info = zipResult.dependency_graph[id];
            if (info) {
              const name = info.file_path.split("/").pop() || info.file_path.split("\\").pop() || id;
              const existing = openSourceTabs.some((t) => t.id === id);
              if (!existing) {
                setOpenSourceTabs((prev) => {
                  const next = [...prev, { id, label: name }];
                  return next.length > 4 ? next.slice(-4) : next;
                });
              }
            }
          }}
          onClose={() => setShowGraph(false)}
        />
      )}

      {/* Source input options — hidden behind a fixed-bottom bar for snippet/file/zip selection */}
      <div style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        background: "var(--panel-2)",
        borderTop: "1px solid var(--line)",
        padding: "10px 22px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 12,
        zIndex: 20,
      }}>
        {/* Source type selector */}
        <div style={{ display: "flex", gap: 4 }}>
          {(["snippet", "file", "zip"] as const).map((type) => (
            <button
              key={type}
              onClick={() => setSourceType(type)}
              disabled={isStreaming}
              className="btn"
              style={{
                ...(sourceType === type ? { borderColor: "var(--amber)", color: "var(--amber)" } : {}),
                fontSize: 10,
                padding: "4px 10px",
              }}
            >
              {type === "snippet" ? "PASTE CODE" : type === "file" ? "UPLOAD FILE" : "ZIP"}
            </button>
          ))}
        </div>

        {/* Quick samples */}
        {sourceType === "snippet" && (
          <div style={{ display: "flex", gap: 4 }}>
            <button className="btn" style={{ fontSize: 10, padding: "4px 10px" }} onClick={() => setSourceRef(SAMPLE_COBOL)} disabled={isStreaming}>
              HELLO WORLD
            </button>
            <button className="btn" style={{ fontSize: 10, padding: "4px 10px" }} onClick={() => setSourceRef(SAMPLE_COBOL_COMPLEX)} disabled={isStreaming}>
              PAYROLL
            </button>
          </div>
        )}

        {/* File input areas */}
        {sourceType === "file" && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".cbl,.cob,.cobol,.cpy,.txt"
              className="hidden"
              disabled={isStreaming}
              onChange={(e) => {
                const selected = e.target.files?.[0] as File | undefined;
                if (selected) handleFileSelect(selected);
              }}
            />
            <button
              className="btn primary"
              style={{ fontSize: 10, padding: "4px 10px" }}
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
            >
              <Upload style={{ width: 12, height: 12 }} />
              {uploadedFile ? "CHANGE FILE" : "BROWSE"}
            </button>
            {uploadedFile && (
              <span style={{ color: "var(--text-dim)", fontSize: 11 }}>
                {uploadedFile.name} ({(uploadedFile.size / 1024).toFixed(1)} KB)
              </span>
            )}
          </>
        )}

        {/* ZIP area */}
        {sourceType === "zip" && (
          <>
            {zipLoading ? (
              <span style={{ color: "var(--amber)" }}>Analyzing ZIP...</span>
            ) : (
              <>
                <input
                  ref={zipRef}
                  type="file"
                  accept=".zip"
                  className="hidden"
                  disabled={isStreaming || zipLoading}
                  onChange={(e) => {
                    const selected = e.target.files?.[0] as File | undefined;
                    if (selected) handleZipUpload(selected);
                  }}
                />
                <button
                  className="btn"
                  style={{ fontSize: 10, padding: "4px 10px" }}
                  onClick={() => zipRef.current?.click()}
                  disabled={isStreaming || zipLoading}
                >
                  <Upload style={{ width: 12, height: 12 }} />
                  BROWSE
                </button>
                {zipError && (
                  <span style={{ color: "var(--rc8)", fontSize: 11 }}>
                    {zipError}
                  </span>
                )}
                {zipResult && (
                  <>
                    <span style={{ color: "var(--teal)", fontSize: 11 }}>
                      {zipResult.programs_found} programs, order: {zipResult.migration_order.join(" → ")}
                    </span>
                    <select
                      value={selectedZipProgram}
                      onChange={(e) => setSelectedZipProgram(e.target.value)}
                      disabled={isStreaming || isBatchRunning}
                      style={{
                        background: "var(--panel)",
                        border: "1px solid var(--line)",
                        color: "var(--text)",
                        padding: "4px 8px",
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: 11,
                      }}
                    >
                      <option value="">Select...</option>
                      <option value="*all*">All Programs (batch)</option>
                      {zipResult.migration_order
                        .filter((pid) => {
                          const info = zipResult.dependency_graph[pid];
                          return info && !info.file_path.toLowerCase().endsWith(".cpy");
                        })
                        .map((pid) => (
                          <option key={pid} value={pid}>{pid}</option>
                        ))}
                    </select>
                  </>
                )}
              </>
            )}
          </>
        )}

        <div style={{ flex: 1 }} />

        {/* Mock files checkbox */}
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-dim)", fontSize: 11 }}>
          <input
            type="checkbox"
            checked={createDummyFiles}
            onChange={(e) => setCreateDummyFiles(e.target.checked)}
            disabled={isStreaming}
            style={{ width: 14, height: 14 }}
          />
          Mock files
        </label>

        {/* Action buttons */}
        <button
          onClick={handleStartMigration}
          disabled={!canStart}
          className={isStreaming ? "btn" : "btn primary"}
          style={{
            fontSize: 12,
            padding: "7px 18px",
            fontWeight: 600,
            ...(isStreaming ? {
              borderColor: "var(--line)",
              color: "var(--text-dim)",
            } : {}),
          }}
        >
          {isStreaming ? (
            <>
              <Zap style={{ width: 14, height: 14 }} />
              {isStopping ? "STOPPING..." : "RUNNING..."}
            </>
          ) : (
            <>
              <Play style={{ width: 14, height: 14 }} />
              START
            </>
          )}
        </button>

        <AnimatePresence>
          {isStreaming && (
            <motion.button
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: "auto" }}
              exit={{ opacity: 0, width: 0 }}
              onClick={handleStopMigration}
              disabled={isStopping}
              className="btn"
              style={{
                fontSize: 12,
                padding: "7px 18px",
                fontWeight: 600,
                borderColor: isStopping ? "var(--line)" : "var(--rc16)",
                color: isStopping ? "var(--text-faint)" : "var(--rc16)",
              }}
            >
              <Square style={{ width: 14, height: 14 }} />
              STOP
            </motion.button>
          )}
        </AnimatePresence>
      </div>
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
