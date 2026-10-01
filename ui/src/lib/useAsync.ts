import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T) => void;
}

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

/** Keep data on refresh, but never expose a previous run or row after the loader's keys change. */
export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [result, setResult] = useState<{ data: T | null; error: string | null; loading: boolean; deps: DependencyList }>({ data: null, error: null, loading: true, deps: [...deps] });
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  const currentDeps = useRef(deps);
  currentDeps.current = deps;
  const sameDeps = (a: DependencyList, b: DependencyList) => a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const current = sameDeps(result.deps, deps);
  const data = current ? result.data : null;
  const error = current ? result.error : null;
  const loading = !current || result.loading;
  const setData = useCallback((value: T) => setResult({ data: value, deps: [...currentDeps.current], error: null, loading: false }), []);
  useEffect(() => {
    const id = ++seq.current;
    let live = true;
    setResult(previous => ({ data: sameDeps(previous.deps, deps) ? previous.data : null, error: null, loading: true, deps: [...deps] }));
    Promise.resolve().then(fn).then(
      (d) => {
        if (!live || seq.current !== id) return;
        setResult({ data: d, error: null, loading: false, deps: [...deps] });
      },
      (e) => {
        if (!live || seq.current !== id) return;
        setResult(previous => ({ ...previous, error: errorMessage(e), loading: false, deps: [...deps] }));
      },
    );
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}
