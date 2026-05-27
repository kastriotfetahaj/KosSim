import { useEffect, useRef, useState } from "react";

type Tone = "danger" | "warning" | "primary";

type ConfirmRequest = {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  requiredText?: string;
  tone?: Tone;
  action: () => Promise<void> | void;
};

export function useConfirmDialog() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = (next: ConfirmRequest) => {
    setError(null);
    setRequest(next);
  };

  const dialog = (
    <ConfirmDialog
      request={request}
      busy={busy}
      error={error}
      onCancel={() => {
        if (!busy) {
          setError(null);
          setRequest(null);
        }
      }}
      onConfirm={async () => {
        if (!request) return;
        setBusy(true);
        setError(null);
        try {
          await request.action();
          setRequest(null);
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        } finally {
          setBusy(false);
        }
      }}
    />
  );

  return { confirm, dialog };
}

function ConfirmDialog({
  request,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  request: ConfirmRequest | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!request) return;
    setTyped("");
    const id = window.setTimeout(() => {
      if (request.requiredText) inputRef.current?.focus();
      else confirmRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(id);
  }, [request]);

  useEffect(() => {
    if (!request) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, request]);

  if (!request) return null;

  const tone = request.tone ?? "danger";
  const canConfirm = !request.requiredText || typed === request.requiredText;

  return (
    <div
      className="confirm-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <section
        className={`confirm-dialog confirm-${tone}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-body"
      >
        <header>
          <span className="confirm-mark" aria-hidden>
            !
          </span>
          <div>
            <h2 id="confirm-title">{request.title}</h2>
            <p id="confirm-body">{request.body}</p>
          </div>
        </header>

        {request.requiredText && (
          <label className="confirm-field">
            <span>
              Type <code>{request.requiredText}</code> to continue
            </span>
            <input
              ref={inputRef}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={busy}
              autoComplete="off"
            />
          </label>
        )}

        {error && <div className="confirm-error">{error}</div>}

        <footer>
          <button className="btn btn-ghost" type="button" disabled={busy} onClick={onCancel}>
            {request.cancelLabel ?? "Cancel"}
          </button>
          <button
            ref={confirmRef}
            className={`btn ${tone === "danger" ? "btn-danger" : tone === "warning" ? "btn-warning" : "btn-primary"}`}
            type="button"
            disabled={busy || !canConfirm}
            onClick={onConfirm}
          >
            {busy ? "Working..." : request.confirmLabel}
          </button>
        </footer>
      </section>
    </div>
  );
}
