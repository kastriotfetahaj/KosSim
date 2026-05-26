defmodule PolicyForge.Share do
  # Share tokens authorize export-style reads of a snapshot. The signature
  # binds ONLY the snapshot id; the read handler then looks up the object id
  # supplied in the URL path. This is the FS1 vulnerability: a share token
  # minted for the public snapshot unlocks every object in the store, not
  # just the public objects sealed inside that snapshot.

  def issue(secret, snap_id) do
    body64 = Base.url_encode64(snap_id, padding: false)
    sig = :crypto.mac(:hmac, :sha256, secret, body64) |> Base.url_encode64(padding: false)
    body64 <> "." <> sig
  end

  def verify(secret, token) do
    with [body64, sig] <- String.split(token || "", ".", parts: 2),
         expected <- :crypto.mac(:hmac, :sha256, secret, body64) |> Base.url_encode64(padding: false),
         true <- Plug.Crypto.secure_compare(expected, sig),
         {:ok, snap_id} <- Base.url_decode64(body64, padding: false) do
      {:ok, snap_id}
    else
      _ -> :error
    end
  end
end
