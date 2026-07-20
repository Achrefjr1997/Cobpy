const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
}

export interface MigrationRequest {
  source_type: "snippet" | "file";
  source_ref: string;
  step_budget?: number;
  create_dummy_files?: boolean;
}

export interface MigrationStartResponse {
  run_id: string;
  message: string;
}

export interface PlannerDecisionPayload {
  reasoning: string;
  next_action: string;
  target_draft_id: string | null;
  step_count: number;
}

export interface AnalysisReadyPayload {
  program_summary: string;
  io_contract: {
    inputs: Array<{ name: string; type: string; description: string }>;
    outputs: Array<{ name: string; type: string; description: string }>;
    invariants: string[];
  } | null;
}

export interface DraftCreatedPayload {
  draft_id: string;
  parent_id: string | null;
  code: string;
  rationale: string;
}

export interface TestsGeneratedPayload {
  tests: string;
}

export interface TestRunPayload {
  draft_id: string;
  passed: boolean;
  output: string;
  stderr: string;
  duration_ms: number;
}

export interface LessonLearnedPayload {
  lesson: string;
  recommended_action: string;
  root_cause?: string;
}

export interface ErrorPayload {
  message: string;
}

export interface CobolValidationPayload {
  passed: boolean;
  message: string;
  cobol_output?: string | null;
  compiler_output?: string;
  cobc_available?: boolean;
}

export interface DonePayload {
  final_draft_id?: string;
  total_drafts?: number;
  total_test_runs?: number;
  final_test_passed?: boolean;
  verdict?: string;
  confidence?: number | null;
  step_count?: number;
  validation_verdict?: string;
  external_dependency?: boolean;
  external_resource?: string;
  used_dummy_files?: boolean;
  issues?: string[];
}

export interface CancelledPayload {
  message: string;
}

export type AgentEvent =
  | { type: "planner_decision"; payload: PlannerDecisionPayload; run_id: string }
  | { type: "analysis_ready"; payload: AnalysisReadyPayload; run_id: string }
  | { type: "draft_created"; payload: DraftCreatedPayload; run_id: string }
  | { type: "tests_generated"; payload: TestsGeneratedPayload; run_id: string }
  | { type: "test_run"; payload: TestRunPayload; run_id: string }
  | { type: "lesson_learned"; payload: LessonLearnedPayload; run_id: string }
  | { type: "cobol_validation"; payload: CobolValidationPayload; run_id: string }
  | { type: "error"; payload: ErrorPayload; run_id: string }
  | { type: "cancelled"; payload: CancelledPayload; run_id: string }
  | { type: "done"; payload?: DonePayload; run_id: string };

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json() as Promise<HealthResponse>;
}

export async function startMigration(
  request: MigrationRequest
): Promise<MigrationStartResponse> {
  const response = await fetch(`${API_BASE}/api/migrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to start migration: ${error}`);
  }
  return response.json() as Promise<MigrationStartResponse>;
}

export async function uploadAndMigrate(
  file: File,
  stepBudget: number = 25,
  createDummyFiles: boolean = false
): Promise<MigrationStartResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("step_budget", String(stepBudget));
  formData.append("create_dummy_files", String(createDummyFiles));

  const response = await fetch(`${API_BASE}/api/migrations/upload`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to upload file: ${error}`);
  }
  return response.json() as Promise<MigrationStartResponse>;
}

export interface StopMigrationResponse {
  run_id: string;
  message: string;
  was_running: boolean;
}

export async function stopMigration(
  runId: string
): Promise<StopMigrationResponse> {
  const response = await fetch(`${API_BASE}/api/migrations/${runId}/stop`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to stop migration: ${error}`);
  }
  return response.json() as Promise<StopMigrationResponse>;
}

export function getDownloadUrl(runId: string): string {
  return `${API_BASE}/api/migrations/${runId}/download`;
}

export function subscribeEvents(
  runId: string,
  onEvent: (event: AgentEvent) => void
): () => void {
  const url = `${API_BASE}/api/migrations/${runId}/events`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (messageEvent: MessageEvent<string>) => {
    try {
      const data = JSON.parse(messageEvent.data) as AgentEvent;
      onEvent(data);

      if (data.type === "done") {
        eventSource.close();
      }
    } catch {
      console.error("Failed to parse SSE event:", messageEvent.data);
    }
  };

  eventSource.onerror = () => {
    console.error("SSE connection error");
    eventSource.close();
  };

  return () => {
    eventSource.close();
  };
}
