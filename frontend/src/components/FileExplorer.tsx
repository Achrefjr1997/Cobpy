export interface FileNode {
  id: string;
  name: string;
  kind: "file" | "folder";
  children?: FileNode[];
  status?: "ok" | "warn" | "pending" | null;
}

interface FileExplorerProps {
  title: string;
  tree: FileNode[];
  activeId: string;
  onSelect: (id: string) => void;
  accent: "amber" | "teal";
}

function FileRow({ node, activeId, onSelect, accent, depth }: {
  node: FileNode;
  activeId: string;
  onSelect: (id: string) => void;
  accent: "amber" | "teal";
  depth: number;
}) {
  if (node.kind === "folder") {
    return (
      <>
        <div className="tree-node folder" style={{ paddingLeft: `${14 + depth * 14}px` }}>
          <span>{depth === 0 ? "\u25BE" : ""}</span>
          {node.name}
        </div>
        {node.children?.map((child) => (
          <FileRow
            key={child.id}
            node={child}
            activeId={activeId}
            onSelect={onSelect}
            accent={accent}
            depth={depth + 1}
          />
        ))}
      </>
    );
  }

  const isActive = node.id === activeId;

  return (
    <div
      className={`tree-node indent${isActive ? ` active accent-${accent}` : ""}`}
      style={{ paddingLeft: `${14 + depth * 14}px` }}
      onClick={() => onSelect(node.id)}
    >
      <span>{node.name}</span>
      {node.status && (
        <span className={`status-dot ${node.status}`} />
      )}
    </div>
  );
}

export default function FileExplorer({ title, tree, activeId, onSelect, accent }: FileExplorerProps) {
  return (
    <div className="explorer">
      <div style={{
        padding: "8px 10px 4px 14px",
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: "10px",
        fontWeight: 600,
        color: "var(--text-faint)",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
      }}>
        {title}
      </div>
      {tree.map((node) => (
        <FileRow
          key={node.id}
          node={node}
          activeId={activeId}
          onSelect={onSelect}
          accent={accent}
          depth={0}
        />
      ))}
    </div>
  );
}
