import { useMemo, useCallback, useRef, useEffect, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
  MarkerType,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import type { BatchEvent } from "../lib/api";

type NodeStatus = "pending" | "running" | "passed" | "partial" | "failed" | "errored" | "skipped";

interface DepGraphProps {
  graph: Record<string, {
    file_path: string;
    source: string;
    calls: string[];
    copies: string[];
  }>;
  batchProgramResults: Record<string, { verdict: string; confidence?: number }>;
  batchEvents: BatchEvent[];
  migrationOrder: string[];
  onSelectFile: (id: string) => void;
  onClose: () => void;
}

const STATUS_ORDER = { pending: 0, running: 1, skipped: 2, passed: 3, partial: 4, failed: 5, errored: 6 };
const STATUS_COLORS: Record<NodeStatus, string> = {
  pending: "var(--text-faint)",
  running: "#4dabf7",
  skipped: "var(--text-faint)",
  passed: "#2f9e44",
  partial: "#e8a33d",
  failed: "#e03131",
  errored: "#862e2e",
};
const STATUS_ICONS: Record<NodeStatus, string> = {
  pending: "",
  running: "",
  skipped: "",
  passed: "\u2713",
  partial: "\u25D0",
  failed: "\u2717",
  errored: "\u2717",
};

function getNodeStatuses(
  programIds: string[],
  results: Record<string, { verdict: string; confidence?: number }>,
  batchEvents: BatchEvent[],
  migrationOrder: string[],
): Record<string, NodeStatus> {
  const started = new Set<string>();
  const completed = new Set<string>();

  for (const e of batchEvents) {
    if (e.type === "program_started") {
      started.add(e.payload.program_id);
    }
    if (e.type === "program_completed" || e.type === "program_error") {
      completed.add(e.payload.program_id);
    }
  }

  const activeId = [...started].find((pid) => !completed.has(pid));

  const statuses: Record<string, NodeStatus> = {};
  for (const pid of programIds) {
    if (results[pid]) {
      const v = results[pid].verdict;
      if (v === "passed" || v === "likely_equivalent") statuses[pid] = "passed";
      else if (v === "partial") statuses[pid] = "partial";
      else if (v === "failed") statuses[pid] = "failed";
      else statuses[pid] = "errored";
    } else if (pid === activeId) {
      statuses[pid] = "running";
    } else if (completed.has(pid)) {
      statuses[pid] = "errored";
    } else if (activeId && migrationOrder.indexOf(pid) < migrationOrder.indexOf(activeId) && !completed.has(pid)) {
      statuses[pid] = "skipped";
    } else {
      statuses[pid] = "pending";
    }
  }
  return statuses;
}

const NODE_WIDTH = 160;
const NODE_HEIGHT = 40;

function dagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 100, marginx: 20, marginy: 20 });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  return nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    };
  });
}

interface DepNodeData {
  label: string;
  isCopy: boolean;
  status: NodeStatus;
  filePath: string;
  source: string;
  calls: number;
  copies: number;
  hasResult: boolean;
  confidence?: number;
}

