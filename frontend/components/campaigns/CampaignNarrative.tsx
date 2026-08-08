"use client";

import { buildResearchUrl } from "../../lib/discovery-mode";
import Icon from "../shared/Icon";

type Props = {
  campaignId: string;
  campaignName?: string;
  objective?: string;
  audience?: string;
  messagingAngle?: string;
  status: string;
  step?: string;
  leadCount: number;
  pendingDrafts: number;
  approvedDrafts: number;
  sentDrafts: number;
  launchTotal?: number;
  launchFailed?: number;
  launching?: boolean;
  hasStrategy: boolean;
  generating: boolean;
  onGenerateStrategy: () => void;
  onGenerateDrafts: () => void;
  onLaunch: () => void;
};

/**
 * Contextual Narrative AI. The phase decision reads the campaign's canonical
 * current_step (the same single source as the stepper, cards, and gates);
 * draft/lead counters appear only inside branch wording, never to choose
 * the phase.
 */
export default function CampaignNarrative({
  campaignId,
  campaignName,
  objective,
  audience,
  messagingAngle,
  status,
  step,
  leadCount,
  pendingDrafts,
  approvedDrafts,
  sentDrafts,
  launchTotal,
  launchFailed,
  launching,
  hasStrategy,
  generating,
  onGenerateStrategy,
  onGenerateDrafts,
  onLaunch,
}: Props) {
  const researchUrl = buildResearchUrl({
    campaignId,
    campaignName,
    objective,
    audience,
    messagingAngle,
  });
  let message: string;
  let primaryLabel: string | null = null;
  let primaryHref: string | null = null;
  let onPrimary: (() => void) | null = null;
  let primaryVariant: "primary" | "success" = "primary";

  if (status === "paused") {
    message = "This campaign is paused. Resume it when you're ready to continue.";
  } else if (launching) {
    message =
      launchTotal && launchTotal > 0
        ? `Sending ${sentDrafts} of ${launchTotal} — replies and failures will settle in Inbox.`
        : "Your campaign is sending.";
  } else if (status === "completed" && (launchFailed ?? 0) > 0) {
    message = `Most of your sends delivered, but ${launchFailed} failed. Review them in Inbox.`;
    primaryLabel = "Open Inbox";
    primaryHref = "/inbox";
  } else if (status === "completed") {
    message = "This campaign has finished running. Track replies and follow-ups in Inbox.";
    primaryLabel = "Track replies";
    primaryHref = "/inbox";
  } else if (generating) {
    message = "Drafting personalized outreach for your leads — this takes a minute.";
  } else if (step === "research") {
    message = hasStrategy
      ? "Your strategy is ready. Attach the prospects it targets before drafting outreach."
      : "Let's find the right prospects before we build your messaging.";
    primaryLabel = "Research prospects";
    primaryHref = researchUrl;
  } else if (step === "strategy") {
    message = "Great. I understand your audience now. I'll prepare a strategy tailored to these companies.";
    primaryLabel = "Generate Strategy";
    onPrimary = onGenerateStrategy;
  } else if (step === "review") {
    message =
      pendingDrafts > 0
        ? `Review the ${pendingDrafts} draft${pendingDrafts === 1 ? "" : "s"} before launching your campaign.`
        : "Review the drafts before launching your campaign.";
    primaryLabel = "Review drafts";
    primaryHref = `/draft?campaign=${encodeURIComponent(campaignId)}`;
  } else if (sentDrafts > 0) {
    message = "Your campaign is sending. Track replies as they come in.";
    primaryLabel = "Open inbox";
    primaryHref = "/inbox";
  } else if (step === "sending") {
    message =
      approvedDrafts > 0
        ? `Drafts are approved. Launch campaign (${approvedDrafts} draft${approvedDrafts === 1 ? "" : "s"} ready).`
        : "Drafts are approved. Launch campaign.";
    primaryLabel = "Launch campaign";
    onPrimary = onLaunch;
    primaryVariant = "success";
  } else {
    message = "Your messaging is ready. Next I'll prepare personalized outreach drafts.";
    primaryLabel = "Generate Drafts";
    onPrimary = onGenerateDrafts;
  }

  return (
    <section className="p-6 rounded-xl border border-outline-variant/10 bg-surface-lowest animate-conversation-fade">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center shrink-0">
          <Icon name="auto_awesome" className="text-xl" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-widest text-on-surface-variant/50 font-medium">
            Loqi's read
          </p>
          <p className="mt-1 text-base text-on-surface leading-relaxed">{message}</p>

          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            {primaryLabel ? (
              primaryHref ? (
                <a
                  href={primaryHref}
                  className={`inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all hover:brightness-110 ${
                    primaryVariant === "success"
                      ? "bg-success text-white"
                      : "bg-primary text-on-primary"
                  }`}
                >
                  {primaryLabel}
                  <span className="material-symbols-outlined text-sm">arrow_forward</span>
                </a>
              ) : onPrimary ? (
                <button
                  onClick={onPrimary}
                  className={`inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all hover:brightness-110 ${
                    primaryVariant === "success"
                      ? "bg-success text-white"
                      : "bg-primary text-on-primary"
                  }`}
                >
                  {primaryLabel}
                  <span className="material-symbols-outlined text-sm">arrow_forward</span>
                </button>
              ) : null
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
