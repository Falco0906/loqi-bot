/** A failed run does not erase canonical saved leads or prove zero matches. */
export function terminalDiscoveryMessage(run: { status: string; failure?: { kind: string } | null }): string {
  const saved = "Any results below are saved leads in this workspace; they do not mean the search completed.";
  if (run.status === "cancelled") return `This search was stopped. ${saved}`;
  switch (run.failure?.kind) {
    case "timeout": return `The search timed out. ${saved}`;
    case "permanent": return `This search could not run. Start a new search of your saved workspace leads. ${saved}`;
    case "persistence": return `The search could not finish saving its results. Results may be incomplete. ${saved}`;
    default: return `This search did not complete. ${saved}`;
  }
}
