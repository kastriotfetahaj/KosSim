import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

export function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

// Tiny polling hook: invokes `loader` immediately then every `intervalMs`.
// Pass a stable deps array — reruns when deps change. Returns { data, error,
// loading, refresh }.
export function usePoll<T>(
  loader: () => Promise<T>,
  intervalMs: number,
  deps: ReadonlyArray<unknown>,
): { data: T | null; error: string | null; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    let timer: number | undefined;
    const run = async () => {
      try {
        const res = await loader();
        if (!cancelled.current) {
          setData(res);
          setError(null);
        }
      } catch (e: unknown) {
        if (!cancelled.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled.current) setLoading(false);
      }
    };
    run();
    if (intervalMs > 0) timer = window.setInterval(run, intervalMs);
    return () => {
      cancelled.current = true;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, intervalMs, ...deps]);

  return { data, error, loading, refresh: () => setTick((n) => n + 1) };
}

// Sync a URL search-param to React state.
export function useQueryParam(
  key: string,
  initial: string = "",
): [string, (next: string) => void] {
  const [params, setParams] = useSearchParams();
  const value = params.get(key) ?? initial;
  const set = (next: string) => {
    const sp = new URLSearchParams(params);
    if (next) sp.set(key, next);
    else sp.delete(key);
    setParams(sp, { replace: true });
  };
  return [value, set];
}
