type Status = "idle" | "running" | "success" | "error" | "partial" | "cancelled";

interface RcBadgeProps {
  status: Status;
}

const config: Record<Status, { code: string; label: string; color: string }> = {
  idle:     { code: "????", label: "AWAITING JOB", color: "var(--text-faint)" },
  running:  { code: "....", label: "RUNNING",      color: "var(--text-dim)" },
  success:  { code: "0000", label: "SUCCESS",      color: "var(--rc0)" },
  partial:  { code: "0004", label: "PARTIAL",      color: "var(--rc4)" },
  error:    { code: "0008", label: "FAILED",       color: "var(--rc8)" },
  cancelled: { code: "0016", label: "CANCELLED",    color: "var(--rc16)" },
};

export default function RcBadge({ status }: RcBadgeProps) {
  const c = config[status];

  return (
    <div
      className={`rc-badge${status === "running" ? " running" : ""}`}
      style={{ borderColor: c.color, color: c.color }}
    >
      <span className="dot" style={{ background: c.color }} />
      RC={c.code} &middot; {c.label}
    </div>
  );
}
