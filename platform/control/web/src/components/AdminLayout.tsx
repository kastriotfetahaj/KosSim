import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { admin } from "../api";
import { useAuth } from "../auth";
import GameStatusBar from "./GameStatusBar";

const NAV = [
  { to: "/admin", label: "Dashboard", end: true, hint: "g d" },
  { to: "/admin/analytics", label: "Analytics" },
  { to: "/admin/observability", label: "Observability" },
  { to: "/admin/challenges", label: "Challenges" },
  { to: "/admin/checkers", label: "Checkers" },
  { to: "/admin/network", label: "Network" },
  { to: "/admin/vulnboxes", label: "Vulnboxes" },
  { to: "/admin/flags", label: "Flags" },
  { to: "/admin/submissions", label: "Submissions" },
  { to: "/admin/game", label: "Game" },
  { to: "/admin/teams", label: "Teams" },
  { to: "/admin/services", label: "Services" },
  { to: "/admin/patches", label: "Patches" },
  { to: "/admin/wiki", label: "Wiki" },
  { to: "/admin/logs", label: "Logs" },
];

const COMMAND_LINKS = [
  ...NAV.map((item) => ({
    label: item.label,
    detail: `Open ${item.label.toLowerCase()}`,
    to: item.to,
  })),
  {
    label: "Public scoreboard",
    detail: "Open spectator scoreboard in a new tab",
    href: "/public/scoreboard",
    external: true,
  },
  {
    label: "Export scoreboard",
    detail: "Download current scoreboard JSON",
    href: admin.scoreboardExportUrl(),
  },
  {
    label: "Export submissions",
    detail: "Download submissions CSV",
    href: admin.submissionsExportUrl(),
  },
  {
    label: "Export checker failures",
    detail: "Download checker failure CSV",
    href: admin.checkerFailuresExportUrl(),
  },
  {
    label: "Export audit log",
    detail: "Download audit log CSV",
    href: admin.logsExportUrl(),
  },
];

export default function AdminLayout() {
  const { username, logout } = useAuth();
  const nav = useNavigate();
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");

  const commands = useMemo(() => {
    const q = commandQuery.trim().toLowerCase();
    if (!q) return COMMAND_LINKS;
    return COMMAND_LINKS.filter(
      (cmd) =>
        cmd.label.toLowerCase().includes(q) ||
        cmd.detail.toLowerCase().includes(q),
    );
  }, [commandQuery]);

  // Global keyboard shortcuts:
  //   "/"  → focus the first search input on the current page
  //   Ctrl+K / Meta+K → open the command menu
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen(true);
        return;
      }
      if (e.key === "Escape") {
        setCommandOpen(false);
        return;
      }
      const tgt = e.target as HTMLElement | null;
      const inField =
        tgt &&
        (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.isContentEditable);
      if (inField) return;
      if (e.key === "/") {
        const el = document.querySelector<HTMLInputElement>(".search input");
        if (el) {
          e.preventDefault();
          el.focus();
          el.select();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const runCommand = (cmd: (typeof COMMAND_LINKS)[number]) => {
    setCommandOpen(false);
    setCommandQuery("");
    if ("href" in cmd && cmd.href) {
      if (cmd.external) {
        window.open(cmd.href, "_blank", "noopener,noreferrer");
      } else {
        window.location.href = cmd.href;
      }
      return;
    }
    if ("to" in cmd && cmd.to) nav(cmd.to);
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          Kos<span>Sim</span>
          <small>Ops</small>
        </div>
        <button
          className="command-trigger"
          type="button"
          onClick={() => setCommandOpen(true)}
        >
          <span>Command</span>
          <kbd>Ctrl K</kbd>
        </button>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <a className="footer-link" href="/public/scoreboard" target="_blank" rel="noreferrer">
            Public scoreboard ↗
          </a>
          <div className="kbd-row">
            <span>Tip</span>
            <kbd>/</kbd>
            <span>focus search</span>
          </div>
          <div className="user-line">
            <span className="user">{username ?? "—"}</span>
            <button
              className="btn btn-ghost btn-xs"
              onClick={async () => {
                await logout();
                nav("/admin/login", { replace: true });
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <GameStatusBar />
        <Outlet />
      </main>
      {commandOpen && (
        <div
          className="command-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setCommandOpen(false);
          }}
        >
          <div className="command-panel" role="dialog" aria-label="Command menu">
            <input
              value={commandQuery}
              onChange={(e) => setCommandQuery(e.target.value)}
              placeholder="Search pages and exports..."
              autoFocus
            />
            <div className="command-list">
              {commands.map((cmd) => (
                <button
                  key={cmd.label}
                  className="command-item"
                  type="button"
                  onClick={() => runCommand(cmd)}
                >
                  <strong>{cmd.label}</strong>
                  <span>{cmd.detail}</span>
                </button>
              ))}
              {!commands.length && (
                <div className="command-empty">No matching command.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
