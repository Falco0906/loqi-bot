"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../hooks/useAuth";
import {
  createWorkspace,
  saveWizardData,
} from "../../lib/onboarding-api";
import { getGoogleOAuthUrl } from "../../lib/auth-api";

type OnboardingState =
  | "conversational-discovery"
  | "knowledge-validation"
  | "workspace-connection"
  | "executive-briefing";

export default function OnboardingPage() {
  const router = useRouter();
  const { user, refreshUser } = useAuth();
  const [state, setState] = useState<OnboardingState>("conversational-discovery");
  const [profile, setProfile] = useState<OnboardingProfile | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const userId = user && "id" in user ? user.id : "";

  useEffect(() => {
    if (!user || ("onboarding_complete" in user && user.onboarding_complete)) {
      router.push("/mission-control");
    }
  }, [user, router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state]);

  // Listen for OAuth callback from popup
  useEffect(() => {
    const handleOAuthMessage = (event: MessageEvent) => {
      if (event.data?.type === "oauth-callback") {
        setConnecting(false);
        if (event.data?.success) {
          setConnectError(null);
          setState("executive-briefing");
        } else {
          setConnectError(event.data?.error || "Connection failed. Please try again.");
        }
      }
    };
    window.addEventListener("message", handleOAuthMessage);
    return () => window.removeEventListener("message", handleOAuthMessage);
  }, []);

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

  const handleDiscoveryComplete = async (p: OnboardingProfile) => {
    setProfile(p);
    // Persist profile before advancing
    await persistProfile(p);
    setState("knowledge-validation");
  };

  const handleValidationProceed = async (updated: OnboardingProfile) => {
    setProfile(updated);
    // Persist updated profile before advancing
    await persistProfile(updated);
    setState("workspace-connection");
  };

  const handleConnect = async () => {
    setConnecting(true);
    setConnectError(null);
    try {
      const res = await getGoogleOAuthUrl();
      if (res.authorize_url) {
        const popup = window.open(res.authorize_url, "google-oauth", "width=600,height=700");
        if (!popup) {
          // Fallback: redirect in same window if popup blocked
          window.location.href = res.authorize_url;
        }
        // Popup is open - wait for message event
      } else {
        setConnecting(false);
        setConnectError("Failed to initiate OAuth flow.");
      }
    } catch (e) {
      setConnecting(false);
      setConnectError("Failed to connect. Please try again.");
    }
  };

  const handleEnterMissionControl = async () => {
    if (!userId || finishing) return;
    setFinishing(true);
    setFinishError(null);
    
    try {
      // 1. Validate we have a profile to save
      if (!profile) {
        throw new Error("No profile data available");
      }
      
      // 2. Save wizard data with actual profile
      const wizardRes = await saveWizardData(userId, {
        companyDescription: profile.companyDescription,
        idealCustomer: profile.idealCustomer,
        differentiation: profile.differentiation,
        annualGoal: profile.annualGoal,
        biggestObstacle: profile.biggestObstacle,
        website: profile.website,
      }, false);
      
      if (!wizardRes) {
        throw new Error("Failed to save onboarding data");
      }
      
      // 3. Mark wizard complete
      await saveWizardData(userId, {
        companyDescription: profile.companyDescription,
        idealCustomer: profile.idealCustomer,
        differentiation: profile.differentiation,
        annualGoal: profile.annualGoal,
        biggestObstacle: profile.biggestObstacle,
        website: profile.website,
      }, true);
      
      // 4. Create workspace
      await createWorkspace(userId, "My Workspace", "my-workspace");
      
      // 5. Refresh user
      await refreshUser();
      
      // 6. Only then redirect
      router.push("/mission-control");
    } catch (err) {
      setFinishError(err instanceof Error ? err.message : "Failed to complete onboarding");
      setFinishing(false);
    }
  };

  return (
    <main className="relative z-10 w-full min-h-screen onb-surface">
      {state === "conversational-discovery" && (
        <ConversationalDiscovery onComplete={handleDiscoveryComplete} />
      )}
      {state === "knowledge-validation" && profile && (
        <KnowledgeValidation
          profile={profile}
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

function ConversationalDiscovery({
  onComplete,
}: {
  onComplete: (profile: OnboardingProfile) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentQ, setCurrentQ] = useState(0);
  const [inputValue, setInputValue] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisComplete, setAnalysisComplete] = useState(false);
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

  useEffect(() => {
    if (messages.length === 0) {
      setMessages([{ role: "loqi", text: QUESTIONS[0] }]);
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isAnalyzing, analysisComplete]);

  useEffect(() => {
    if (!isAnalyzing && !analysisComplete) {
      inputRef.current?.focus();
    }
  }, [messages, isAnalyzing, analysisComplete]);

  const extractWebsite = (text: string): string | null => {
    const match = text.match(/https?:\/\/[^\s,;)]+/);
    return match ? match[0] : null;
  };

  const buildAcknowledgement = (qIndex: number, answer: string): string => {
    const preamble = [
      "Understood. You\u2019re ",
      "So your buyers are ",
      "So your edge is ",
      "So your north star is ",
      "Understood. ",
    ];
    const mirror = answer.length > 120
      ? answer.slice(0, answer.lastIndexOf(" ", 100)) + "\u2026"
      : answer;
    const nextQ = qIndex < QUESTIONS.length - 1 ? `\n\n${QUESTIONS[qIndex + 1]}` : "";
    return `${preamble[qIndex]}${mirror}.${nextQ}`;
  };

  const handleSend = () => {
    const text = inputValue.trim();
    if (!text) return;

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
    }
    setProfile(updatedProfile);

    const userMsg: Message = { role: "user", text };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInputValue("");

    if (currentQ < QUESTIONS.length - 1) {
      const next = currentQ + 1;
      const ack = buildAcknowledgement(currentQ, text);
      setMessages([...updated, { role: "loqi", text: ack }]);
      setCurrentQ(next);
    } else {
      const ack = buildAcknowledgement(currentQ, text);
      setMessages([...updated, { role: "loqi", text: ack }]);
      setIsAnalyzing(true);
      setTimeout(() => setAnalysisComplete(true), 3200);
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
              Session ID: LS-2024-X9
            </span>
            <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase block">
              Protocol: Editorial Deep-Dive
            </span>
          </div>

          <div className="space-y-0">
            {messages.map((msg, i) => (
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
            ))}

            {isAnalyzing && (
              <div className="mt-16 onb-fade-in">
                <div className="flex items-start gap-8">
                  <div className="w-24 shrink-0 flex justify-end pt-1">
                    <div className="w-2 h-2 rounded-full bg-[#000000] onb-pulse-dot" />
                  </div>
                  <div className="flex-1">
                    <div className="mb-8">
                      <p className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] italic text-[#444748] mb-6 font-normal">
                        &ldquo;Reading website&hellip;&rdquo;
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
                          Investigation Pipeline
                        </h3>
                      </div>
                      <div className="space-y-6 relative">
                        <div className="absolute left-[7px] top-2 bottom-2 w-[1px] bg-[#c4c7c7]/30" />

                        <div className="flex gap-6 items-start onb-fade-in-fast">
                          <div className="relative z-10 w-4 h-4 rounded-full bg-[#53625c] flex items-center justify-center">
                            <span className="material-symbols-outlined text-[10px] text-white">
                              check
                            </span>
                          </div>
                          <div className="flex-1">
                            <p className="font-['Inter'] text-[16px] leading-[1.5] font-medium text-[#1c1b1b]">
                              Reading website...
                            </p>
                            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] mt-1">
                              Analyzing landing page content and positioning signals.
                            </p>
                          </div>
                        </div>

                        <div className="flex gap-6 items-start onb-fade-in-fast onb-stagger-1">
                          <div className="relative z-10 w-4 h-4 rounded-full bg-[#53625c] flex items-center justify-center">
                            <span className="material-symbols-outlined text-[10px] text-white">
                              check
                            </span>
                          </div>
                          <div className="flex-1">
                            <p className="font-['Inter'] text-[16px] leading-[1.5] font-medium text-[#1c1b1b]">
                              Analyzing positioning...
                            </p>
                            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] mt-1">
                              Cross-referencing against market categories and competitor posture.
                            </p>
                          </div>
                        </div>

                        <div className="flex gap-6 items-start onb-fade-in-fast onb-stagger-2">
                          <div className="relative z-10 w-4 h-4 rounded-full bg-[#53625c] flex items-center justify-center">
                            <span className="material-symbols-outlined text-[10px] text-white">
                              check
                            </span>
                          </div>
                          <div className="flex-1">
                            <p className="font-['Inter'] text-[16px] leading-[1.5] font-medium text-[#1c1b1b]">
                              Comparing competitors...
                            </p>
                            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] mt-1">
                              Mapping differentiation vectors against peer set.
                            </p>
                          </div>
                        </div>

                        <div className="flex gap-6 items-start onb-fade-in-fast onb-stagger-3">
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
                              Building strategic model...
                            </p>
                            <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] mt-1 italic">
                              Synthesizing insights into an initial strategic position.
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
          </div>
        </div>
      </div>

      {!isAnalyzing && !analysisComplete && (
        <footer className="fixed bottom-0 left-0 w-full px-6 z-50">
          <div className="max-w-[720px] mx-auto">
            <div className="bg-[#ffffff]/80 backdrop-blur-xl rounded-full onb-ambient-shadow border border-[#c4c7c7]/20 p-2 flex items-center gap-4 transition-all">
              <div className="pl-6 flex-1">
                <input
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="w-full bg-transparent border-none focus:ring-0 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] placeholder:text-[#444748]/40 py-3 outline-none"
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
function inferBelief(field: keyof OnboardingProfile, text: string): string {
  const s = text.trim();
  const strip = (t: string) =>
    t
      .replace(/^(we|our|i)\s+(are|build|create|develop|make|offer|provide|specialize in|want|aim|need|plan|focus on|target|cater to|serve|work with|struggle with|face|deal with|battle)\s+/i, "")
      .replace(/^to |^a |^an /, "")
      .trim();

  const cleaned = strip(s);
  if (!cleaned) return s;

  const lower = cleaned.toLowerCase();

  switch (field) {
    case "companyDescription":
      if (/ai|machine learning|llm|gpt|neural/.test(lower))
        return `You're an AI-powered platform focused on ${cleaned.replace(/ai|artificial intelligence/gi, "").trim()}.`;
      return `Your organization operates as a ${cleaned} provider.`;
    case "idealCustomer":
      return `Your core audience consists of ${cleaned}.`;
    case "annualGoal":
      return `Your 12-month priority is ${cleaned}.`;
    case "differentiation":
      return `Your competitive edge is ${cleaned}.`;
    case "biggestObstacle":
      return `Your primary obstacle is ${cleaned}.`;
    default:
      return cleaned;
  }
}

function KnowledgeValidation({
  profile,
  onProceed,
}: {
  profile: OnboardingProfile;
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
      belief: inferBelief("companyDescription", local.companyDescription),
      raw: local.companyDescription,
    },
    {
      key: "idealCustomer" as keyof OnboardingProfile,
      label: "Ideal Customer Profile",
      icon: "group",
      belief: inferBelief("idealCustomer", local.idealCustomer),
      raw: local.idealCustomer,
    },
    {
      key: "annualGoal" as keyof OnboardingProfile,
      label: "Primary Objective",
      icon: "flag",
      belief: inferBelief("annualGoal", local.annualGoal),
      raw: local.annualGoal,
      span: true,
    },
    {
      key: "differentiation" as keyof OnboardingProfile,
      label: "Competitive Edge",
      icon: "trending_up",
      belief: inferBelief("differentiation", local.differentiation),
      raw: local.differentiation,
    },
    {
      key: "biggestObstacle" as keyof OnboardingProfile,
      label: "Critical Challenge",
      icon: "warning",
      belief: inferBelief("biggestObstacle", local.biggestObstacle),
      raw: local.biggestObstacle,
    },
  ];

  const updateField = (key: keyof OnboardingProfile, val: string) => {
    setLocal((prev) => ({ ...prev, [key]: val }));
  };

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
                Loqi &middot; Intelligence Agency
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
                    <div className="w-full h-48 rounded-lg overflow-hidden relative bg-gradient-to-br from-[#f5f0eb] via-[#fdf8f8] to-[#e8e0d8]" />
                  </div>
                )}
                <div className={card.span ? "flex flex-col justify-center flex-1" : ""}>
                  <span
                    className="material-symbols-outlined text-[#53625c] mb-4"
                    style={{ fontSize: 24 }}
                  >
                    {card.icon}
                  </span>
                  <p className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase mb-1">
                    {card.label}
                  </p>
                  <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-4 font-normal">
                    I currently believe...
                  </h3>
                  {editing ? (
                    <textarea
                      value={card.raw}
                      onChange={(e) => updateField(card.key, e.target.value)}
                      className="w-full bg-[#ebe7e6] border border-[#c4c7c7] rounded p-3 font-['Inter'] text-[16px] leading-[1.5] text-[#1c1b1b] resize-none focus:ring-1 focus:ring-[#000000] focus:border-[#000000] outline-none"
                      rows={3}
                    />
                  ) : (
                    <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                      {card.belief}
                    </p>
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
                    <span>Looks right</span>
                    <span className="material-symbols-outlined text-sm group-hover:translate-x-1 transition-transform">
                      arrow_forward
                    </span>
                  </button>
                  <button
                    onClick={() => setEditing(true)}
                    className="px-8 py-4 bg-transparent border border-[#c4c7c7] text-[#444748] rounded-lg font-['Inter'] text-[16px] leading-[1.5] transition-all duration-300 hover:border-[#000000] hover:text-[#000000] active:scale-95"
                  >
                    Let&rsquo;s refine this
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
              Digital Consiglieri
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
function deriveStrategicFocus(description: string): string {
  if (!description) return "";
  // Frame as strategic positioning, not verbatim repeat
  const clean = description.replace(/^(we|our|i)\s+(are|build|create|develop|make|offer|provide|specialize in)\s+/i, "").trim();
  return `Your immediate priority is establishing ${clean} as a core market capability.`;
}

function deriveCriticalConstraint(obstacle: string): string {
  if (!obstacle) return "";
  // Frame obstacle as strategic dependency
  const clean = obstacle.replace(/^(we|our|i)\s+(face|struggle with|battle|deal with|are challenged by)\s+/i, "").trim();
  return `Your stated objective depends on solving ${clean} before operational scaling becomes viable.`;
}

function deriveTargetMarket(customer: string): string {
  if (!customer) return "";
  // Frame ideal customer as market focus
  const clean = customer.replace(/^(we|our)\s+(target|focus on|serve|cater to)\s+/i, "").trim();
  return `You're targeting ${clean} as your primary market segment.`;
}

function deriveCompetitiveEdge(diff: string): string {
  if (!diff) return "";
  // Frame differentiation as advantage
  const clean = diff.replace(/^(we|our)\s+(are better|differentiate|stand out|excel)\s+(by|because|through|on)\s+/i, "").trim();
  return `Your competitive positioning centers on ${clean}.`;
}

function ExecutiveBriefing({
  profile,
  finishing,
  finishError,
  onEnterMissionControl,
}: {
  profile: OnboardingProfile;
  finishing: boolean;
  finishError: string | null;
  onEnterMissionControl: () => void;
}) {
  const hasData = profile.companyDescription || profile.annualGoal || profile.biggestObstacle;
  
  const strategicFocus = deriveStrategicFocus(profile.companyDescription);
  const criticalConstraint = deriveCriticalConstraint(profile.biggestObstacle);
  const targetMarket = deriveTargetMarket(profile.idealCustomer);
  const competitiveEdge = deriveCompetitiveEdge(profile.differentiation);
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
              Digital Consiglieri
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
            {/* Strategic Focus */}
            {strategicFocus && (
              <div className="md:col-span-2 onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg">
                <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest mb-4 block">
                  Strategic Focus
                </span>
                <h4 className="font-['Libre_Caslon_Text'] text-[32px] leading-[1.3] text-[#1c1b1b] mb-6 font-normal">
                  {profile.annualGoal || "Strategic Objective"}
                </h4>
                <div className="space-y-6">
                  <div className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-[#000000] mt-1">
                      flag
                    </span>
                    <div>
                      <h5 className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium font-bold mb-1 text-[#1c1b1b]">
                        Objective
                      </h5>
                      <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                        {strategicFocus}
                      </p>
                    </div>
                  </div>
                  {criticalConstraint && (
                    <div className="flex items-start gap-4">
                      <span className="material-symbols-outlined text-[#000000] mt-1">
                        warning
                      </span>
                      <div>
                        <h5 className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium font-bold mb-1 text-[#1c1b1b]">
                          Critical Constraint
                        </h5>
                        <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
                          {criticalConstraint}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Target Market */}
            {targetMarket && (
              <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg border-t-2 border-[#d3e3dc]">
                <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest mb-2 block">
                  Market
                </span>
                <h4 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-4 font-normal">
                  Target Profile
                </h4>
                <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748] mb-6">
                  {targetMarket}
                </p>
                <div className="pt-4 border-t border-[#c4c7c7]/20">
                  <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#747878] italic font-medium">
                    Source: {source}
                  </span>
                </div>
              </div>
            )}

            {/* Competitive Edge */}
            {competitiveEdge && (
              <div className="onb-ambient-shadow bg-[#ffffff] p-8 rounded-lg border-t-2 border-[#000000]">
                <span className="font-['Geist'] text-[11px] leading-[1.2] tracking-[0.05em] font-semibold text-[#444748] uppercase tracking-widest mb-2 block">
                  Positioning
                </span>
                <h4 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-4 font-normal">
                  Competitive Edge
                </h4>
                <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748] mb-6">
                  {competitiveEdge}
                </p>
                <div className="pt-4 border-t border-[#c4c7c7]/20">
                  <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#747878] italic font-medium">
                    Confidence: Medium
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
