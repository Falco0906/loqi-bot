from uuid import uuid4

from services.workflow_models import (
    WorkflowPlan, WorkflowStep, AlternativePlanPair,
    ActionType, RiskLevel, StepStatus, PlanStatus,
    APPROVAL_ACTIONS, ACTION_DURATIONS,
)
from services.workflow_reasoner import WorkflowReasoner


OBJECTIVE_PATTERNS: list[tuple[str, list[str], str]] = [
    ("find_leads", ["find", "search", "discover", "look for", "find me", "get me", "source", "hunt"], "User wants to discover leads"),
    ("create_campaign", ["create campaign", "start campaign", "build campaign", "new campaign", "make campaign", "launch campaign for"], "User wants to create a campaign"),
    ("finish_campaign", ["finish", "complete", "finalize", "wrap up", "get this done", "close campaign"], "User wants to finalize an existing campaign"),
    ("review_drafts", ["review", "check draft", "look at draft", "approve", "read draft", "feedback"], "User wants to review drafts"),
    ("generate_drafts", ["generate draft", "write draft", "create draft", "make draft", "draft for", "personalize"], "User wants to generate drafts"),
    ("find_similar", ["similar", "like ", "same as", "competitor", "companies like", "similar to"], "User wants to find companies similar to a known reference"),
    ("analyze", ["analyze", "check campaign", "how is", "performance", "stats", "report"], "User wants to analyze campaign performance"),
    ("rewrite", ["rewrite", "improve", "edit draft", "make better", "fix draft", "polish"], "User wants to rewrite or improve a draft"),
    ("launch", ["launch", "send", "start sending", "go live", "deploy"], "User wants to launch a campaign"),
    ("what_next", ["what next", "what should i do", "suggest", "recommend", "what now", "help", "what can i do"], "User wants suggestions"),
]


def _classify_objective(objective: str) -> tuple[str, str, float]:
    ol = objective.lower()
    best_match = "what_next"
    best_reason = "General assistance requested"
    best_score = 0.0

    for match_type, keywords, reason in OBJECTIVE_PATTERNS:
        for kw in keywords:
            if kw in ol:
                score = len(kw) / max(len(ol), 1)
                if score > best_score:
                    best_score = score
                    best_match = match_type
                    best_reason = reason

    return best_match, best_reason, best_score


def _make_step(
    action_type: ActionType,
    title: str,
    description: str = "",
    approval: bool = False,
) -> WorkflowStep:
    return WorkflowStep(
        title=title,
        description=description or title,
        action_type=action_type,
        estimated_duration=ACTION_DURATIONS.get(action_type, "~30s"),
        approval_required=approval or action_type in APPROVAL_ACTIONS,
    )


def _extract_target(objective: str) -> str:
    """Extract what the user is searching for or targeting."""
    ol = objective.lower()
    for prefix in ["find companies like ", "find similar companies to ",
                   "find ", "search for ", "find me ", "get me ", "look for ",
                   "companies like ", "similar to ", "create campaign for ",
                   "start campaign for ", "build campaign for "]:
        if ol.startswith(prefix):
            return objective[len(prefix):].strip()
    for prefix in ["find companies like ", "find similar companies to ", "companies like "]:
        if prefix in ol:
            idx = ol.index(prefix) + len(prefix)
            return objective[idx:].strip()
    for prefix in ["search for ", "search "]:
        if ol.startswith(prefix):
            return objective[len(prefix):].strip()
    return objective


