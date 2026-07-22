import { X } from "lucide-react";

export interface Tab {
  id: string;
  label: string;
}

interface TabStripProps {
  tabs: Tab[];
  activeId: string;
  onSelect: (id: string) => void;
  onClose?: (id: string) => void;
  accent: "amber" | "teal";
}

export default function TabStrip({ tabs, activeId, onSelect, onClose, accent }: TabStripProps) {
  if (tabs.length === 0) return null;

  return (
    <div className="tabstrip">
      {tabs.map((tab) => (
        <div
          key={tab.id}
          className={`tab${tab.id === activeId ? " active" : ""}`}
          onClick={() => onSelect(tab.id)}
          style={tab.id === activeId ? {
            boxShadow: `inset 0 2px 0 ${accent === "amber" ? "var(--amber)" : "var(--teal)"}`,
          } : undefined}
        >
          {tab.label}
          {onClose && (
            <span
              className="tab-close"
              onClick={(e) => { e.stopPropagation(); onClose(tab.id); }}
            >
              <X size={11} strokeWidth={2} />
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
