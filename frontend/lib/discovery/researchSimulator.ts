import { Prospect } from "../types/prospect";

export type SearchPhase = "idle" | "submitting" | "processing" | "completed" | "error";

export interface ResearchSimulatorCallbacks {
  onProgress: (phase: SearchPhase, progress: number) => void;
  onComplete: (results: Prospect[]) => void;
  onError: (error: string) => void;
}

export const runResearchSimulation = (query: string, callbacks: ResearchSimulatorCallbacks) => {
  callbacks.onProgress("submitting", 0);
  
  setTimeout(() => {
    callbacks.onProgress("processing", 10);
    
    // Simulate steps
    const steps = [
      { p: 30, phase: "processing" as SearchPhase },
      { p: 60, phase: "processing" as SearchPhase },
      { p: 90, phase: "processing" as SearchPhase },
    ];
    
    steps.forEach((step, i) => {
      setTimeout(() => {
        callbacks.onProgress(step.phase, step.p);
      }, (i + 1) * 800);
    });

    setTimeout(() => {
      const mockResults: Prospect[] = [
        { id: "1", company: "Acme Corp", contact: "Alice Smith", title: "CTO", location: "SF", summary: "AI SaaS scaling fast.", confidence: 0.95 },
        { id: "2", company: "Globex", contact: "Bob Jones", title: "VP Sales", location: "NYC", summary: "Enterprise fintech.", confidence: 0.88 },
      ];
      callbacks.onComplete(mockResults);
    }, 3200);
    
  }, 500);
};
