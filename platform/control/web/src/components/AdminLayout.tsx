import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
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

export default function AdminLayout() {
  const { username, logout } = useAuth();
  const nav = useNavigate();

  // Global keyboard shortcuts:
  //   "/"  → focus the first search input on the current page
  //   "?"  → reveal the shortcut hint (transient)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
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

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          Kos<span>Sim</span>
          <small>Ops</small>
        </div>
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
    </div>
  );
}
