"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { getBetaFeatures, type BetaFeatures } from "../lib/api";

const BetaFeaturesContext = createContext<BetaFeatures | null>(null);

/**
 * Frontend projection of the backend-owned Beta product policy. Unknown or
 * unavailable policy fails closed so deferred controls never flash enabled.
 */
export function BetaFeaturesProvider({ children }: { children: React.ReactNode }) {
  const [features, setFeatures] = useState<BetaFeatures | null>(null);

  useEffect(() => {
    let active = true;
    void getBetaFeatures()
      .then((next) => {
        if (active) setFeatures(next);
      })
      .catch(() => {
        if (active) setFeatures({});
      });
    return () => { active = false; };
  }, []);

  return (
    <BetaFeaturesContext.Provider value={features}>
      {children}
    </BetaFeaturesContext.Provider>
  );
}

export function useBetaFeature(feature: string): boolean {
  const features = useContext(BetaFeaturesContext);
  return features?.[feature] === true;
}
