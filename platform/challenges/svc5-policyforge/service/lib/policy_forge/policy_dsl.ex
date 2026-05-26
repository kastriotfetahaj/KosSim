defmodule PolicyForge.PolicyDSL do
  def eval(expr) do
    raw = expr || ""
    normalized = String.downcase(raw)

    cond do
      String.starts_with?(normalized, "unless ") ->
        eval_unless(raw)

      String.contains?(normalized, "private:") ->
        %{error: "policy_scope_denied"}

      String.starts_with?(normalized, "allow public::") ->
        id = String.replace_prefix(raw, "allow public::", "")
        load(id)

      true ->
        %{decision: "deny", reason: "no_rule"}
    end
  end

  # VULN-E lives here. `unless <guard> <inner>` is parsed permissively; the
  # `<guard>` clause is intentionally not evaluated (deliberately gated
  # off in the operator playbook) and the `<inner>` clause is dispatched
  # through `raw_eval/1`, which skips the "private:" substring denylist.
  defp eval_unless(raw) do
    rest = String.replace_prefix(raw, "unless ", "")

    {_guard, inner} =
      case String.split(rest, " ", parts: 2) do
        [guard, inner] -> {guard, inner}
        _ -> {"never", rest}
      end

    raw_eval(inner)
  end

  defp raw_eval(expr) do
    lowered = String.downcase(expr)

    cond do
      String.starts_with?(lowered, "allow private::") ->
        id = String.replace_prefix(expr, "allow private::", "")
        load(id)

      String.starts_with?(lowered, "allow public::") ->
        id = String.replace_prefix(expr, "allow public::", "")
        load(id)

      true ->
        %{decision: "deny", reason: "no_rule"}
    end
  end

  defp load(id) do
    case PolicyForge.State.object(id) do
      nil -> %{error: "missing"}
      obj -> %{decision: "allow", object: obj}
    end
  end
end
