import { OutreachContext, OutreachStrategyType } from "../../lib/types/outreach";
import PageSection from "../primitives/PageSection";

interface Props {
  outreach: OutreachContext;
  onStrategyChange: (type: OutreachStrategyType) => void;
}

export default function OutreachReviewPanel({ outreach, onStrategyChange }: Props) {
  return (
    <div className="space-y-6">
      <PageSection title="Outreach Strategy">
        <select 
          className="w-full p-2 bg-surface border border-outline-variant/20 rounded-lg text-sm text-on-surface"
          value={outreach.strategy.type}
          onChange={(e) => onStrategyChange(e.target.value as OutreachStrategyType)}
        >
          <option value="hiring">Hiring</option>
          <option value="growth">Growth</option>
          <option value="technology">Technology</option>
          <option value="product_launch">Product Launch</option>
        </select>
        <p className="text-body-sm text-outline">Angle: {outreach.strategy.angle}</p>
      </PageSection>

      <PageSection title="Draft">
        <div className="p-4 bg-surface-low rounded-lg border border-outline-variant/20 space-y-2 text-sm text-on-surface">
            <p className="font-bold">Subject: {outreach.draft.subject}</p>
            <p>{outreach.draft.opening}</p>
            <p>{outreach.draft.body}</p>
            <p className="font-semibold">{outreach.draft.cta}</p>
            <p>{outreach.draft.closing}</p>
        </div>
      </PageSection>

      <PageSection title="AI Reasoning">
        <p className="text-body-sm text-on-surface">{outreach.draft.reasoning}</p>
      </PageSection>
    </div>
  );
}
