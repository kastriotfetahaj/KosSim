import { Navigate, Route, Routes } from "react-router-dom";
import AdminLayout from "./components/AdminLayout";
import RequireAuth from "./components/RequireAuth";
import ToastProvider from "./components/ToastProvider";
import { AuthProvider } from "./auth";
import Scoreboard from "./pages/Scoreboard";
import Analytics from "./pages/admin/Analytics";
import Challenges from "./pages/admin/Challenges";
import Checkers from "./pages/admin/Checkers";
import Dashboard from "./pages/admin/Dashboard";
import Flags from "./pages/admin/Flags";
import Game from "./pages/admin/Game";
import Login from "./pages/admin/Login";
import Logs from "./pages/admin/Logs";
import Network from "./pages/admin/Network";
import Observability from "./pages/admin/Observability";
import Patches from "./pages/admin/Patches";
import Services from "./pages/admin/Services";
import Submissions from "./pages/admin/Submissions";
import Teams from "./pages/admin/Teams";
import Vulnboxes from "./pages/admin/Vulnboxes";
import Wiki from "./pages/admin/Wiki";
import { WikiIndex, WikiPageView } from "./pages/PublicWiki";

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Routes>
          <Route path="/" element={<Navigate to="/public/scoreboard" replace />} />
          <Route
            path="/scoreboard"
            element={
              <RequireAuth>
                <Scoreboard variant="internal" />
              </RequireAuth>
            }
          />
          <Route path="/public/scoreboard" element={<Scoreboard variant="public" />} />
          <Route path="/wiki" element={<WikiIndex />} />
          <Route path="/wiki/:slug" element={<WikiPageView />} />

          <Route path="/admin/login" element={<Login />} />
          <Route
            path="/admin"
            element={
              <RequireAuth>
                <AdminLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="observability" element={<Observability />} />
            <Route path="challenges" element={<Challenges />} />
            <Route path="checkers" element={<Checkers />} />
            <Route path="network" element={<Network />} />
            <Route path="vulnboxes" element={<Vulnboxes />} />
            <Route path="flags" element={<Flags />} />
            <Route path="submissions" element={<Submissions />} />
            <Route path="game" element={<Game />} />
            <Route path="teams" element={<Teams />} />
            <Route path="services" element={<Services />} />
            <Route path="patches" element={<Patches />} />
            <Route path="wiki" element={<Wiki />} />
            <Route path="logs" element={<Logs />} />
          </Route>

          <Route path="*" element={<p style={{ padding: 24 }}>Not found.</p>} />
        </Routes>
      </ToastProvider>
    </AuthProvider>
  );
}
