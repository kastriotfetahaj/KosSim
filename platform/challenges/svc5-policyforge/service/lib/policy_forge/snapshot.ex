defmodule PolicyForge.Snapshot do
  def read(snap, id, tenant_claim) do
    with snapshot when not is_nil(snapshot) <- PolicyForge.State.snapshot(snap),
         true <- id in snapshot.objects,
         obj when not is_nil(obj) <- PolicyForge.State.object(id) do
      if tenant_claim == "public" or obj.public do
        {:ok, obj}
      else
        :denied
      end
    else
      _ -> :missing
    end
  end
end
