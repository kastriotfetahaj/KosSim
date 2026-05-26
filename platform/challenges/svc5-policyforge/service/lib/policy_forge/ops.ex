defmodule PolicyForge.Ops do
  use Plug.Router

  plug :match
  plug :dispatch

  get "/auditor" do
    json(conn, %{hardcoded_auditor: "fixture", accepted: false})
  end

  get "/graphql" do
    json(conn, %{errors: [%{message: "inactive route"}]})
  end

  get "/renderer" do
    json(conn, %{renderer: "disabled", templates: ["status"]})
  end

  get "/cookie-flags" do
    json(conn, %{secure: true, httponly: true, source: "ui report"})
  end

  get "/csp-report" do
    json(conn, %{reports: [], leaks: []})
  end

  match _ do
    conn |> put_status(404) |> json(%{error: "not_found"})
  end

  defp json(conn, value) do
    conn
    |> put_resp_content_type("application/json")
    |> send_resp(conn.status || 200, Jason.encode!(value))
  end
end
