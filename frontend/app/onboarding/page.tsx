"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../hooks/useAuth";
import {
  createWorkspace,
  getOnboardingProgress,
  saveWizardData,
} from "../../lib/onboarding-api";
import { createSession, getGmailAuthUrl } from "../../lib/api";
import { isTrustedGmailOAuthMessage, openGmailAuthPopup } from "../../lib/gmail-oauth";
import { generateStrategicProfile } from "../../lib/strategic-intelligence-api";
import type { StrategicProfile } from "../../lib/strategic-intelligence-api";
import { ProfileValue } from "../../components/shared/ProfileValue";

const ACTIVE_SESSION_KEY = "loqi_active_session_token";
const ONBOARDING_MESSAGES_KEY = "loqi_onboarding_messages";

type OnboardingState =
  | "conversational-discovery"
  | "knowledge-validation"
  | "workspace-connection"
  | "executive-briefing";

export default function OnboardingPage() {
  const router = useRouter();
  const { user, isLoading: authLoading, refreshUser } = useAuth();
  const [state, setState] = useState<OnboardingState>("conversational-discovery");
  const [profile, setProfile] = useState<OnboardingProfile | null>(null);
  const [strategicProfile, setStrategicProfile] = useState<StrategicProfile | null>(null);
  const [isGeneratingProfile, setIsGeneratingProfile] = useState(false);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [initializationError, setInitializationError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const userId = user && "id" in user ? user.id : "";

  // Restore onboarding state from backend on load
  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if ("onboarding_complete" in user && user.onboarding_complete) {
      // A completed account must never render the onboarding state machine.
      // In particular, stale browser conversation data must not be allowed to
      // advance into a state whose parent profile has not been loaded.
      router.replace("/mission-control");
      return;
    }
    (async () => {
      try {
        const progress = await getOnboardingProgress(userId);
        if (progress.onboarding_complete) {
          router.replace("/mission-control");
          return;
        }
        const data = progress.wizard_data || {};
        if (data.strategicProfile) {
          setStrategicProfile(data.strategicProfile as StrategicProfile);
        }
        const restoredProfile: Partial<OnboardingProfile> = {};
        if (data.companyDescription) restoredProfile.companyDescription = data.companyDescription as string;
        if (data.idealCustomer) restoredProfile.idealCustomer = data.idealCustomer as string;
        if (data.differentiation) restoredProfile.differentiation = data.differentiation as string;
        if (data.annualGoal) restoredProfile.annualGoal = data.annualGoal as string;
        if (data.biggestObstacle) restoredProfile.biggestObstacle = data.biggestObstacle as string;
        if (data.website) restoredProfile.website = data.website as string;
        if (Object.keys(restoredProfile).length > 0) {
          setProfile(restoredProfile as OnboardingProfile);
        }

        // Backend progress is authoritative. Only restore a client-side step
        // after confirming that the account is still incomplete server-side.
        const restoredStep = sessionStorage.getItem("loqi_onboarding_step");
        if (restoredStep) {
          sessionStorage.removeItem("loqi_onboarding_step");
          if (
            (restoredStep === "knowledge-validation" || restoredStep === "executive-briefing") &&
            Object.keys(restoredProfile).length === 0
          ) {
            setState("conversational-discovery");
          } else {
            setState(restoredStep as OnboardingState);
          }
          setLoadingInitial(false);
          return;
        }

        const savedStep = data.onboarding_step as string | undefined;
        if (savedStep === "knowledge-validation" && Object.keys(restoredProfile).length > 0) {
          setState("knowledge-validation");
        } else if (savedStep === "workspace-connection" && Object.keys(restoredProfile).length > 0) {
          setState("workspace-connection");
        } else if (savedStep === "executive-briefing" && Object.keys(restoredProfile).length > 0) {
          setState("executive-briefing");
        }
      } catch {
        // Do not present a blank or potentially destructive onboarding flow
        // when the progress endpoint is unavailable. The user can retry once
        // the backend is reachable.
        setInitializationError("We couldn't verify your onboarding status. Please try again.");
      }
      setLoadingInitial(false);
    })();
  }, [user, authLoading, userId, router]);

  useEffect(() => {
    if (authLoading) return;
    if (!user || ("onboarding_complete" in user && user.onboarding_complete)) {
      router.replace(user ? "/mission-control" : "/login");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    const token = (() => {
      try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
      catch { return null; }
    })();
    setSessionToken(token);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state]);

  // Listen for Gmail OAuth callback from popup
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      // Strict origin validation — only accept messages from the API origin.
      if (!isTrustedGmailOAuthMessage(event)) return;
      if (event.data?.type === "gmail-oauth") {
        setConnecting(false);
        const payload = event.data?.payload;
        if (payload?.ok) {
          setConnectError(null);
          setState("executive-briefing");
          // Persist step for restoration
          if (userId) {
            saveWizardData(userId, { onboarding_step: "executive-briefing" }, false).catch(() => {});
          }
        } else {
          setConnectError(payload?.error || "Connection failed. Please try again.");
        }
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [userId]);

  // Generate strategic profile from conversation data
  const generateProfile = async (p: OnboardingProfile) => {
    if (!userId) return null;
    setIsGeneratingProfile(true);
    try {
      const response = await generateStrategicProfile({
        company_description: p.companyDescription,
        ideal_customer: p.idealCustomer,
        differentiation: p.differentiation,
        annual_goal: p.annualGoal,
        biggest_obstacle: p.biggestObstacle,
        website: p.website,
        user_id: userId,
      });
      setStrategicProfile(response.profile);
      return response.profile;
    } catch (err) {
      console.error("Failed to generate strategic profile:", err);
      return null;
    } finally {
      setIsGeneratingProfile(false);
    }
  };

  // Persist profile to backend after knowledge validation
  const persistProfile = async (p: OnboardingProfile) => {
    if (!userId) return false;
    try {
      await saveWizardData(userId, {
        companyDescription: p.companyDescription,
        idealCustomer: p.idealCustomer,
        differentiation: p.differentiation,
        annualGoal: p.annualGoal,
        biggestObstacle: p.biggestObstacle,
        website: p.website,
      }, false);
      return true;
    } catch (err) {
      console.error("Failed to persist profile:", err);
      return false;
    }
  };

  const handleDiscoveryGenerate = async (p: OnboardingProfile): Promise<StrategicProfile | null> => {
    setProfile(p);
    try { localStorage.removeItem(ONBOARDING_MESSAGES_KEY); } catch { /* ignore */ }
    // Generate strategic profile from the conversation
    const generated = await generateProfile(p);
    // Persist strategic profile to backend wizard data
    if (generated && userId) {
      try {
        await saveWizardData(userId, {
          strategicProfile: generated,
          onboarding_step: "knowledge-validation",
        }, false);
      } catch (err) {
        console.error("Failed to persist strategic profile:", err);
      }
    }
    // Persist raw profile before advancing
    await persistProfile(p);
    return generated;
  };

  const handleDiscoveryComplete = (completedProfile: OnboardingProfile) => {
    // A browser-resumed conversation may already be complete even when the
    // backend wizard record is missing (for example after a dev-server
    // restart). Carry the child component's profile into the parent before
    // advancing so profile-dependent states can never render blank.
    setProfile(completedProfile);
    void persistProfile(completedProfile);
    setState("knowledge-validation");
  };

  const handleValidationProceed = async (updated: OnboardingProfile) => {
    setProfile(updated);
    // Persist updated profile before advancing
    await persistProfile(updated);
    // Persist step for restoration
    if (userId) {
      try {
        await saveWizardData(userId, { onboarding_step: "workspace-connection" }, false);
      } catch { /* step save is best-effort */ }
    }
    setState("workspace-connection");
  };

  const handleConnect = async () => {
    setConnecting(true);
    setConnectError(null);
    // PR10.9: open the popup synchronously (within the click gesture), then
    // navigate it to the auth URL. Never replace the onboarding tab.
    const result = await openGmailAuthPopup(() => getGmailAuthUrl(sessionToken || undefined));
    if (result.status === "blocked") {
      setConnecting(false);
      setConnectError("Popup blocked — please allow popups for this site and try again.");
    } else if (result.status === "error") {
      setConnecting(false);
      setConnectError("Failed to initiate OAuth flow.");
    }
    // "opened" keeps connecting=true until the popup reports back.
  };

  const handleEnterMissionControl = async () => {
    if (!userId || finishing) return;
    setFinishing(true);
    setFinishError(null);
    
    try {
      if (!profile) {
        throw new Error("No profile data available");
      }
      
      const finalData: Record<string, unknown> = {
        companyDescription: profile.companyDescription,
        idealCustomer: profile.idealCustomer,
        differentiation: profile.differentiation,
        annualGoal: profile.annualGoal,
        biggestObstacle: profile.biggestObstacle,
        website: profile.website,
        onboarding_step: "completed",
      };
      if (strategicProfile) {
        finalData.strategicProfile = strategicProfile;
      }
      
      // Mark wizard complete (saves + advances lifecycle)
      const wizardRes = await saveWizardData(userId, finalData, true);
      if (!wizardRes) {
        throw new Error("Failed to save onboarding data");
      }
      
      // Ensure Mission Control has a session-specific event stream before the
      // backend dispatches the automatic research job.
      let activeSessionToken = sessionToken;
      if (!activeSessionToken) {
        const created = await createSession("Loqi Operator");
        activeSessionToken = created.session_token;
        localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionToken);
        setSessionToken(activeSessionToken);
      }

      // Finalization automatically starts research from the saved profile.
      await createWorkspace(userId, "My Workspace", "my-workspace", activeSessionToken);
      
      // Refresh user
      await refreshUser();
      
      // Redirect
      router.push("/mission-control");
    } catch (err) {
      setFinishError(err instanceof Error ? err.message : "Failed to complete onboarding");
      setFinishing(false);
    }
  };

  if (authLoading || loadingInitial) {
    return (
      <main className="relative z-10 w-full min-h-screen onb-surface flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-[#000000] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">Loading...</p>
        </div>
      </main>
    );
  }

  if (initializationError) {
    return (
      <main className="relative z-10 w-full min-h-screen onb-surface flex items-center justify-center px-6">
        <div className="max-w-[520px] text-center space-y-6">
          <span className="material-symbols-outlined text-[#dc2626] text-4xl">error</span>
          <h1 className="font-['Libre_Caslon_Text'] text-[32px] text-[#1c1b1b]">
            We couldn&apos;t open your workspace
          </h1>
          <p className="font-['Inter'] text-[16px] leading-[1.6] text-[#444748]">
            {initializationError}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="px-8 py-4 bg-[#000000] text-[#ffffff] rounded-lg font-['Inter'] text-[16px]"
          >
            Try again
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="relative z-10 w-full min-h-screen onb-surface">
      {state === "conversational-discovery" && (
        <ConversationalDiscovery
          onGenerate={handleDiscoveryGenerate}
          onComplete={handleDiscoveryComplete}
        />
      )}
      {state === "knowledge-validation" && profile && (
        <KnowledgeValidation
          profile={profile}
          strategicProfile={strategicProfile}
          isLoading={isGeneratingProfile}
          onProceed={handleValidationProceed}
        />
      )}
      {state === "workspace-connection" && (
        <WorkspaceConnection
          connecting={connecting}
          error={connectError}
          onConnect={handleConnect}
        />
      )}
      {state === "executive-briefing" && profile && (
        <ExecutiveBriefing
          profile={profile}
          strategicProfile={strategicProfile}
          finishing={finishing}
          finishError={finishError}
          onEnterMissionControl={handleEnterMissionControl}
        />
      )}
      <div ref={bottomRef} />
    </main>
  );
}

