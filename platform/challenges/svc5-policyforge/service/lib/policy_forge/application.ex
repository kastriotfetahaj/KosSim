defmodule PolicyForge.Application do
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {PolicyForge.State, []},
      {Plug.Cowboy, scheme: :http, plug: PolicyForge.Router, options: [port: 8080]}
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: PolicyForge.Supervisor)
  end
end