function DepNode({ data }: NodeProps) {
  const d = data as unknown as DepNodeData;
  const [hovered, setHovered] = useState(false);

  const baseBorder = d.isCopy ? "var(--teal)" : "var(--amber)";
  const borderColor = d.hasResult ? STATUS_COLORS[d.status] : baseBorder;
  const isRunning = d.status === "running";
  const isSkipped = d.status === "skipped";
  const icon = STATUS_ICONS[d.status];

  const loc = useMemo(() => d.source.split("\n").length, [d.source]);

  return (
    <div
      className={`dep-node${isRunning ? " dep-node-running" : ""}`}
      style={{
        background: d.isCopy ? "var(--teal-dim)" : "var(--amber-dim)",
        borderColor,
        opacity: isSkipped ? 0.35 : 1,
        position: "relative",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <span className="dep-node-label">{d.label}</span>
      {d.hasResult && icon && (
        <span
          className="dep-node-badge"
          style={{ background: STATUS_COLORS[d.status] }}
        >
          {icon}
        </span>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />

      {hovered && (
        <div className="dep-node-tooltip">
          <div className="tooltip-path">{d.filePath}</div>
          <div className="tooltip-stats">
            {loc} lines &middot; {d.calls} calls &middot; {d.copies} copies
            {d.hasResult && d.confidence !== undefined
              ? ` \u00B7 ${Math.round(d.confidence * 100)}% confidence`
              : d.hasResult
              ? ` \u00B7 ${d.status}`
              : ""}
          </div>
          <pre className="tooltip-preview">
            {d.source.split("\n").slice(0, 3).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}

const nodeTypes = { dep: DepNode };

function Flow({
  graph,
  batchProgramResults,
  batchEvents,
  migrationOrder,
  onSelectFile,
}: {
  graph: DepGraphProps["graph"];
  batchProgramResults: DepGraphProps["batchProgramResults"];
  batchEvents: DepGraphProps["batchEvents"];
  migrationOrder: DepGraphProps["migrationOrder"];
  onSelectFile: (id: string) => void;
}) {
  const { fitView } = useReactFlow();
  const initialized = useRef(false);

  const { nodes, edges } = useMemo(() => {
    const nodeList: Node[] = [];
    const edgeList: Edge[] = [];
    const programIds = Object.keys(graph);
    const statuses = getNodeStatuses(programIds, batchProgramResults, batchEvents, migrationOrder);

    for (const [id, info] of Object.entries(graph)) {
      const isCopy = info.file_path.toLowerCase().endsWith(".cpy");
      const s = statuses[id];
      nodeList.push({
        id,
        type: "dep",
        position: { x: 0, y: 0 },
        data: {
          label: id,
          isCopy,
          status: s,
          filePath: info.file_path,
          source: info.source,
          calls: info.calls.length,
          copies: info.copies.length,
          hasResult: s !== "pending" && s !== "running" && s !== "skipped",
          confidence: batchProgramResults[id]?.confidence,
        },
      });

      for (const callee of info.calls) {
        if (graph[callee]) {
          edgeList.push({
            id: `${id}->${callee}`,
            source: id,
            target: callee,
            type: "smoothstep",
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed, color: "var(--amber)" },
            style: { stroke: "var(--amber)", strokeWidth: 1.5 },
            label: "CALL",
            labelStyle: { fontSize: 10, fill: "var(--amber)" },
            labelBgStyle: { fill: "var(--bg)", fillOpacity: 0.8, borderRadius: 2 },
          });
        }
      }

      for (const copy of info.copies) {
        if (graph[copy]) {
          edgeList.push({
            id: `${id}->${copy}`,
            source: id,
            target: copy,
            type: "smoothstep",
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed, color: "var(--teal)" },
            style: { stroke: "var(--teal)", strokeWidth: 1, strokeDasharray: "4 2" },
            label: "COPY",
            labelStyle: { fontSize: 10, fill: "var(--teal)" },
            labelBgStyle: { fill: "var(--bg)", fillOpacity: 0.8, borderRadius: 2 },
          });
        }
      }
    }

    return { nodes: dagreLayout(nodeList, edgeList), edges: edgeList };
  }, [graph, batchProgramResults, batchEvents, migrationOrder]);

  useEffect(() => {
    if (!initialized.current && nodes.length > 0) {
      initialized.current = true;
      setTimeout(() => fitView({ duration: 200 }), 50);
    }
  }, [nodes, fitView]);

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    onSelectFile(node.id);
  }, [onSelectFile]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      fitView
      colorMode="dark"
      style={{ background: "var(--bg)" }}
      proOptions={{ hideAttribution: true }}
    >
      <Background color="var(--line-soft)" gap={20} />
      <Controls
        style={{
          background: "var(--panel)",
          border: "1px solid var(--line)",
          borderRadius: 4,
        }}
      />
      <MiniMap
        style={{ background: "var(--panel)", border: "1px solid var(--line)" }}
        nodeColor={(n: Node) => {
          const data = n.data as unknown as DepNodeData;
          return data.hasResult ? STATUS_COLORS[data.status] : data.isCopy ? "var(--teal-dim)" : "var(--amber-dim)";
        }}
        maskColor="rgba(11,13,15,0.7)"
      />
    </ReactFlow>
  );
}

export default function DependencyGraph({
  graph,
  batchProgramResults,
  batchEvents,
  migrationOrder,
  onSelectFile,
  onClose,
}: DepGraphProps) {
  const handleSelect = useCallback((id: string) => {
    onSelectFile(id);
    onClose();
  }, [onSelectFile, onClose]);

  const fileCount = Object.keys(graph).length;
  const programCount = Object.values(graph).filter(
    (info) => !info.file_path.toLowerCase().endsWith(".cpy"),
  ).length;
  const copybookCount = fileCount - programCount;

  return (
    <div className="graph-overlay" onClick={onClose}>
      <div className="graph-modal" onClick={(e) => e.stopPropagation()}>
        <div className="graph-header">
          <span style={{ color: "var(--amber)", fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 600 }}>
            DEPENDENCY GRAPH
          </span>
          <span style={{ color: "var(--text-faint)", fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>
            {programCount} PROGRAMS &middot; {copybookCount} COPYBOOKS
          </span>
          <button className="btn graph-close-btn" onClick={onClose}>
            ESC
          </button>
        </div>
        <ReactFlowProvider>
          <Flow
            graph={graph}
            batchProgramResults={batchProgramResults}
            batchEvents={batchEvents}
            migrationOrder={migrationOrder}
            onSelectFile={handleSelect}
          />
        </ReactFlowProvider>
        <div className="graph-legend">
          <span><span className="legend-dot" style={{ background: "var(--amber)" }} /> PROGRAM</span>
          <span><span className="legend-dot" style={{ background: "var(--teal)" }} /> COPYBOOK</span>
          <span className="legend-dot" style={{ background: STATUS_COLORS.passed, width: 6, height: 6 }} /> PASSED
          <span className="legend-dot" style={{ background: STATUS_COLORS.failed, width: 6, height: 6 }} /> FAILED
          <span className="legend-dot" style={{ background: STATUS_COLORS.running, width: 6, height: 6, animation: "blip 1.6s ease-in-out infinite" }} /> RUNNING
          <span style={{ color: "var(--text-faint)" }}>Click a node to open file</span>
        </div>
      </div>
    </div>
  );
}
