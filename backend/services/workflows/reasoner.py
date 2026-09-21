from services.reasoning._shared import hours_since as _hours_since


def _find_matching_campaign(campaigns: list[dict], keywords: list[str]) -> dict | None:
    name_lower = ""
    for c in campaigns:
        name_lower = (c.get("name") or "").lower()
        for kw in keywords:
            if kw in name_lower:
                return c
    return None


class WorkflowReasoner:
    """Understands the current workspace state for planning purposes.

    Answers questions like:
    - Does a campaign for X already exist?
    - Are there leads ready for a campaign?
    - What is the current workflow stage?
    - What's the most logical next step?
    """

    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        self.campaigns = snapshot.get("campaigns", [])
        self.drafts = snapshot.get("drafts", {})
        self.jobs = snapshot.get("jobs", {})
        self.memory = snapshot.get("memory", {})
        self.timeline = snapshot.get("timeline", [])
        self.analysis = snapshot.get("analysis", {})
        self.total_leads = snapshot.get("total_leads", 0)

    def has_campaigns(self) -> bool:
        return len(self.campaigns) > 0

    def has_active_campaigns(self) -> bool:
        return sum(1 for c in self.campaigns if c.get("status") not in ("completed", "archived")) > 0

    def get_campaign_by_name(self, name: str) -> dict | None:
        nl = name.lower()
        for c in self.campaigns:
            if nl in (c.get("name") or "").lower():
                return c
        return None

    def has_pending_drafts(self) -> bool:
        return (self.drafts.get("pending") or 0) > 0

    def has_approved_drafts(self) -> bool:
        return (self.drafts.get("approved") or 0) > 0

    def has_running_jobs(self) -> bool:
        return len(self.jobs.get("running", [])) > 0

    def has_leads(self) -> bool:
        return self.total_leads > 0

    def campaigns_ready_to_launch(self) -> list[dict]:
        return [c for c in self.campaigns if c.get("current_step") == "sending"]

    def campaigns_in_draft_review(self) -> list[dict]:
        return [c for c in self.campaigns if c.get("current_step") == "review"]

    def campaigns_in_planning(self) -> list[dict]:
        return [c for c in self.campaigns if c.get("status") == "planning"]

    def campaigns_with_leads_no_drafts(self) -> list[dict]:
        return [c for c in self.campaigns
                if c.get("current_step") == "drafts"]

    def idle_campaigns(self) -> list[dict]:
        return [c for c in self.campaigns
                if c.get("status") not in ("completed", "archived", "deleted")
                and _hours_since(c.get("updated_at", "")) > 72]

    def last_action_type(self) -> str:
        action = (self.memory.get("last_action") or "")
        if "search" in action:
            return "search"
        if "launch" in action:
            return "launch"
        if "review" in action:
            return "review"
        if "open_campaign" in action:
            return "reviewing_campaign"
        return "idle"

    def needs_leads(self) -> bool:
        return not self.has_leads() and not self.has_running_jobs()

    def has_recently_completed_search(self) -> bool:
        recent = self.jobs.get("recently_completed", [])
        return any(j.get("type") == "search" for j in recent)