def _plan_find_leads(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    target = _extract_target(objective)

    if reasoner.has_running_jobs():
        steps = [
            _make_step(ActionType.WAIT_FOR_USER, f"Wait for running job to complete",
                       f"A search is already in progress. Let it finish first."),
            _make_step(ActionType.REVIEW_DRAFTS if reasoner.has_pending_drafts() else ActionType.WAIT_FOR_USER,
                       "Review results",
                       "Check the search results once ready."),
        ]
        primary = WorkflowPlan(
            goal=f"Wait for existing search before finding {target}",
            reasoning="A search job is already running. Starting another would create duplicate work.",
            risk_level=RiskLevel.LOW,
            steps=steps,
            estimated_duration="1-2min",
        )
        alt = WorkflowPlan(
            goal=f"Start a new search for {target} anyway",
            reasoning="If the running job is unrelated, a new parallel search may be fine.",
            risk_level=RiskLevel.MEDIUM,
            steps=[
                _make_step(ActionType.SEARCH_LEADS, f"Search for {target}", f"Find leads matching '{target}'"),
                _make_step(ActionType.WAIT_FOR_USER, "Review results and proceed"),
            ],
            estimated_duration="1-2min",
        )
        return primary, alt

    if reasoner.has_campaigns():
        existing = reasoner.get_campaign_by_name(target)
        if existing:
            primary = WorkflowPlan(
                goal=f"Continue existing campaign for {target}",
                reasoning=f"A campaign for '{target}' already exists. Continuing is faster than starting over.",
                risk_level=RiskLevel.LOW,
                steps=_existing_campaign_steps(existing, reasoner),
                estimated_duration="varies",
            )
            alt = WorkflowPlan(
                goal=f"Refresh leads for {target}",
                reasoning="Finding new leads can uncover fresh opportunities the existing campaign missed.",
                risk_level=RiskLevel.LOW,
                steps=[
                    _make_step(ActionType.SEARCH_LEADS, f"Search for {target}"),
                    _make_step(ActionType.CREATE_CAMPAIGN, f"Create campaign for {target}", approval=True),
                ],
                estimated_duration="2-3min",
            )
            return primary, alt

    primary = WorkflowPlan(
        goal=f"Find and campaign for {target}",
        reasoning="No existing campaign for this target. A search-first approach builds from real results.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.SEARCH_LEADS, f"Search for {target}", f"Discover leads matching '{target}'"),
            _make_step(ActionType.FILTER_LEADS, "Filter relevant leads", "Narrow results to the best-fit companies"),
            _make_step(ActionType.CREATE_CAMPAIGN, f"Create campaign for {target}", approval=True),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts",
                       "Auto-generate personalized outreach drafts"),
            _make_step(ActionType.WAIT_FOR_USER, "Review and approve drafts", approval=True),
            _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
        ],
        estimated_duration="5-10min",
    )
    alt = WorkflowPlan(
        goal=f"Direct campaign for {target} without search",
        reasoning="If you already know your target audience, skip search and go straight to campaign creation.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.CREATE_CAMPAIGN, f"Create campaign for {target}", approval=True),
            _make_step(ActionType.WAIT_FOR_USER, "Add leads manually"),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
            _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
        ],
        estimated_duration="3-5min",
    )
    return primary, alt


def _plan_create_campaign(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    target = _extract_target(objective)

    if reasoner.has_leads() and not reasoner.campaigns_in_planning():
        primary = WorkflowPlan(
            goal=f"Create campaign from existing leads{f' for {target}' if target else ''}",
            reasoning="You already have leads ready. Creating a campaign now puts them to use.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.CREATE_CAMPAIGN, f"Create campaign{f' for {target}' if target else ''}",
                           approval=True),
                _make_step(ActionType.GENERATE_DRAFTS, "Generate personalized drafts"),
                _make_step(ActionType.WAIT_FOR_USER, "Review and approve drafts", approval=True),
                _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
            ],
            estimated_duration="3-5min",
        )
        alt = WorkflowPlan(
            goal=f"Search for more leads first{f' about {target}' if target else ''}",
            reasoning="Expanding your lead pool before creating the campaign increases volume options.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.SEARCH_LEADS, f"Search for additional leads{f' for {target}' if target else ''}"),
                _make_step(ActionType.CREATE_CAMPAIGN, "Create campaign from combined leads", approval=True),
                _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
                _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
            ],
            estimated_duration="5-8min",
        )
        return primary, alt

    primary = WorkflowPlan(
        goal=f"Create campaign{f' for {target}' if target else ''}",
        reasoning="Starting from scratch: find leads, build campaign, generate content, and launch.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.SEARCH_LEADS, f"Search for leads{f' for {target}' if target else ''}",
                       f"Discover potential targets{f' matching {target}' if target else ''}"),
            _make_step(ActionType.FILTER_LEADS, "Filter to best-fit leads"),
            _make_step(ActionType.CREATE_CAMPAIGN, f"Create campaign", approval=True),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate personalized drafts"),
            _make_step(ActionType.WAIT_FOR_USER, "Review and approve", approval=True),
            _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
        ],
        estimated_duration="5-10min",
    )
    alt = WorkflowPlan(
        goal=f"Use existing data to build campaign faster",
        reasoning="If there's existing workspace data, we might be able to skip search.",
        risk_level=RiskLevel.MEDIUM,
        steps=[
            _make_step(ActionType.CREATE_CAMPAIGN, "Create campaign directly", approval=True),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts from available context"),
            _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch", approval=True),
        ],
        estimated_duration="2-4min",
    )
    return primary, alt