/* ─── State 1: Conversational Discovery ─── */
type Message = {
  role: "loqi" | "user";
  text: string;
};

type OnboardingProfile = {
  companyDescription: string;
  idealCustomer: string;
  differentiation: string;
  annualGoal: string;
  biggestObstacle: string;
  website: string | null;
};

const QUESTIONS = [
  "What does your company do?",
  "Who usually buys your product?",
  "What problem do you solve better than anyone else?",
  "What is your biggest goal over the next 12 months?",
  "What is the biggest obstacle preventing that?",
];

const STRATEGIC_RESPONSES = [
  (answer: string) => {
    const topic = answer.length > 60 ? answer.slice(0, answer.lastIndexOf(" ", 60)) + "\u2026" : answer;
    return `Understood. You\u2019re building ${topic}. Who usually buys your product?`;
  },
  (answer: string) => {
    return `So your buyers are ${answer.toLowerCase()}. What problem do you solve better than anyone else?`;
  },
  (answer: string) => {
    const edge = answer.length > 60 ? answer.slice(0, answer.lastIndexOf(" ", 60)) + "\u2026" : answer;
    return `${edge}. That\u2019s your differentiator. What is your biggest goal over the next 12 months?`;
  },
  (answer: string) => {
    const goal = answer.length > 60 ? answer.slice(0, answer.lastIndexOf(" ", 60)) + "\u2026" : answer;
    return `So your north star is ${goal.toLowerCase()}. What is the biggest obstacle preventing that?`;
  },
  (answer: string) => {
    return `Understood. Thank you\u2014I have enough context to begin building your strategic profile. I\u2019ll process what you\u2019ve shared.`;
  },
];

