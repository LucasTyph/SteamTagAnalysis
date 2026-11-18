import { useMemo } from "react";
import { loadTags, type Tag } from "../data/queries";
import { type AsyncState, useAsync } from "./hooks";

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