def _existing_campaign_steps(campaign: dict, reasoner: WorkflowReasoner) -> list[WorkflowStep]:
    status = campaign.get("status", "planning")
    steps = []

    if reasoner.needs_leads():
        steps.append(_make_step(ActionType.SEARCH_LEADS, "Find leads for this campaign",
                                f"{campaign.get('name')} has no leads yet."))
        steps.append(_make_step(ActionType.WAIT_FOR_USER, "Select leads", approval=True))

    if status in ("planning",) and (campaign.get("lead_count") or 0) > 0:
        steps.append(_make_step(ActionType.GENERATE_DRAFTS, "Generate drafts",
                                f"Create personalized drafts for {campaign.get('name')}"))
        steps.append(_make_step(ActionType.WAIT_FOR_USER, "Review drafts", approval=True))

    if status in ("draft_review",) or reasoner.has_pending_drafts():
        steps.append(_make_step(ActionType.REVIEW_DRAFTS, "Review pending drafts",
                                f"Check and approve {reasoner.drafts.get('pending', 0)} pending drafts"))

    if status in ("ready", "ready_to_send") or reasoner.has_approved_drafts():
        steps.append(_make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign",
                                f"{campaign.get('name')} is ready to send.", approval=True))

    if not steps:
        steps.append(_make_step(ActionType.ANALYZE_CAMPAIGN, f"Analyze {campaign.get('name')}",
                                "Check what this campaign needs next."))
        steps.append(_make_step(ActionType.WAIT_FOR_USER, "Decide next step", approval=True))

    return steps


