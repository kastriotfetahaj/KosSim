defmodule PolicyForge.Token do
  def sign(secret, user, groups) do
    body = Jason.encode!(%{user: user, groups: groups, exp: System.system_time(:second) + 86_400})
    body64 = Base.url_encode64(body, padding: false)
    sig = :crypto.mac(:hmac, :sha256, secret, body64) |> Base.url_encode64(padding: false)
    body64 <> "." <> sig
  end

  def verify(secret, token) do
    with [body64, sig] <- String.split(token || "", ".", parts: 2),
         expected <- :crypto.mac(:hmac, :sha256, secret, body64) |> Base.url_encode64(padding: false),
         true <- Plug.Crypto.secure_compare(expected, sig),
         {:ok, body} <- Base.url_decode64(body64, padding: false),
         {:ok, json} <- Jason.decode(body),
         true <- json["exp"] >= System.system_time(:second) do
      {:ok, json}
    else
      _ -> :error
    end
  end
end
