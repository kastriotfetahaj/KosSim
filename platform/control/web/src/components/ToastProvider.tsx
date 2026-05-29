import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ToastTone = "success" | "info" | "warning" | "danger";

type Toast = {
  id: number;
  message: string;
  tone: ToastTone;
};

type ToastContextValue = {
  pushToast: (message: string, tone?: ToastTone) => void;
};

type ToastEventDetail = {
  message: string;
  tone?: ToastTone;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function emitToast(message: string, tone: ToastTone = "info") {
  window.dispatchEvent(
    new CustomEvent<ToastEventDetail>("kossim:toast", {
      detail: { message, tone },
    }),
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

export default function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  const pushToast = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = Date.now() + Math.random();
      setToasts((items) => [...items.slice(-3), { id, message, tone }]);
      window.setTimeout(() => dismiss(id), 4200);
    },
    [dismiss],
  );

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<ToastEventDetail>).detail;
      if (!detail?.message) return;
      pushToast(detail.message, detail.tone ?? "info");
    };

    window.addEventListener("kossim:toast", handler);
    return () => window.removeEventListener("kossim:toast", handler);
  }, [pushToast]);

  const value = useMemo(() => ({ pushToast }), [pushToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => (
          <button
            key={toast.id}
            className={`toast toast-${toast.tone}`}
            type="button"
            onClick={() => dismiss(toast.id)}
          >
            <strong>{toast.tone}</strong>
            <span>{toast.message}</span>
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
