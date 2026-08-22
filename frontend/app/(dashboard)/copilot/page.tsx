"use client";

/**
 * PR-4.5 — dedicated full Copilot page.
 *
 * The sidebar is the mini Copilot; THIS page is the full Copilot. Both render
 * the same CopilotPanel driven by the same CopilotContext engine — one
 * conversation, one action architecture, zero duplicated AI logic.
 */

import { useEffect } from "react";
import WorkspaceContainer from "../../../components/layout/WorkspaceContainer";
import AppPage from "../../../components/primitives/AppPage";
import CopilotPanel from "../../../components/copilot/CopilotPanel";
import { usePageTitle } from "../../../hooks/usePageTitle";

export default function CopilotPage() {
  usePageTitle("Copilot");

  // The panel normally renders as a fixed side column; on this page it fills
  // the workspace instead. The layout hides the duplicate sidebar instance
  // for /copilot (see DashboardLayout isCopilotPage).
  return (
    <WorkspaceContainer>
      <AppPage>
        <div className="mx-auto w-full max-w-3xl h-full flex flex-col" data-copilot-page>
          <div className="h-full min-h-0">
            <CopilotPanel variant="page" />
          </div>
        </div>
      </AppPage>
    </WorkspaceContainer>
  );
}
