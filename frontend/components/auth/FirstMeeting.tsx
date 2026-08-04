"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "../../hooks/useAuth";

export default function FirstMeeting() {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && user && "onboarding_complete" in user && user.onboarding_complete) {
      router.replace("/mission-control");
    }
  }, [isLoading, router, user]);

  const handleBegin = () => {
    router.push("/onboarding");
  };

  return (
    <div className="animate-fade-in space-y-16">
      {/* Introduction */}
      <section className="space-y-6">
        <h1 className="font-['Libre_Caslon_Text'] text-[40px] leading-[1.3] text-[#000000] tracking-tight">
          First Meeting
        </h1>
        <div className="space-y-4">
          <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#444748]">
            Welcome to Loqi. I'm your AI Chief of Staff for outbound strategy.
          </p>
          <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#444748]">
            To work effectively on your behalf, I need to understand your business, 
            your goals, and your constraints. This conversation will establish 
            our strategic foundation.
          </p>
          <p className="font-['Inter'] text-[18px] leading-[1.6] text-[#444748]">
            Approximately 5 minutes. Your responses persist as your organizational memory.
          </p>
        </div>
      </section>

      {/* What we'll cover */}
      <section className="space-y-6">
        <h2 className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest text-[#444748]">
          What we'll establish
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-[#ffffff] p-6 rounded-lg border border-[#c4c7c7]/20">
            <span className="material-symbols-outlined text-[#53625c] mb-4 text-[24px]">
              explore
            </span>
            <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-2">
              Market Position
            </h3>
            <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
              What you do and who you serve
            </p>
          </div>
          <div className="bg-[#ffffff] p-6 rounded-lg border border-[#c4c7c7]/20">
            <span className="material-symbols-outlined text-[#53625c] mb-4 text-[24px]">
              flag
            </span>
            <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-2">
              Strategic Objectives
            </h3>
            <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
              Your 12-month priorities and goals
            </p>
          </div>
          <div className="bg-[#ffffff] p-6 rounded-lg border border-[#c4c7c7]/20">
            <span className="material-symbols-outlined text-[#53625c] mb-4 text-[24px]">
              warning
            </span>
            <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-2">
              Critical Constraints
            </h3>
            <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
              Obstacles and limitations to address
            </p>
          </div>
          <div className="bg-[#ffffff] p-6 rounded-lg border border-[#c4c7c7]/20">
            <span className="material-symbols-outlined text-[#53625c] mb-4 text-[24px]">
              trending_up
            </span>
            <h3 className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] text-[#1c1b1b] mb-2">
              Competitive Edge
            </h3>
            <p className="font-['Inter'] text-[16px] leading-[1.5] text-[#444748]">
              What sets you apart
            </p>
          </div>
        </div>
      </section>

      {/* Begin button */}
      <div className="flex flex-col md:flex-row gap-4 justify-center items-center pt-8 border-t border-[#c4c7c7]/20">
        <button
          onClick={handleBegin}
          className="group relative px-8 py-4 bg-[#000000] text-[#ffffff] rounded-lg font-['Inter'] text-[16px] leading-[1.5] transition-all duration-300 hover:bg-[#444748] active:scale-95 flex items-center gap-2"
        >
          <span>Begin First Meeting</span>
          <span className="material-symbols-outlined text-sm group-hover:translate-x-1 transition-transform">
            arrow_forward
          </span>
        </button>
      </div>

      {/* Trust note */}
      <p className="text-center font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] text-[#747878] italic">
        Your data establishes your organizational memory and remains private to your workspace.
      </p>
    </div>
  );
}