def _plan_finish_campaign(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    ready = reasoner.campaigns_ready_to_launch()
    review = reasoner.campaigns_in_draft_review()
    planning = reasoner.campaigns_in_planning()
    idle = reasoner.idle_campaigns()

    if ready:
        primary = WorkflowPlan(
            goal=f"Launch {ready[0].get('name')}",
            reasoning="This campaign is fully ready. All drafts are approved. Launching now gets outreach in front of leads with no further delay.",
            risk_level=RiskLevel.MEDIUM,
            steps=[
                _make_step(ActionType.NAVIGATE, f"Open {ready[0].get('name')}",
                           f"Go to campaign to do final checks"),
                _make_step(ActionType.LAUNCH_CAMPAIGN, f"Launch {ready[0].get('name')}",
                           approval=True),
            ],
            estimated_duration="~1min",
        )
        alt = WorkflowPlan(
            goal="Review all ready campaigns before launching",
            reasoning="If multiple campaigns are ready, prioritizing the most impactful one first may be better.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.ANALYZE_CAMPAIGN, "Compare ready campaigns",
                           "Decide which to launch first based on lead quality"),
                _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch selected campaign", approval=True),
            ],
            estimated_duration="2-3min",
        )
        return primary, alt

    if review:
        primary = WorkflowPlan(
            goal=f"Complete draft review for {review[0].get('name')}",
            reasoning=f"{review[0].get('name')} has {review[0].get('pending_drafts', 0)} pending drafts that must be reviewed before launch.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.REVIEW_DRAFTS, f"Review {review[0].get('name')} drafts",
                           f"Approve or revise {review[0].get('pending_drafts', 0)} pending drafts"),
                _make_step(ActionType.LAUNCH_CAMPAIGN, f"Launch {review[0].get('name')}",
                           approval=True),
            ],
            estimated_duration="2-4min",
        )
        alt = WorkflowPlan(
            goal="Review all campaigns needing attention",
            reasoning="Multiple campaigns may need work. A holistic review prevents bottlenecks.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.NAVIGATE, "View all campaigns", "/campaigns"),
                _make_step(ActionType.ANALYZE_CAMPAIGN, "Assess each campaign's status"),
                _make_step(ActionType.WAIT_FOR_USER, "Prioritize and proceed"),
            ],
            estimated_duration="3-5min",
        )
        return primary, alt

    if planning:
        has_leads = (planning[0].get("lead_count") or 0) > 0
        if has_leads:
            primary = WorkflowPlan(
                goal=f"Generate drafts for {planning[0].get('name')}",
                reasoning=f"{planning[0].get('name')} has leads ready. Generating drafts is the next step toward launch.",
                risk_level=RiskLevel.LOW,
                steps=[
                    _make_step(ActionType.GENERATE_DRAFTS, f"Generate drafts for {planning[0].get('name')}"),
                    _make_step(ActionType.WAIT_FOR_USER, "Review and approve drafts", approval=True),
                    _make_step(ActionType.LAUNCH_CAMPAIGN, f"Launch {planning[0].get('name')}", approval=True),
                ],
                estimated_duration="3-6min",
            )
        else:
            primary = WorkflowPlan(
                goal=f"Find leads for {planning[0].get('name')}",
                reasoning=f"{planning[0].get('name')} needs leads before drafts can be generated.",
                risk_level=RiskLevel.LOW,
                steps=[
                    _make_step(ActionType.SEARCH_LEADS, f"Find leads for {planning[0].get('name')}"),
                    _make_step(ActionType.CREATE_CAMPAIGN, "Update campaign with leads"),
                    _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
                    _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch", approval=True),
                ],
                estimated_duration="5-8min",
            )
        alt = WorkflowPlan(
            goal="Focus on a different campaign that's closer to launch",
            reasoning="If another campaign is ahead in the pipeline, finishing that one first builds momentum.",
            risk_level=RiskLevel.MEDIUM,
            steps=[
                _make_step(ActionType.ANALYZE_CAMPAIGN, "Compare campaign readiness"),
                _make_step(ActionType.WAIT_FOR_USER, "Select campaign to prioritize"),
            ],
            estimated_duration="1-2min",
        )
        return primary, alt

    if idle:
        primary = WorkflowPlan(
            goal=f"Reactivate {idle[0].get('name')}",
            reasoning=f"{idle[0].get('name')} has been idle for over 3 days. Picking it back up prevents pipeline stagnation.",
            risk_level=RiskLevel.LOW,
            steps=_existing_campaign_steps(idle[0], reasoner),
            estimated_duration="varies",
        )
        alt = WorkflowPlan(
            goal="Start fresh with a new campaign",
            reasoning="If existing campaigns are stalled, a new focused campaign may be more productive.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.SEARCH_LEADS, "Find leads for a new campaign"),
                _make_step(ActionType.CREATE_CAMPAIGN, "Create new campaign", approval=True),
                _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
                _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch", approval=True),
            ],
            estimated_duration="5-10min",
        )
        return primary, alt

    return _plan_create_campaign(objective, reasoner)


