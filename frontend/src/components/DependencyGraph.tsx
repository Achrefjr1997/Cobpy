import { useMemo, useCallback, useRef, useEffect } from "react";
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

interface DepGraphProps {
  graph: Record<string, {
    file_path: string;
    source: string;
    calls: string[];
    copies: string[];
  }>;
  onSelectFile: (id: string) => void;
  onClose: () => void;
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

interface DepNodeData { label: string; isCopy: boolean; }

function DepNode({ data }: NodeProps) {
  const d = data as unknown as DepNodeData;
  return (
    <div
      className="dep-node"
      style={{
        background: d.isCopy ? "var(--teal-dim)" : "var(--amber-dim)",
        borderColor: d.isCopy ? "var(--teal)" : "var(--amber)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <span className="dep-node-label">{d.label}</span>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { dep: DepNode };

function Flow({ graph, onSelectFile }: {
  graph: DepGraphProps["graph"];
  onSelectFile: (id: string) => void;
}) {
  const { fitView } = useReactFlow();
  const initialized = useRef(false);

  const { nodes, edges } = useMemo(() => {
    const nodeList: Node[] = [];
    const edgeList: Edge[] = [];

    for (const [id, info] of Object.entries(graph)) {
      const isCopy = info.file_path.toLowerCase().endsWith(".cpy");
      nodeList.push({
        id,
        type: "dep",
        position: { x: 0, y: 0 },
        data: { label: id, isCopy },
      });

      for (const callee of info.calls) {
        if (graph[callee]) {
          edgeList.push({
            id: `${id}->${callee}`,
            source: id,
            target: callee,
            type: "smoothstep",
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: "var(--text-faint)", strokeWidth: 1.5 },
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
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: "var(--text-faint)", strokeWidth: 1, strokeDasharray: "4 2" },
          });
        }
      }
    }

    return { nodes: dagreLayout(nodeList, edgeList), edges: edgeList };
  }, [graph]);

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
        nodeColor={(n: Node) => n.data.isCopy ? "var(--teal-dim)" : "var(--amber-dim)"}
        maskColor="rgba(11,13,15,0.7)"
      />
    </ReactFlow>
  );
}

export default function DependencyGraph({ graph, onSelectFile, onClose }: DepGraphProps) {
  const handleSelect = useCallback((id: string) => {
    onSelectFile(id);
    onClose();
  }, [onSelectFile, onClose]);

  return (
    <div className="graph-overlay" onClick={onClose}>
      <div className="graph-modal" onClick={(e) => e.stopPropagation()}>
        <div className="graph-header">
          <span style={{ color: "var(--amber)", fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 600 }}>
            DEPENDENCY GRAPH
          </span>
          <span style={{ color: "var(--text-faint)", fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>
            {Object.keys(graph).length} FILES
          </span>
          <button className="btn graph-close-btn" onClick={onClose}>
            ESC
          </button>
        </div>
        <ReactFlowProvider>
          <Flow graph={graph} onSelectFile={handleSelect} />
        </ReactFlowProvider>
        <div className="graph-legend">
          <span><span className="legend-dot" style={{ background: "var(--amber)" }} /> PROGRAM</span>
          <span><span className="legend-dot" style={{ background: "var(--teal)" }} /> COPYBOOK</span>
          <span style={{ color: "var(--text-faint)" }}>Click a node to open file</span>
        </div>
      </div>
    </div>
  );
}
