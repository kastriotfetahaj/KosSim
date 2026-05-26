defmodule PolicyForge.State do
  use Agent

  @public_object "public-incident"
  @public_snapshot "public-snap"

  def start_link(_opts) do
    Agent.start_link(fn -> init() end, name: __MODULE__)
  end

  def init do
    team = env("TEAM_NAME", "team")
    service = env("SERVICE_NAME", "svc5")
    secret = env("SERVICE_PUSH_SECRET", "rotate-secret")
    boot = env("BOOT_FLAG", "FLAG{BOOT_POLICYFORGE}")
    data_dir = env("POLICYFORGE_DATA_DIR", "/var/lib/policyforge")

    base = %{
      team: team,
      service: service,
      secret: secret,
      data_dir: data_dir,
      flags: %{},
      objects: %{},
      cache: %{},
      snapshots: %{}
    }

    state = load_state(base) |> seed_public()
    {_info, state} = put_flag_state(state, 0, 0, boot)
    {_info, state} = put_flag_state(state, 0, 1, boot <> "_LEDGER")
    {_info, state} = put_flag_state(state, 0, 2, boot <> "_AUDIT")
    state
  end

  def env(key, fallback), do: System.get_env(key) || fallback

  def info, do: Agent.get(__MODULE__, &Map.take(&1, [:team, :service, :secret]))

  def public_object, do: @public_object
  def public_snapshot, do: @public_snapshot

  defp seed_public(state) do
    obj = %{
      id: @public_object,
      tenant: state.team,
      class: "incident",
      owner: "guest",
      public: true,
      data: "public postmortem template",
      snapshot: @public_snapshot
    }
    snap = %{id: @public_snapshot, tenant: state.team, objects: [@public_object]}
    %{
      state
      | objects: Map.put_new(state.objects, @public_object, obj),
        snapshots: Map.put_new(state.snapshots, @public_snapshot, snap)
    }
  end

  defp variant_class(0), do: "incident"
  defp variant_class(1), do: "ledger-share"
  defp variant_class(2), do: "audit-record"
  defp variant_class(_), do: "incident"

  def put_flag(tick, payload, flag) do
    Agent.get_and_update(__MODULE__, fn state ->
      put_flag_state(state, tick, payload, flag)
    end)
  end

  defp put_flag_state(state, tick, payload, flag) do
    target = hash("#{state.team}:#{tick}:#{payload}:#{flag}")
    snapshot = hash("snap:#{target}")
    klass = variant_class(payload)

    secret_obj = %{
      id: target,
      tenant: state.team,
      class: klass,
      owner: "checker",
      public: false,
      data: flag,
      snapshot: snapshot
    }

    objects = Map.put(state.objects, target, secret_obj)

    snapshots =
      state.snapshots
      |> Map.put(snapshot, %{id: snapshot, tenant: state.team, objects: [target]})

    next = %{
      state
      | flags: Map.put(state.flags, {tick, payload}, flag),
        objects: objects,
        snapshots: snapshots,
        cache: %{}
    }

    persist(next)
    info = Jason.encode!(%{a: target, b: @public_object, c: snapshot, p: payload})
    {info, next}
  end

  def get_flag(tick, payload, expected) do
    Agent.get(__MODULE__, fn state ->
      Map.get(state.flags, {tick, payload}) == expected and
        Enum.any?(state.objects, fn {_id, obj} ->
          obj.data == expected and obj.class == variant_class(payload)
        end)
    end)
  end

  def objects do
    Agent.get(__MODULE__, fn state ->
      Enum.map(state.objects, fn {_id, obj} -> Map.drop(obj, [:data]) end)
    end)
  end

  def object(id), do: Agent.get(__MODULE__, fn state -> Map.get(state.objects, id) end)
  def snapshot(id), do: Agent.get(__MODULE__, fn state -> Map.get(state.snapshots, id) end)

  def allowed?(session, object_id) do
    Agent.get_and_update(__MODULE__, fn state ->
      obj = Map.fetch!(state.objects, object_id)
      key = "#{session["user"]}:#{obj.tenant}:#{obj.class}"

      case Map.fetch(state.cache, key) do
        {:ok, decision} ->
          {decision, state}

        :error ->
          decision =
            obj.public or obj.owner == session["user"] or "auditor" in (session["groups"] || [])

          {decision, %{state | cache: Map.put(state.cache, key, decision)}}
      end
    end)
  end

  def hash(text) do
    :crypto.hash(:sha256, text) |> Base.encode16(case: :lower) |> binary_part(0, 18)
  end

  def put_noise(tick, payload) do
    Agent.get_and_update(__MODULE__, fn state ->
      id = hash("#{state.team}:noise:#{tick}:#{payload}")

      obj = %{
        id: id,
        tenant: state.team,
        class: "sample",
        owner: "guest",
        public: true,
        data: "sample:#{state.service}:#{tick}:#{payload}",
        snapshot: "noise"
      }

      next = %{state | objects: Map.put(state.objects, id, obj)}
      persist(next)
      {id, next}
    end)
  end

  def get_noise(tick, payload) do
    Agent.get(__MODULE__, fn state ->
      id = hash("#{state.team}:noise:#{tick}:#{payload}")

      case Map.get(state.objects, id) do
        %{public: true, class: "sample"} -> true
        _ -> false
      end
    end)
  end

  def havoc(tick, payload) do
    put_noise(tick, payload)

    Agent.get(__MODULE__, fn state ->
      map_size(state.objects) > 0 and map_size(state.snapshots) >= 0
    end)
  end

  defp load_state(state) do
    path = Path.join(state.data_dir, "state.term")

    case File.read(path) do
      {:ok, raw} ->
        case :erlang.binary_to_term(raw) do
          %{flags: flags, objects: objects, cache: cache, snapshots: snapshots} ->
            %{state | flags: flags, objects: objects, cache: cache, snapshots: snapshots}

          _ ->
            state
        end

      _ ->
        state
    end
  rescue
    _ -> state
  end

  defp persist(state) do
    File.mkdir_p!(state.data_dir)
    data = Map.take(state, [:flags, :objects, :cache, :snapshots])
    File.write(Path.join(state.data_dir, "state.term"), :erlang.term_to_binary(data))
    File.write(Path.join(state.data_dir, "evaluations.log"), "#{map_size(state.objects)}\n")
    :ok
  end
end