def _plan_review_drafts(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    pending = reasoner.drafts.get("pending", 0)
    approved = reasoner.drafts.get("approved", 0)

    if pending > 0:
        primary = WorkflowPlan(
            goal=f"Review {pending} pending draft{'s' if pending > 1 else ''}",
            reasoning=f"There are {pending} draft{'s' if pending > 1 else ''} waiting for review. Reviewing them unlocks the next stage.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.NAVIGATE, "Open Draft Review",
                           "Go to the draft review interface"),
                _make_step(ActionType.REVIEW_DRAFTS, f"Review {pending} draft{'s' if pending > 1 else ''}",
                           f"Approve or request changes for each draft", approval=True),
                _make_step(ActionType.REWRITE_DRAFTS, "Apply revisions as needed"),
                _make_step(ActionType.WAIT_FOR_USER, "Confirm final versions", approval=True),
            ],
            estimated_duration="2-5min",
        )
        alt = WorkflowPlan(
            goal=f"Review in batches by campaign",
            reasoning="Prioritizing drafts by campaign context ensures consistency across each batch.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.ANALYZE_CAMPAIGN, "Compare campaigns with pending drafts"),
                _make_step(ActionType.REVIEW_DRAFTS, "Review highest-priority campaign first"),
            ],
            estimated_duration="2-4min",
        )
        return primary, alt

    if approved > 0:
        review_camps = reasoner.campaigns_in_draft_review()
        primary = WorkflowPlan(
            goal=f"Check why drafts are stuck",
            reasoning=f"{approved} draft{'s' if approved > 1 else ''} are approved. The next step is launch if all are approved.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.ANALYZE_CAMPAIGN, "Check campaign launch readiness"),
                _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
            ],
            estimated_duration="~1min",
        )
        alt = WorkflowPlan(
            goal="Generate more drafts to increase volume",
            reasoning="If you want more options before launching, generating additional drafts may help.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.GENERATE_DRAFTS, "Generate additional drafts"),
                _make_step(ActionType.REVIEW_DRAFTS, "Review new drafts"),
            ],
            estimated_duration="3-6min",
        )
        return primary, alt

    primary = WorkflowPlan(
        goal="Generate drafts to review",
        reasoning="No drafts exist yet. We need to generate drafts before we can review them.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.WAIT_FOR_USER, "Select a campaign to draft for"),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
            _make_step(ActionType.REVIEW_DRAFTS, "Review generated drafts", approval=True),
        ],
        estimated_duration="3-6min",
    )
    alt = WorkflowPlan(
        goal="Find leads first, then generate drafts",
        reasoning="If no campaign has leads, search for targets before drafting.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.SEARCH_LEADS, "Find leads"),
            _make_step(ActionType.CREATE_CAMPAIGN, "Build campaign", approval=True),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
            _make_step(ActionType.REVIEW_DRAFTS, "Review", approval=True),
        ],
        estimated_duration="5-10min",
    )
    return primary, alt


def _plan_find_similar(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    target = _extract_target(objective)

    primary = WorkflowPlan(
        goal=f"Find companies like {target}",
        reasoning=f"Analyzing {target} first helps define the search profile for finding similar companies.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.SEARCH_LEADS, f"Analyze {target} profile",
                       f"Understand {target}'s industry, size, and signals"),
            _make_step(ActionType.EXPAND_SEARCH, f"Find similar companies",
                       f"Search for companies matching {target}'s profile"),
            _make_step(ActionType.FILTER_LEADS, "Filter to best matches"),
            _make_step(ActionType.CREATE_CAMPAIGN, f"Build campaign for {target} lookalikes",
                       approval=True),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate personalized drafts"),
            _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch campaign", approval=True),
        ],
        estimated_duration="5-10min",
    )
    alt = WorkflowPlan(
        goal=f"Direct search for {target} without analysis",
        reasoning="If you already know the profile, skip analysis and search directly.",
        risk_level=RiskLevel.LOW,
        steps=[
            _make_step(ActionType.SEARCH_LEADS, f"Search for companies like {target}"),
            _make_step(ActionType.CREATE_CAMPAIGN, "Create campaign from results", approval=True),
            _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts"),
            _make_step(ActionType.LAUNCH_CAMPAIGN, "Launch", approval=True),
        ],
        estimated_duration="4-7min",
    )
    return primary, alt


