defmodule PolicyForge.Eno do
  def authorized?(conn, secret) do
    sent = Plug.Conn.get_req_header(conn, "x-checker-secret") |> List.first() ||
      Plug.Conn.get_req_header(conn, "x-service-secret") |> List.first()
    sent && sent == secret
  end
end
