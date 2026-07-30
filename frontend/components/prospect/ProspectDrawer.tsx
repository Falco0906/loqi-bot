"use client";

import { useState } from "react";
import { Prospect } from "../../lib/types/prospect";
import Drawer from "./Drawer";
import ProspectDetails from "./ProspectDetails";
import OutreachReviewPanel from "./OutreachReviewPanel";
import { generateOutreach } from "../../lib/discovery/outreachSimulator";
import { OutreachStrategyType } from "../../lib/types/outreach";

interface Props {
  isOpen: boolean;
  prospect: Prospect | null;
  onClose: () => void;
}

export default function ProspectDrawer({ isOpen, prospect, onClose }: Props) {
  const [strategyType, setStrategyType] = useState<OutreachStrategyType>("hiring");
  
  if (!prospect) return null;
  
  const outreachContext = generateOutreach(prospect, strategyType);

  return (
    <Drawer isOpen={isOpen} onClose={onClose}>
        <div className="flex flex-col h-full overflow-y-auto">
            <ProspectDetails prospect={prospect} onClose={onClose} />
            <OutreachReviewPanel 
                outreach={outreachContext} 
                onStrategyChange={(type) => setStrategyType(type)} 
            />
        </div>
    </Drawer>
  );
}