def _plan_generate_drafts(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    planning = reasoner.campaigns_with_leads_no_drafts()
    if planning:
        primary = WorkflowPlan(
            goal=f"Generate drafts for {planning[0].get('name')}",
            reasoning=f"{planning[0].get('name')} has {planning[0].get('lead_count')} leads ready but no drafts yet.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.GENERATE_DRAFTS, f"Generate drafts for {planning[0].get('name')}"),
                _make_step(ActionType.WAIT_FOR_USER, "Review generated drafts",
                           approval=True),
            ],
            estimated_duration="2-5min",
        )
        alt = WorkflowPlan(
            goal="Generate drafts for all campaigns simultaneously",
            reasoning="If multiple campaigns need drafts, generating everything at once saves time.",
            risk_level=RiskLevel.MEDIUM,
            steps=[
                _make_step(ActionType.ANALYZE_CAMPAIGN, "Identify all campaigns needing drafts"),
                _make_step(ActionType.GENERATE_DRAFTS, "Generate drafts across campaigns"),
                _make_step(ActionType.WAIT_FOR_USER, "Review all drafts"),
            ],
            estimated_duration="5-10min",
        )
        return primary, alt

    return _plan_create_campaign(objective, reasoner)


def _plan_what_next(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    if reasoner.campaigns_ready_to_launch():
        return _plan_finish_campaign("finish campaign", reasoner)
    if reasoner.has_pending_drafts():
        return _plan_review_drafts("review drafts", reasoner)
    if reasoner.campaigns_with_leads_no_drafts():
        return _plan_generate_drafts("generate drafts", reasoner)
    if reasoner.needs_leads():
        return _plan_find_leads("find leads", reasoner)
    return _plan_create_campaign("create campaign", reasoner)


def _plan_find_finish_campaign(objective: str, reasoner: WorkflowReasoner) -> tuple[WorkflowPlan, WorkflowPlan]:
    """For analyze type: check if we should analyze existing or build new."""
    if reasoner.has_campaigns():
        top = reasoner.campaigns[0]
        return WorkflowPlan(
            goal=f"Analyze {top.get('name')}",
            reasoning=f"{top.get('name')} is your top campaign. Analyzing its status helps decide next steps.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.ANALYZE_CAMPAIGN, f"Analyze {top.get('name')}",
                           "Check performance metrics and bottlenecks"),
                _make_step(ActionType.WAIT_FOR_USER, "Review analysis and plan next steps"),
            ],
            estimated_duration="~1min",
        ), WorkflowPlan(
            goal="View overall campaign intelligence",
            reasoning="Campaign Intelligence gives a cross-campaign view of performance.",
            risk_level=RiskLevel.LOW,
            steps=[
                _make_step(ActionType.NAVIGATE, "Go to Campaign Intelligence",
                           "/campaign-intelligence"),
                _make_step(ActionType.WAIT_FOR_USER, "Explore insights"),
            ],
            estimated_duration="~1min",
        )
    return _plan_find_leads(objective, reasoner)


_PLANNERS: dict[str, callable] = {
    "find_leads": _plan_find_leads,
    "create_campaign": _plan_create_campaign,
    "finish_campaign": _plan_finish_campaign,
    "review_drafts": _plan_review_drafts,
    "generate_drafts": _plan_generate_drafts,
    "find_similar": _plan_find_similar,
    "analyze": _plan_find_finish_campaign,
    "rewrite": _plan_review_drafts,
    "launch": _plan_finish_campaign,
    "what_next": _plan_what_next,
}


def plan_workflow(
    objective: str,
    snapshot: dict,
    current_page: str = "unknown",
) -> AlternativePlanPair:
    reasoner = WorkflowReasoner(snapshot)
    match_type, match_reason, confidence = _classify_objective(objective)

    planner = _PLANNERS.get(match_type, _plan_what_next)
    if callable(planner):
        primary, alt = planner(objective, reasoner)
    else:
        primary, alt = _plan_what_next(reasoner)

    primary.status = PlanStatus.DRAFT
    alt.status = PlanStatus.DRAFT

    recommendation = (
        f"I recommend Option A: {primary.goal}. "
        f"{primary.reasoning}"
    )

    if primary.risk_level == RiskLevel.HIGH or primary.requires_approval:
        recommendation += " This plan requires your approval before proceeding."
    else:
        recommendation += f" Option B ({alt.goal}) is also viable if you prefer a different approach."

    return AlternativePlanPair(
        primary_plan=primary,
        alternative_plan=alt,
        recommendation=recommendation,
        confidence=min(int(confidence * 100) + 70, 95),
    )