function ConversationalDiscovery({
  onGenerate,
  onComplete,
}: {
  onGenerate: (profile: OnboardingProfile) => Promise<StrategicProfile | null>;
  onComplete: (profile: OnboardingProfile) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentQ, setCurrentQ] = useState(0);
  const [inputValue, setInputValue] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisComplete, setAnalysisComplete] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [loqiIsResponding, setLoqiIsResponding] = useState(false);
  const [hasWebsite, setHasWebsite] = useState(false);
  const [profile, setProfile] = useState<OnboardingProfile>({
    companyDescription: "",
    idealCustomer: "",
    differentiation: "",
    annualGoal: "",
    biggestObstacle: "",
    website: null,
  });
  const inputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const restoredRef = useRef(false);

  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    try {
      const raw = localStorage.getItem(ONBOARDING_MESSAGES_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        if (saved.messages && saved.messages.length > 0) {
          setMessages(saved.messages);
          setCurrentQ(saved.currentQ ?? 0);
          if (saved.profile) setProfile(saved.profile);
          if (saved.hasWebsite) setHasWebsite(true);
          if (saved.isAnalyzing && !saved.analysisComplete) {
            // A refresh happened mid-analysis: resume the real generation.
            setIsAnalyzing(true);
            const resumed = (saved.profile as OnboardingProfile | undefined) ?? profile;
            void runProfileGeneration(resumed);
          } else {
            if (saved.isAnalyzing) setIsAnalyzing(true);
            if (saved.analysisComplete) setAnalysisComplete(true);
          }
          return;
        }
      }
    } catch { /* ignore corrupted data */ }
    if (messages.length === 0) {
      setMessages([{ role: "loqi", text: QUESTIONS[0] }]);
    }
  }, []);

  useEffect(() => {
    if (messages.length === 0) return;
    try {
      localStorage.setItem(ONBOARDING_MESSAGES_KEY, JSON.stringify({
        messages,
        currentQ,
        profile,
        hasWebsite,
        isAnalyzing,
        analysisComplete,
        loqiIsResponding,
      }));
    } catch { /* storage full or unavailable */ }
  }, [messages, currentQ, profile, hasWebsite, isAnalyzing, analysisComplete]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isAnalyzing, analysisComplete, loqiIsResponding]);

  useEffect(() => {
    if (!isAnalyzing && !analysisComplete && !loqiIsResponding) {
      inputRef.current?.focus();
    }
  }, [messages, isAnalyzing, analysisComplete, loqiIsResponding]);

  const extractWebsite = (text: string): string | null => {
    const match = text.match(/https?:\/\/[^\s,;)]+/);
    return match ? match[0] : null;
  };

  const deliverResponse = (responseText: string, callback?: () => void) => {
    setLoqiIsResponding(true);
    const typingDelay = Math.min(600 + responseText.length * 8, 2000);
    setTimeout(() => {
      setLoqiIsResponding(false);
      const updated = [...messages];
      updated[updated.length - 1] = { role: "loqi", text: responseText };
      setMessages(updated);
      if (callback) callback();
    }, typingDelay);
  };

  const runProfileGeneration = async (nextProfile: OnboardingProfile) => {
    setIsAnalyzing(true);
    setAnalysisError(null);
    try {
      const generated = await onGenerate(nextProfile);
      if (!generated) {
        throw new Error("We couldn't generate your strategic profile. Please try again.");
      }
      setAnalysisComplete(true);
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : "We couldn't generate your strategic profile. Please try again.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSend = () => {
    const text = inputValue.trim();
    if (!text || loqiIsResponding) return;

    const updatedProfile = { ...profile };
    const keys: (keyof OnboardingProfile)[] = [
      "companyDescription",
      "idealCustomer",
      "differentiation",
      "annualGoal",
      "biggestObstacle",
    ];
    updatedProfile[keys[currentQ]] = text;

    const site = extractWebsite(text);
    if (site) {
      updatedProfile.website = site;
      setHasWebsite(true);
    }
    setProfile(updatedProfile);

    const userMsg: Message = { role: "user", text };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInputValue("");

    if (currentQ < QUESTIONS.length - 1) {
      const next = currentQ + 1;
      setMessages([...updated, { role: "loqi", text: "" }]);
      setCurrentQ(next);
      deliverResponse(STRATEGIC_RESPONSES[currentQ](text));
    } else {
      setMessages([...updated, { role: "loqi", text: "" }]);
      deliverResponse(STRATEGIC_RESPONSES[currentQ](text), () => {
        // The visible state is driven by the real profile-generation request.
        void runProfileGeneration(updatedProfile);
      });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <header className="fixed top-0 left-0 w-full z-50 bg-[#fdf8f8]/80 backdrop-blur-md px-6 py-6 flex justify-between items-center">
        <div className="flex items-center space-x-3">
          <span className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] font-bold text-[#000000] tracking-tight">
            Loqi
          </span>
          <span className="h-4 w-px bg-[#c4c7c7]/40" />
          <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest text-[#444748]">
            Continuous Strategy
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#444748] italic font-medium">
            Onboarding phase 1 of 4
          </span>
        </div>
      </header>

      <div className="pt-32 pb-48 px-6">
        <div className="max-w-[720px] mx-auto">
          <div className="mb-12 opacity-60">
            <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase block mb-2">
              Loqi Chief of Staff
            </span>
            <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase block">
              Initial Strategy Session
            </span>
          </div>

          <div className="space-y-0">
            {messages.map((msg, i) => {
              if (msg.text === "" && msg.role === "loqi") {
                return (
                  <article key={i} className="py-8">
                    <div className="flex items-baseline gap-8">
                      <div className="w-24 shrink-0 font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#444748] uppercase tracking-widest text-right font-medium">
                        Loqi
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] italic text-[#444748] font-normal">
                            Thinking
                          </span>
                          <span className="flex gap-1">
                            <span className="w-1.5 h-1.5 bg-[#444748] rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                            <span className="w-1.5 h-1.5 bg-[#444748] rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                            <span className="w-1.5 h-1.5 bg-[#444748] rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                          </span>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              }
              return (
                <article
                  key={i}
                  className={`py-8 border-b border-[#747878]/15 ${i < 4 && "onb-fade-in"} onb-stagger-${(i % 5) + 1}`}
                >
                <div className="flex items-baseline gap-8">
                  <div className="w-24 shrink-0 font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#444748] uppercase tracking-widest text-right font-medium">
                    {msg.role === "loqi" ? "Loqi" : "User"}
                  </div>
                  <div className="flex-1">
                    {msg.role === "loqi" ? (
                      <h2 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] italic text-[#000000] leading-tight font-normal whitespace-pre-line">
                        &ldquo;{msg.text}&rdquo;
                      </h2>
                    ) : (
                      <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#1c1b1b]">
                        {msg.text}
                      </p>
                    )}
                  </div>
                </div>
              </article>
              );
            })}

            {(isAnalyzing || analysisError || analysisComplete) && (
              <div className="mt-16 onb-fade-in">
                <div className="flex items-start gap-8">
                  <div className="w-24 shrink-0 flex justify-end pt-1">
                    <div className="w-2 h-2 rounded-full bg-[#000000] onb-pulse-dot" />
                  </div>
                  <div className="flex-1">
                    <div className="mb-8">
                      <p className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] italic text-[#444748] mb-6 font-normal">
                        {analysisComplete ? "Your strategic profile is ready." : analysisError ? "Your strategic profile could not be generated." : "Synthesizing your strategic profile&hellip;"}
                      </p>
                    </div>

                    <div className="bg-[#ffffff] onb-ambient-shadow p-8 rounded-lg border border-[#c4c7c7]/10">
                      <div className="flex items-center gap-3 mb-8">
                        <span
                          className="material-symbols-outlined text-[#000000]"
                          style={{ fontVariationSettings: "'FILL' 1" }}
                        >
                          manage_search
                        </span>
                        <h3 className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest font-bold">
                          Strategic Analysis
                        </h3>
                      </div>
                      <div className="space-y-6 relative">
                        <div className="absolute left-[7px] top-2 bottom-2 w-[1px] bg-[#c4c7c7]/30" />

                        <div className="flex gap-6 items-start onb-fade-in-fast">
                          <div className="relative z-10 w-4 h-4 rounded-full border-2 border-[#000000] bg-[#ffffff] flex items-center justify-center">
                            {analysisComplete ? (
                              <span className="material-symbols-outlined text-[10px] text-[#000000]">
                                check
                              </span>
                            ) : (
                              <div className="w-1.5 h-1.5 rounded-full bg-[#000000] onb-pulse-dot" />
                            )}
                          </div>
                          <div className="flex-1">
                            <p className="font-['Inter'] text-[16px] leading-[1.5] font-bold text-[#000000]">
                            {analysisComplete ? "Profile complete" : analysisError ? "Profile generation failed" : "Building your strategic model..."}
                            </p>
                            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] mt-1 italic">
                              {analysisError || "Turning what you shared into a working model of your company, buyers, and goals."}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {analysisComplete && (
              <div className="mt-12 text-center onb-fade-in">
                <button
                  onClick={() => onComplete(profile)}
                  className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest border border-[#000000]/20 px-10 py-4 rounded-sm hover:bg-[#000000] hover:text-[#ffffff] hover:border-[#000000] transition-all duration-300"
                >
                  Continue to Knowledge Validation
                </button>
              </div>
            )}
            {analysisError && (
              <div className="mt-8 text-center onb-fade-in">
                <button
                  onClick={() => void runProfileGeneration(profile)}
                  className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest border border-[#000000]/20 px-10 py-4 rounded-sm hover:bg-[#000000] hover:text-[#ffffff] hover:border-[#000000] transition-all duration-300"
                >
                  Retry profile generation
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {!isAnalyzing && !analysisComplete && (
        <footer className="fixed bottom-0 left-0 w-full px-6 z-50">
          <div className="max-w-[720px] mx-auto">
            <div className={`bg-[#ffffff]/80 backdrop-blur-xl rounded-full onb-ambient-shadow border ${loqiIsResponding ? "border-[#c4c7c7]/10 opacity-60" : "border-[#c4c7c7]/20"} p-2 flex items-center gap-4 transition-all`}>
              <div className="pl-6 flex-1">
                  <input
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={loqiIsResponding}
                  className="w-full bg-transparent border-none focus:ring-0 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] placeholder:text-[#444748]/40 py-3 outline-none disabled:cursor-not-allowed"
                  placeholder="Respond to Loqi..."
                  type="text"
                />
              </div>
              <div className="flex items-center gap-2 pr-2">
                <button
                  onClick={handleSend}
                  className="bg-[#000000] text-[#ffffff] px-6 py-3 rounded-full font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium font-bold active:scale-95 transition-all"
                >
                  SEND
                </button>
              </div>
            </div>
          </div>
        </footer>
      )}

      <div className="fixed bottom-24 right-24 w-48 h-48 opacity-10 pointer-events-none grayscale">
        <div className="w-full h-full bg-gradient-to-br from-[#f5f0eb] via-[#fdf8f8] to-[#e8e0d8]" />
      </div>
    </>
  );
}

/* ─── State 2: Knowledge Validation ─── */

function KnowledgeValidation({
  profile,
  strategicProfile,
  isLoading,
  onProceed,
}: {
  profile: OnboardingProfile;
  strategicProfile: StrategicProfile | null;
  isLoading: boolean;
  onProceed: (updated: OnboardingProfile) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [local, setLocal] = useState(profile);

  const source = profile.website ? "Conversation + Website" : "Conversation";

  const cards = [
    {
      key: "companyDescription" as keyof OnboardingProfile,
      label: "Market Position",
      icon: "explore",
      belief: strategicProfile?.COMPANY_SUMMARY || "",
      raw: local.companyDescription,
    },
    {
      key: "idealCustomer" as keyof OnboardingProfile,
      label: "Ideal Customer Profile",
      icon: "group",
      belief: strategicProfile?.ICP || "",
      raw: local.idealCustomer,
    },
    {
      key: "annualGoal" as keyof OnboardingProfile,
      label: "Primary Objective",
      icon: "flag",
      belief: strategicProfile?.PRIMARY_OBJECTIVE || "",
      raw: local.annualGoal,
      span: true,
    },
    {
      key: "differentiation" as keyof OnboardingProfile,
      label: "Competitive Edge",
      icon: "trending_up",
      belief: strategicProfile?.DIFFERENTIATION || "",
      raw: local.differentiation,
    },
    {
      key: "biggestObstacle" as keyof OnboardingProfile,
      label: "Critical Challenge",
      icon: "warning",
      belief: strategicProfile?.CURRENT_CONSTRAINTS || "",
      raw: local.biggestObstacle,
    },
  ];

  const updateField = (key: keyof OnboardingProfile, val: string) => {
    setLocal((prev) => ({ ...prev, [key]: val }));
  };

  if (isLoading) {
    return (
      <div className="relative z-10 w-full min-h-screen px-6 pt-24 pb-16 overflow-x-hidden">
        <div className="max-w-[720px] mx-auto text-center">
          <div className="animate-pulse space-y-8">
            <div className="h-8 w-8 rounded-full bg-[#000000] mx-auto" />
            <p className="font-['Libre_Caslon_Text'] text-[24px] text-[#444748]">
              Analyzing your strategic position...
            </p>
            <div className="h-32 bg-[#ffffff] rounded-lg" />
          </div>
        </div>
      </div>
    );
  }

  if (!strategicProfile) {
    return (
      <div className="relative z-10 w-full min-h-screen px-6 pt-24 pb-16 overflow-x-hidden">
        <div className="max-w-[720px] mx-auto">
          <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg border border-[#c4c7c7]/20 space-y-4">
            <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#444748]">
              Strategic profile could not be generated. You can continue with
              your conversation answers, or go back and try again after
              reconnecting.
            </p>
            <button
              onClick={() => onProceed(local)}
              className="px-8 py-4 bg-[#000000] text-[#ffffff] rounded-lg font-['Inter'] text-[16px] leading-[1.5] transition-all duration-300 hover:bg-[#444748] active:scale-95"
            >
              Continue with conversation data
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative z-10 w-full min-h-screen px-6 pt-24 pb-16 overflow-x-hidden">
      <div className="max-w-[720px] mx-auto">
        <section className="space-y-16">
          <div className="flex gap-4 onb-fade-in-fast">
            <div className="w-8 h-8 rounded-full bg-[#000000] flex items-center justify-center shrink-0">
              <span
                className="material-symbols-outlined text-[#ffffff]"
                style={{ fontSize: 20 }}
              >
                radar
              </span>
            </div>
            <div className="max-w-[85%]">
              <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase mb-2">
                Loqi &middot; Strategic Intelligence
              </p>
              <p className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#000000] italic font-normal">
                &ldquo;I think I understand enough to investigate further...
                I&rsquo;ve processed the foundational data from your domain.
                Here is what I currently believe about your strategic
                position.&rdquo;
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 onb-fade-in-fast onb-stagger-1">
            {cards.map((card) => (
              <div
                key={card.key}
                className={`${card.span ? "md:col-span-2" : ""} bg-[#ffffff] p-6 rounded-lg onb-ambient-shadow border border-[#c4c7c7]/10 flex flex-col ${card.span ? "md:flex-row gap-8" : ""} transition-all duration-500 hover:scale-[1.01]`}
              >
                {card.span && (
                  <div className="md:w-1/3 shrink-0">
                    <div className="w-full h-48 rounded-lg overflow-hidden relative bg-gradient-to-br from-[#f5f0eb] via-[#fdf8f8] to-[#e8e0d8] flex items-center justify-center">
                      <span
                        className="material-symbols-outlined text-[#53625c]"
                        style={{ fontSize: 48 }}
                      >
                        flag
                      </span>
                    </div>
                  </div>
                )}
                <div className="flex flex-col justify-center flex-1">
                  <span
                    className="material-symbols-outlined text-[#53625c] mb-4"
                    style={{ fontSize: 24 }}
                  >
                    {card.icon}
                  </span>
                  <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase mb-1">
                    {card.label}
                  </p>
                  {editing ? (
                    <textarea
                      value={card.raw}
                      onChange={(e) => updateField(card.key, e.target.value)}
                      className="w-full bg-[#ebe7e6] border border-[#c4c7c7] rounded p-3 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] resize-none focus:ring-1 focus:ring-[#000000] focus:border-[#000000] outline-none"
                      rows={3}
                    />
                  ) : (
                    <>
                      <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-4 font-normal">
                        I currently believe&hellip;
                      </h3>
                      <div className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                        <ProfileValue value={card.belief || card.raw} />
                      </div>
                      {card.span && strategicProfile?.CONFIDENCE_LEVELS?.overall && (
                        <div className="mt-6 flex gap-2">
                          <span className="px-3 py-1 bg-[#ebe7e6] rounded-full font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#576660]">
                            {strategicProfile.CONFIDENCE_LEVELS.overall === "high" ? "High Confidence" : strategicProfile.CONFIDENCE_LEVELS.overall === "low" ? "Developing" : "Moderate Confidence"}
                          </span>
                          <span className="px-3 py-1 bg-[#ebe7e6] rounded-full font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#576660]">
                            Strategic Core
                          </span>
                        </div>
                      )}
                    </>
                  )}
                  <div className="mt-8 pt-4 border-t border-[#c4c7c7]/20">
                    <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#747878] italic font-medium">
                      Based on: {source}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="onb-fade-in-fast onb-stagger-2 max-w-[720px] mx-auto border-t border-[#c4c7c7]/20 pt-16 text-center">
            <p className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-8 font-normal">
              Does this alignment feel right to you?
            </p>
            <div className="flex flex-col md:flex-row gap-4 justify-center items-center">
              {editing ? (
                <button
                  onClick={() => onProceed(local)}
                  className="group relative px-8 py-4 bg-[#000000] text-[#ffffff] rounded-lg font-['Inter'] text-[16px] leading-[1.5] transition-all duration-300 hover:bg-[#444748] active:scale-95 flex items-center gap-2 overflow-hidden"
                >
                  <span>Confirm changes</span>
                  <span className="material-symbols-outlined text-sm group-hover:translate-x-1 transition-transform">
                    arrow_forward
                  </span>
                </button>
              ) : (
                <>
                  <button
                    onClick={() => onProceed(local)}
                    className="group relative px-8 py-4 bg-[#000000] text-[#ffffff] rounded-lg font-['Inter'] text-[16px] leading-[1.5] transition-all duration-300 hover:bg-[#444748] active:scale-95 flex items-center gap-2 overflow-hidden"
                  >
                    <span>Yes, proceed with investigation</span>
                    <span className="material-symbols-outlined text-sm group-hover:translate-x-1 transition-transform">
                      arrow_forward
                    </span>
                  </button>
                  <button
                    onClick={() => setEditing(true)}
                    className="px-8 py-4 bg-transparent border border-[#c4c7c7] text-[#444748] rounded-lg font-['Inter'] text-[16px] leading-[1.5] transition-all duration-300 hover:border-[#000000] hover:text-[#000000] active:scale-95"
                  >
                    Let&rsquo;s refine a few things
                  </button>
                </>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ─── State 3: Workspace Connection ─── */
function WorkspaceConnection({
  connecting,
  error,
  onConnect,
}: {
  connecting: boolean;
  error: string | null;
  onConnect: () => void;
}) {
  return (
    <div className="min-h-screen py-16 px-6 flex flex-col items-center">
      <div className="max-w-[720px] mx-auto w-full">
        <div className="flex items-center gap-4 mb-16">
          <div className="w-10 h-10 rounded-full bg-[#ebe7e6] flex items-center justify-center">
            <span
              className="material-symbols-outlined text-[#000000] text-xl"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              radar
            </span>
          </div>
          <div>
            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest">
              Loqi &middot; Chief of Staff
            </p>
            <h2 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] font-bold text-[#1c1b1b]">
              Loqi
            </h2>
          </div>
        </div>

        <div className="mb-16">
          <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#1c1b1b] italic">
            &ldquo;I know enough to begin. To actually work on your behalf I
            need access to your Google Workspace.&rdquo;
          </p>
        </div>

        <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg transition-all duration-700">
          <div className="flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 flex items-center justify-center bg-[#F1F1EF] rounded-full">
                <span className="material-symbols-outlined text-[#000000]">
                  mail
                </span>
              </div>
              <div>
                <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] font-normal">
                  Google Workspace
                </h3>
                <p className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#444748] font-medium">
                  Secure, read-write access to Drafts &amp; Calendar
                </p>
              </div>
            </div>
            <button
              onClick={onConnect}
              disabled={connecting}
              className="bg-[#000000] text-[#ffffff] px-8 py-3 font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium rounded-full active:scale-95 transition-all disabled:opacity-60 flex items-center gap-2"
            >
              {connecting ? (
                <>
                  <span className="material-symbols-outlined text-sm animate-spin">
                    refresh
                  </span>
                  Connecting...
                </>
              ) : (
                "Connect Account"
              )}
            </button>
          </div>
          
          {error && (
            <div className="mt-6 pt-6 border-t border-[#c4c7c7]/20">
              <div className="flex items-start gap-3">
                <span className="material-symbols-outlined text-[#ef4444] text-sm">error</span>
                <p className="font-['Inter'] text-[14px] leading-[1.5] text-[#ef4444]">
                  {error}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── State 4: Executive Briefing ─── */

function ExecutiveBriefing({
  profile,
  strategicProfile,
  finishing,
  finishError,
  onEnterMissionControl,
}: {
  profile: OnboardingProfile;
  strategicProfile: StrategicProfile | null;
  finishing: boolean;
  finishError: string | null;
  onEnterMissionControl: () => void;
}) {
  const sp = strategicProfile;
  const companySummary = sp?.COMPANY_SUMMARY || profile.companyDescription;
  const objective = sp?.PRIMARY_OBJECTIVE || profile.annualGoal;
  const constraints = sp?.CURRENT_CONSTRAINTS || profile.biggestObstacle;
  const icp = sp?.ICP || profile.idealCustomer;
  const differentiation = sp?.DIFFERENTIATION || profile.differentiation;
  const hasData = !!(companySummary || objective || constraints);
  const source = profile.website ? "Conversation + Website" : "Conversation";

  return (
    <div className="min-h-screen py-16 px-6 flex flex-col items-center">
      <div className="max-w-[720px] mx-auto w-full">
        <div className="flex items-center gap-4 mb-16">
          <div className="w-10 h-10 rounded-full bg-[#ebe7e6] flex items-center justify-center">
            <span
              className="material-symbols-outlined text-[#000000] text-xl"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              radar
            </span>
          </div>
          <div>
            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest">
              Loqi &middot; Chief of Staff
            </p>
            <h2 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] font-bold text-[#1c1b1b]">
              Loqi
            </h2>
          </div>
        </div>

        <div className="mb-12 onb-fade-in">
          <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#1c1b1b]">
            &ldquo;I&rsquo;ve processed our session. Here is your executive briefing
            based on the strategic position we established.&rdquo;
          </p>
        </div>

        {hasData ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 onb-fade-in onb-stagger-1">
            {(companySummary || objective) && (
              <div className="md:col-span-2 onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg">
                <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest mb-4 block">
                  Strategic Alignment
                </span>
                <div className="font-['Libre_Caslon_Text'] text-[32px] leading-[1.3] text-[#1c1b1b] mb-6 font-normal">
                  <ProfileValue value={companySummary || "Immediate Priorities"} />
                </div>
                <div className="space-y-6">
                  {objective && (
                    <div className="flex items-start gap-4">
                      <span className="material-symbols-outlined text-[#000000] mt-1">
                        flag
                      </span>
                      <div>
                        <h5 className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium font-bold mb-1 text-[#1c1b1b]">
                          Objective
                        </h5>
                        <div className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                          <ProfileValue value={objective} />
                        </div>
                      </div>
                    </div>
                  )}
                  {constraints && (
                    <div className="flex items-start gap-4">
                      <span className="material-symbols-outlined text-[#000000] mt-1">
                        warning
                      </span>
                      <div>
                        <h5 className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium font-bold mb-1 text-[#1c1b1b]">
                          Critical Constraint
                        </h5>
                        <div className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                          <ProfileValue value={constraints} />
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {icp && (
              <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg border-t-2 border-[#d3e3dc]">
                <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest mb-2 block">
                  Market
                </span>
                <h4 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-4 font-normal">
                  Target Profile
                </h4>
                <div className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748] mb-6">
                  <ProfileValue value={icp} />
                </div>
                <div className="pt-4 border-t border-[#c4c7c7]/20">
                  <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#747878] italic font-medium">
                    Source: {source}
                  </span>
                </div>
              </div>
            )}

            {differentiation && (
              <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg border-t-2 border-[#000000]">
                <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest mb-2 block">
                  Positioning
                </span>
                <h4 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-4 font-normal">
                  Competitive Edge
                </h4>
                <div className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748] mb-6">
                  <ProfileValue value={differentiation} />
                </div>
                <div className="pt-4 border-t border-[#c4c7c7]/20">
                  <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#747878] italic font-medium">
                    Confidence: {sp?.CONFIDENCE_LEVELS?.overall || "Medium"}
                  </span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg border border-[#c4c7c7]/20 onb-fade-in">
            <div className="flex items-start gap-4">
              <span className="material-symbols-outlined text-[#747878] mt-1">
                info
              </span>
              <div>
                <h4 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-2 font-normal">
                  Insufficient Context
                </h4>
                <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                  We need additional workspace context before generating your first executive briefing.
                  Connect data sources or complete additional discovery to build strategic insights.
                </p>
              </div>
            </div>
          </div>
        )}

        <div className="mt-16 text-center py-16 onb-fade-in onb-stagger-2">
          <p className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] italic text-[#444748] mb-12 font-normal">
            &ldquo;The meeting has ended. Now work begins.&rdquo;
          </p>

          {finishError && (
            <div className="mb-8 bg-[#fef2f2] border border-[#fecaca] rounded-lg px-6 py-4">
              <div className="flex items-center gap-3 justify-center">
                <span className="material-symbols-outlined text-[#dc2626]">error</span>
                <p className="font-['Inter'] text-[14px] text-[#dc2626]">
                  {finishError}
                </p>
              </div>
            </div>
          )}

          <button
            onClick={onEnterMissionControl}
            disabled={finishing}
            className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest border border-[#000000]/20 px-10 py-4 rounded-sm hover:bg-[#000000] hover:text-[#ffffff] hover:border-[#000000] transition-all duration-300 disabled:opacity-50"
          >
            {finishing ? "Initializing..." : "Enter Mission Control"}
          </button>
        </div>
      </div>
    </div>
  );
}
