defmodule PolicyForge.Router do
  use Plug.Router

  plug Plug.Static, at: "/static", from: "/app/priv/static"
  plug Plug.Parsers, parsers: [:json], pass: ["application/json"], json_decoder: Jason
  plug :match
  plug :dispatch

  get "/" do
    send_resp(conn, 200, File.read!("/app/priv/static/index.html"))
  end

  get "/health" do
    info = PolicyForge.State.info()
    json(conn, %{status: "up", name: "policyforge", service: "#{info.team}/#{info.service}"})
  end

  get "/whoami" do
    info = PolicyForge.State.info()
    json(conn, %{team: info.team, service: info.service, runtime: "elixir-plug-cowboy"})
  end

  get "/service" do
    info = PolicyForge.State.info()

    if PolicyForge.Eno.authorized?(conn, info.secret) do
      json(conn, %{serviceName: "policyforge", flagVariants: 3, noiseVariants: 3, havocVariants: 6})
    else
      conn |> put_status(403) |> json(%{error: "forbidden"})
    end
  end

  post "/" do
    info = PolicyForge.State.info()

    if !PolicyForge.Eno.authorized?(conn, info.secret) do
      conn |> put_status(403) |> json(%{error: "forbidden"})
    else
      task = conn.body_params
      method = String.upcase(to_string(task["method"] || ""))
      tick = task["related_round_id"] || task["current_round_id"] || 0
      payload = task["variant_id"] || 0

      case method do
        "PUTFLAG" ->
          flag = to_string(task["flag"] || "")

          if flag == "" do
            json(conn, %{result: "INTERNAL_ERROR", message: "missing flag"})
          else
            json(conn, %{result: "OK", attack_info: PolicyForge.State.put_flag(tick, payload, flag)})
          end

        "GETFLAG" ->
          result =
            if PolicyForge.State.get_flag(tick, payload, to_string(task["flag"] || "")),
              do: "OK",
              else: "MUMBLE"

          json(conn, %{result: result})

        "PUTNOISE" ->
          PolicyForge.State.put_noise(tick, payload)
          json(conn, %{result: "OK"})

        "GETNOISE" ->
          result = if PolicyForge.State.get_noise(tick, payload), do: "OK", else: "MUMBLE"
          json(conn, %{result: result})

        "HAVOC" ->
          result = if PolicyForge.State.havoc(tick, payload), do: "OK", else: "MUMBLE"
          json(conn, %{result: result})

        _ ->
          json(conn, %{result: "OK"})
      end
    end
  end

  post "/rpc" do
    req = conn.body_params
    method = to_string(req["method"] || "")
    params = req["params"] || %{}
    info = PolicyForge.State.info()

    result =
      case method do
        "session.guest" ->
          %{session: PolicyForge.Token.sign(info.secret, "guest", ["reader"])}

        "policy.eval" ->
          PolicyForge.PolicyDSL.eval(to_string(params["expr"] || ""))

        "policy.objects" ->
          %{objects: PolicyForge.State.objects()}

        "policy.simulate" ->
          %{decision: "deny", trace: [%{stage: "parse"}, %{stage: "evaluate"}]}

        _ ->
          %{error: "method_not_found"}
      end

    json(conn, %{jsonrpc: "2.0", id: req["id"], result: result})
  end

  get "/api/session/guest" do
    info = PolicyForge.State.info()
    json(conn, %{session: PolicyForge.Token.sign(info.secret, "guest", ["reader"])})
  end

  get "/api/objects" do
    json(conn, %{objects: PolicyForge.State.objects()})
  end

  get "/api/object/:id" do
    with {:ok, session} <- session(conn),
         obj when not is_nil(obj) <- PolicyForge.State.object(id),
         true <- PolicyForge.State.allowed?(session, id) do
      json(conn, obj)
    else
      false -> conn |> put_status(403) |> json(%{error: "denied"})
      nil -> conn |> put_status(404) |> json(%{error: "missing"})
      _ -> conn |> put_status(403) |> json(%{error: "bad_session"})
    end
  end

  get "/api/policy/eval" do
    with {:ok, _session} <- session(conn) do
      expr = conn.query_params["expr"] || ""
      json(conn, PolicyForge.PolicyDSL.eval(expr))
    else
      _ -> conn |> put_status(403) |> json(%{error: "bad_session"})
    end
  end

  get "/api/snapshot/:snap/object/:id" do
    case PolicyForge.Snapshot.read(snap, id, conn.query_params["tenant"]) do
      {:ok, obj} -> json(conn, obj)
      :missing -> conn |> put_status(404) |> json(%{error: "missing"})
      :denied -> conn |> put_status(403) |> json(%{error: "denied"})
    end
  end

  # FS1: share-token issuance. Only public snapshots may be exported; the
  # signature binds the snapshot id only. See PolicyForge.Share.
  get "/api/snapshot/share/issue" do
    info = PolicyForge.State.info()
    snap_id = conn.query_params["snap"] || ""

    case PolicyForge.State.snapshot(snap_id) do
      nil ->
        conn |> put_status(404) |> json(%{error: "missing_snapshot"})

      %{objects: object_ids} ->
        if Enum.all?(object_ids, fn id ->
             case PolicyForge.State.object(id) do
               %{public: true} -> true
               _ -> false
             end
           end) do
          json(conn, %{share_token: PolicyForge.Share.issue(info.secret, snap_id)})
        else
          conn |> put_status(403) |> json(%{error: "private_snapshot"})
        end
    end
  end

  # FS1 read path. Verifies the share token's signature (which binds only the
  # snapshot id), then returns whatever object id the caller asked for. The
  # missing bind between the token and the object id is VULN-D.
  get "/api/snapshot/share/:token/object/:id" do
    info = PolicyForge.State.info()

    case PolicyForge.Share.verify(info.secret, token) do
      {:ok, _snap_id} ->
        case PolicyForge.State.object(id) do
          nil -> conn |> put_status(404) |> json(%{error: "missing"})
          obj -> json(conn, obj)
        end

      :error ->
        conn |> put_status(403) |> json(%{error: "bad_share_token"})
    end
  end

  forward "/ops", to: PolicyForge.Ops

  match _ do
    conn |> put_status(404) |> json(%{error: "not_found"})
  end

  defp session(conn) do
    info = PolicyForge.State.info()
    PolicyForge.Token.verify(info.secret, conn.query_params["session"])
  end

  defp json(conn, value) do
    conn
    |> put_resp_content_type("application/json")
    |> send_resp(conn.status || 200, Jason.encode!(value))
  end
end
