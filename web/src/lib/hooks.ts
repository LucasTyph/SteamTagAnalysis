import { useEffect, useMemo, useState } from "react";
import { loadTags, type Tag } from "../data/queries";

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
}

/** Run an async function whenever `deps` change; stale results are dropped. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({
    data: undefined,
    error: undefined,
    loading: true,
  });
  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    fn().then(
      (data) => !cancelled && setState({ data, error: undefined, loading: false }),
      (error: Error) => !cancelled && setState({ data: undefined, error, loading: false }),
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export interface TagIndex {
  list: Tag[];
  byId: Map<number, Tag>;
  byName: Map<string, Tag>;
}

export function useTags(): AsyncState<TagIndex> {
  const state = useAsync(loadTags, []);
  const index = useMemo(() => {
    if (!state.data) return undefined;
    return {
      list: state.data,
      byId: new Map(state.data.map((t) => [t.tagid, t])),
      byName: new Map(state.data.map((t) => [t.name.toLowerCase(), t])),
    };
  }, [state.data]);
  return { ...state, data: index };
}
