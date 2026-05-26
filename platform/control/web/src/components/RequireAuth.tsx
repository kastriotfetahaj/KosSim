import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

export default function RequireAuth({ children }: { children: JSX.Element }) {
  const { loading, username } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="msg">Checking session…</div>;
  if (!username)
    return <Navigate to="/admin/login" replace state={{ from: loc.pathname }} />;
  return children;
}
