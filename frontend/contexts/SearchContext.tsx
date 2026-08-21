"use client";

import { createContext, useContext, useMemo, useState } from "react";

type SearchState = {
  query: string;
  setQuery: (query: string) => void;
};

const SearchContext = createContext<SearchState | null>(null);

export function SearchProvider({ children }: { children: React.ReactNode }) {
  const [query, setQuery] = useState("");
  const value = useMemo(() => ({ query, setQuery }), [query]);
  return <SearchContext.Provider value={value}>{children}</SearchContext.Provider>;
}

export function useWorkspaceSearch() {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error("useWorkspaceSearch must be used within SearchProvider");
  return ctx;
}
