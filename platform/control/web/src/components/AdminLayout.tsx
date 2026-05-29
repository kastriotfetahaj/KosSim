import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { admin } from "../api";
import { useAuth } from "../auth";
import GameStatusBar from "./GameStatusBar";

type NavItem = {
  to: string;
  label: string;
  end?: boolean;
};

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [
      { to: "/admin", label: "Dashboard", end: true },
      { to: "/admin/analytics", label: "Analytics" },
      { to: "/admin/observability", label: "Observability" },
    ],
  },
  {
    label: "Game",
    items: [
      { to: "/admin/game", label: "Game control" },
      { to: "/admin/challenges", label: "Challenges" },
      { to: "/admin/checkers", label: "Checkers" },
      { to: "/admin/services", label: "Services" },
    ],
  },
  {
    label: "Teams",
    items: [
      { to: "/admin/teams", label: "Teams" },
      { to: "/admin/vulnboxes", label: "Vulnboxes" },
      { to: "/admin/network", label: "Network" },
    ],
  },
  {
    label: "Activity",
    items: [
      { to: "/admin/flags", label: "Flags" },
      { to: "/admin/submissions", label: "Submissions" },
      { to: "/admin/logs", label: "Logs" },
    ],
  },
  {
    label: "Content",
    items: [
      { to: "/admin/patches", label: "Patches" },
      { to: "/admin/wiki", label: "Wiki" },
    ],
  },
];

const NAV = NAV_GROUPS.flatMap((group) => group.items);

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
  const location = useLocation();
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [density, setDensity] = useState<"comfortable" | "compact">(() => {
    if (typeof window === "undefined") return "comfortable";
    return window.localStorage.getItem("kossim-admin-density") === "compact"
      ? "compact"
      : "comfortable";
  });

  const commands = useMemo(() => {
    const q = commandQuery.trim().toLowerCase();
    if (!q) return COMMAND_LINKS;
    return COMMAND_LINKS.filter(
      (cmd) =>
        cmd.label.toLowerCase().includes(q) ||
        cmd.detail.toLowerCase().includes(q),
    );
  }, [commandQuery]);

  const currentPage = useMemo(() => {
    return (
      NAV.find((item) =>
        item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
      ) ?? NAV[0]
    );
  }, [location.pathname]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    window.localStorage.setItem("kossim-admin-density", density);
  }, [density]);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

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
        setSidebarOpen(false);
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
      <button
        className={`sidebar-scrim ${sidebarOpen ? "open" : ""}`}
        type="button"
        aria-label="Close navigation"
        onClick={() => setSidebarOpen(false)}
      />
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <img src="/static/kct-logo.png" alt="" />
          <strong>
            Kos<span>Sim</span>
          </strong>
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
          {NAV_GROUPS.map((group) => (
            <section className="nav-section" key={group.label}>
              <div className="nav-section-title">{group.label}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                  onClick={() => setSidebarOpen(false)}
                >
                  {item.label}
                </NavLink>
              ))}
            </section>
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
        <header className="admin-topbar">
          <div className="admin-topbar-main">
            <button
              className="sidebar-toggle"
              type="button"
              aria-label="Open navigation"
              onClick={() => setSidebarOpen(true)}
            >
              <span />
              <span />
              <span />
            </button>
            <div>
              <div className="admin-breadcrumbs">
                <Link to="/admin">Admin</Link>
                <span>/</span>
                <span>{currentPage.label}</span>
              </div>
              <h1 className="admin-title">{currentPage.label}</h1>
            </div>
          </div>
          <div className="admin-topbar-actions">
            <button
              className="btn btn-ghost btn-xs"
              type="button"
              onClick={() =>
                setDensity((value) => (value === "compact" ? "comfortable" : "compact"))
              }
              title="Toggle table density"
            >
              {density === "compact" ? "Comfortable" : "Compact"}
            </button>
            <a className="btn btn-ghost btn-xs" href="/wiki" target="_blank" rel="noreferrer">
              Wiki
            </a>
            <a
              className="btn btn-ghost btn-xs"
              href="/public/scoreboard"
              target="_blank"
              rel="noreferrer"
            >
              Scoreboard
            </a>
            <button
              className="btn btn-ghost btn-xs"
              type="button"
              onClick={() => setCommandOpen(true)}
            >
              Command
            </button>
            <span className="admin-user-pill">{username ?? "admin"}</span>
          </div>
        </header>
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
