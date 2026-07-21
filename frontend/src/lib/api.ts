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

export interface ZipUploadResponse {
  job_id: string;
  programs_found: number;
  dependency_graph: Record<string, {
    file_path: string;
    source: string;
    calls: string[];
    copies: string[];
  }>;
  migration_order: string[];
  extract_path: string;
}

export async function migrateFromZip(
  jobId: string,
  programId: string,
  stepBudget: number = 25,
  createDummyFiles: boolean = false
): Promise<MigrationStartResponse> {
  const response = await fetch(
    `${API_BASE}/api/migrations/zip-job/${jobId}/migrate/${programId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        step_budget: stepBudget,
        create_dummy_files: createDummyFiles,
      }),
    }
  );
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to start ZIP migration: ${error}`);
  }
  return response.json() as Promise<MigrationStartResponse>;
}

export async function uploadZip(
  file: File
): Promise<ZipUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/api/migrations/upload-zip`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to upload ZIP: ${error}`);
  }
  return response.json() as Promise<ZipUploadResponse>;
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

export interface BatchStartResponse {
  batch_id: string;
  migration_order: string[];
}

export interface BatchProgramResult {
  program_id: string;
  status: string;
  verdict: string | null;
  error: string | null;
  final_code: string | null;
  run_id: string | null;
  draft_count: number;
  test_count: number;
  interface: {
    program_id: string;
    parameters: Array<{ name: string; pic_clause: string; level: number }>;
    copybooks_used: string[];
  } | null;
}

export interface BatchStatusResponse {
  batch_id: string;
  status: string;
  migration_order: string[];
  program_results: Record<string, BatchProgramResult>;
}

export type BatchEvent =
  | { type: "batch_started"; payload: { programs: number; migration_order: string[] }; batch_id: string }
  | { type: "program_started"; payload: { program_id: string; index: number; total: number; dependency_interfaces: string[] }; batch_id: string }
  | { type: "program_completed"; payload: { program_id: string; index: number; total: number; verdict: string; error: string | null }; batch_id: string }
  | { type: "program_error"; payload: { program_id: string; index: number; total: number; error: string }; batch_id: string }
  | { type: "batch_completed"; payload: { status: string; program_results: Record<string, { program_id: string; verdict: string; error: string | null }>; shared_model_code?: string | null; integration_issues?: string[] }; batch_id: string }
  | { type: "program_event"; payload: { program_id: string; index: number; total: number; event_type: string; event_payload: any }; batch_id: string }
  | { type: "batch_done"; batch_id: string };

export async function startBatchMigration(
  jobId: string,
  createDummyFiles: boolean = false
): Promise<BatchStartResponse> {
  const response = await fetch(
    `${API_BASE}/api/migrations/zip-job/${jobId}/batch`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ create_dummy_files: createDummyFiles }),
    }
  );
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to start batch migration: ${error}`);
  }
  return response.json() as Promise<BatchStartResponse>;
}

export async function getBatchStatus(batchId: string): Promise<BatchStatusResponse> {
  const response = await fetch(`${API_BASE}/api/migrations/batch/${batchId}`);
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to get batch status: ${error}`);
  }
  return response.json() as Promise<BatchStatusResponse>;
}

export async function stopBatchMigration(batchId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/migrations/batch/${batchId}/stop`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to stop batch: ${error}`);
  }
}

export function getBatchDownloadUrl(batchId: string, programId?: string): string {
  if (programId) {
    return `${API_BASE}/api/migrations/batch/${batchId}/download/${programId}`;
  }
  return `${API_BASE}/api/migrations/batch/${batchId}/download`;
}

export function subscribeBatchEvents(
  batchId: string,
  onEvent: (event: BatchEvent) => void
): () => void {
  const url = `${API_BASE}/api/migrations/batch/${batchId}/events`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (messageEvent: MessageEvent<string>) => {
    try {
      const data = JSON.parse(messageEvent.data) as BatchEvent;
      onEvent(data);

      if (data.type === "batch_done") {
        eventSource.close();
      }
    } catch {
      console.error("Failed to parse batch SSE event:", messageEvent.data);
    }
  };

  eventSource.onerror = () => {
    console.error("Batch SSE connection error");
    eventSource.close();
  };

  return () => {
    eventSource.close();
  };
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
