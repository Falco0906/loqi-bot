"use client";

import React, { createContext, useContext, useState, useCallback, useMemo } from "react";
import { Prospect } from "../lib/types/prospect";

interface ProspectRegistryContextType {
  savedProspects: Prospect[];
  save: (prospect: Prospect) => void;
  unsave: (prospectId: string) => void;
  isSaved: (prospectId: string) => boolean;
}

const ProspectRegistryContext = createContext<ProspectRegistryContextType | null>(null);

export function ProspectRegistryProvider({ children }: { children: React.ReactNode }) {
  const [prospectMap, setProspectMap] = useState<Map<string, Prospect>>(new Map());

  const save = useCallback((prospect: Prospect) => {
    setProspectMap(prev => new Map(prev).set(prospect.id, prospect));
  }, []);

  const unsave = useCallback((prospectId: string) => {
    setProspectMap(prev => {
      const next = new Map(prev);
      next.delete(prospectId);
      return next;
    });
  }, []);

  const isSaved = useCallback((prospectId: string) => {
    return prospectMap.has(prospectId);
  }, [prospectMap]);

  const savedProspects = useMemo(() => Array.from(prospectMap.values()), [prospectMap]);

  return (
    <ProspectRegistryContext.Provider value={{ savedProspects, save, unsave, isSaved }}>
      {children}
    </ProspectRegistryContext.Provider>
  );
}

export const useProspectRegistry = () => {
  const ctx = useContext(ProspectRegistryContext);
  if (!ctx) throw new Error("useProspectRegistry must be used within a ProspectRegistryProvider");
  return ctx;
};
