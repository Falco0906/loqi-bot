"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import AppPage from "../primitives/AppPage";
import WorkspaceContainer from "../layout/WorkspaceContainer";
import { useData } from "../../lib/hooks/use-data";
import { fetchMissionControl } from "../../lib/repositories";
import { useAuth } from "../../hooks/useAuth";
import { getStrategicProfile } from "../../lib/strategic-intelligence-api";
import type { MCTask } from "../../lib/domain";
import type { StrategicProfile } from "../../lib/strategic-intelligence-api";

function TasksCard({ tasks }: { tasks: MCTask[] }) {
  const [localTasks, setLocalTasks] = useState(tasks);

  const toggleTask = (id: string) => {
    setLocalTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, completed: !t.completed } : t))
    );
  };

  return (
    <div className="space-y-4">
      {localTasks.map((task) => (
        <div
          key={task.id}
          onClick={() => toggleTask(task.id)}
          className="flex items-center gap-4 group cursor-pointer"
        >
          <div
            className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${
              task.completed
                ? "bg-primary border-primary text-on-primary"
                : "border-outline group-hover:border-primary"
            }`}
          >
            <span
              className={`material-symbols-outlined text-[14px] transition-opacity ${
                task.completed ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              }`}
            >
              check
            </span>
          </div>
          <span
            className={`text-lg transition-colors ${
              task.completed ? "line-through text-on-surface-variant/40" : "text-on-surface"
            }`}
          >
            {task.title}
          </span>
        </div>
      ))}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="reading-column py-16 flex flex-col gap-16">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="space-y-4 animate-skeleton-pulse" style={{ animationDelay: `${i * 0.1}s` }}>
          <div className="h-6 w-1/4 bg-surface-high/50 rounded-lg" />
          <div className="h-4 w-full bg-surface-high/50 rounded-lg" />
          <div className="h-4 w-3/4 bg-surface-high/50 rounded-lg" />
          <div className="h-20 w-full bg-surface-high/30 rounded-xl" />
        </div>
      ))}
    </div>
  );
}

export default function MissionControlDashboard() {
  const { data, loading, error, retry } = useData(fetchMissionControl);
  const { user } = useAuth();
  const [storedProfile, setStoredProfile] = useState<StrategicProfile | null | undefined>(undefined);

  const profileLoaded = storedProfile !== undefined;

  useEffect(() => {
    if (!user || !("id" in user)) {
      setStoredProfile(null);
      return;
    }
    getStrategicProfile(user.id)
      .then((res) => setStoredProfile(res.profile))
      .catch(() => setStoredProfile(null));
  }, [user]);

  if (loading || !profileLoaded) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <LoadingSkeleton />
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (error) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 text-center">
            <p className="text-lg text-error mb-4">{error}</p>
            <button
              onClick={retry}
              className="bg-primary text-on-primary px-6 py-2 rounded-full text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Retry
            </button>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  if (!data) {
    return (
      <WorkspaceContainer>
        <AppPage>
          <div className="reading-column py-16 flex flex-col items-center justify-center text-center min-h-[60vh]">
            <div className="w-16 h-16 rounded-2xl bg-surface-high/30 flex items-center justify-center text-on-surface-variant/40 mb-4">
              <span className="material-symbols-outlined text-3xl">dashboard</span>
            </div>
            <p className="text-lg text-on-surface-variant/80 font-medium">No mission data yet</p>
            <p className="mt-1.5 text-sm text-on-surface-variant/50 max-w-sm leading-relaxed">
              Start a discovery session or launch a campaign to see your briefing here.
            </p>
          </div>
        </AppPage>
      </WorkspaceContainer>
    );
  }

  const briefingGreeting = storedProfile ? "Welcome back." : data.brief.greeting;

  const briefingLines = storedProfile
    ? [
        storedProfile.COMPANY_SUMMARY
          ? `Market position: ${storedProfile.COMPANY_SUMMARY}`
          : null,
        storedProfile.PRIMARY_OBJECTIVE
          ? `Strategic objective: ${storedProfile.PRIMARY_OBJECTIVE}`
          : null,
        storedProfile.CURRENT_CONSTRAINTS
          ? `Current constraint: ${storedProfile.CURRENT_CONSTRAINTS}`
          : null,
        storedProfile.ICP
          ? `Ideal customer: ${storedProfile.ICP}`
          : null,
      ].filter(Boolean) as string[]
    : data.brief.lines;

  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="reading-column py-16 flex flex-col gap-16">

          {/* Section 1: Briefing Message */}
          <section className="space-y-6 animate-fade-in">
            <h1 className="text-4xl md:text-5xl font-serif text-on-surface leading-tight tracking-tight font-normal">
              {briefingGreeting}
            </h1>
            {briefingLines.map((line, i) => (
              <p key={i} className="text-xl text-on-surface-variant/60 leading-relaxed font-light">
                {line}
              </p>
            ))}
          </section>

          {/* Section 2: Today's Focus */}
          {data.tasks.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Today's Focus
              </h3>
              <TasksCard tasks={data.tasks} />
              <div className="flex items-center gap-4 py-2 border-t border-outline-variant/10 mt-6">
                <span className="material-symbols-outlined text-[18px] text-secondary">verified</span>
                <span className="text-sm text-on-surface-variant italic opacity-60">Everything else is on track</span>
              </div>
            </section>
          )}

          {/* Section 3: Where I Need You */}
          {data.recommendations.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Where I Need You
              </h3>
              <div className="space-y-6">
                {data.recommendations.map((rec, i) => (
                  <div
                    key={i}
                    className="bg-surface-lowest ambient-shadow rounded-xl p-8 transition-transform hover:-translate-y-1 duration-300 border border-outline-variant/10"
                  >
                    <div className="flex justify-between items-start mb-6">
                      <div>
                        <h4 className="text-2xl font-serif text-on-surface mb-2 font-normal">{rec.observation}</h4>
                      </div>
                      <Link
                        href={rec.link}
                        className="bg-primary text-on-primary text-sm px-6 py-2 rounded-full hover:opacity-90 transition-opacity font-medium"
                      >
                        {rec.action}
                      </Link>
                    </div>
                    <p className="text-base text-on-surface-variant leading-relaxed">{rec.reason}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Section 4: What I Took Care Of */}
          {data.liveActivity.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                What I Took Care Of
              </h3>
              <div className="space-y-0">
                {data.liveActivity.map((item, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between py-6 border-b border-outline-variant/15 group"
                  >
                    <div className="flex items-center gap-6">
                      <span className="material-symbols-outlined text-primary/30 group-hover:text-primary transition-colors">
                        {item.type === "research" ? "travel_explore" : "check_circle"}
                      </span>
                      <span className="text-xl font-serif text-on-surface font-normal">{item.text}</span>
                    </div>
                    <span className="material-symbols-outlined text-on-surface-variant/30">chevron_right</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Section 5: Working Right Now */}
          {data.activeJobLabel && data.activeJobProgress !== null && data.activeJobTotal !== null && (
            <section className="space-y-6">
              <div className="bg-surface-container p-8 rounded-xl border border-outline-variant/10">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                  <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                    Working Right Now
                  </h3>
                </div>
                <p className="text-2xl font-serif text-on-surface mb-6 font-normal">{data.activeJobLabel}</p>
                <div className="flex items-end justify-between mb-2">
                  <span className="text-sm text-on-surface font-medium">
                    {data.activeJobProgress} / {data.activeJobTotal} completed
                  </span>
                  <span className="text-xs text-on-surface-variant">In progress</span>
                </div>
                <div className="w-full h-1 bg-surface-container-high rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-1000 ease-in-out"
                    style={{ width: `${(data.activeJobProgress / data.activeJobTotal) * 100}%` }}
                  />
                </div>
              </div>
            </section>
          )}

          {/* Section 6: Intelligence */}
          {data.insights.length > 0 && (
            <section className="space-y-6">
              <h3 className="text-xs uppercase tracking-widest text-on-surface-variant opacity-60 font-medium">
                Intelligence
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {data.insights.map((insight, i) => (
                  <div
                    key={i}
                    className="bg-surface-lowest p-6 rounded-lg border border-outline-variant/10 ambient-shadow"
                  >
                    <span className="material-symbols-outlined text-primary mb-4">{insight.icon}</span>
                    <p className="text-base text-on-surface leading-relaxed italic">&ldquo;{insight.text}&rdquo;</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Section 7: Tell Loqi */}
          <section className="pt-6 border-t border-outline-variant/20">
            <div className="bg-surface-lowest border border-outline-variant/20 rounded-xl p-4 ambient-shadow">
              <label className="text-xs uppercase tracking-widest text-on-surface-variant block mb-2 px-2 font-medium">
                Tell Loqi...
              </label>
              <div className="flex items-end gap-3 px-2 pb-1">
                <textarea
                  className="w-full border-none p-0 focus:ring-0 text-lg placeholder:text-on-surface-variant/30 resize-none bg-transparent outline-none"
                  placeholder="What would you like me to work on next?"
                  rows={1}
                />
                <button className="bg-primary text-on-primary w-10 h-10 rounded-full flex items-center justify-center hover:opacity-80 transition-opacity shrink-0">
                  <span className="material-symbols-outlined text-sm">arrow_upward</span>
                </button>
              </div>
            </div>
            <div className="mt-4 flex justify-center gap-3 overflow-x-auto no-scrollbar">
              <button className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold">
                REPRIORITIZE LIST
              </button>
              <button className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold">
                DRAFT WEEKLY SUMMARY
              </button>
              <button className="whitespace-nowrap text-on-surface-variant/60 hover:text-primary transition-colors border border-outline-variant/10 rounded-full px-4 py-1.5 bg-surface-container-low text-[10px] uppercase tracking-wider font-semibold">
                FIND NEW VENTURE LEADS
              </button>
            </div>
          </section>

        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
