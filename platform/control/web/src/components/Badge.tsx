const STATUS_COLORS: Record<string, string> = {
  SUCCESS: "#34d399",
  RECOVERING: "#fbbf24",
  MUMBLE: "#fb923c",
  OFFLINE: "#f87171",
  CRASHED: "#c084fc",
  accepted: "#34d399",
  duplicate: "#94a3b8",
  expired: "#f87171",
  invalid: "#f87171",
  own_flag: "#fbbf24",
  ERROR: "#f87171",
  WARNING: "#fbbf24",
  NOTIFICATION: "#a78bfa",
  IMPORTANT: "#38bdf8",
  INFO: "#94a3b8",
  DEBUG: "#64748b",
};

export function Badge({ children }: { children: string }) {
  const color = STATUS_COLORS[children] ?? "#94a3b8";
  return (
    <span
      className="badge"
      style={{
        background: `${color}22`,
        color,
        border: `1px solid ${color}55`,
      }}
    >
      {children}
    </span>
  );
}
