from services.providers.provider_factory import get_provider, get_provider_capabilities


def _log(message: str) -> None:
    print(f"[lead_provider] {message}")


def _filter_and_rank_leads(leads: list, icp: dict, context: dict | None = None) -> tuple[list, dict]:
    """
    Filter excluded leads and rank remaining by commercial qualification.
    Uses commercial_qualifier for multi-dimensional scoring.
    Returns (filtered_and_ranked_leads, filtering_stats)
    """
    from services.commercial_qualifier import qualify_and_rank_leads

    qualified_leads, qual_stats = qualify_and_rank_leads(leads, icp, context=context)

    filter_stats = {
        "total_found": qual_stats["total"],
        "excluded_count": qual_stats["excluded_vendor"] + qual_stats["excluded_junk"],
        "excluded_reasons": qual_stats["rejected_reasons"],
        "scored_count": qual_stats["qualified"],
        "average_score": qual_stats["avg_score"],
        "drift_detected": qual_stats["drift_detected"],
    }

    _log(f"Commercial qualification: {filter_stats['excluded_count']} excluded (vendor={qual_stats['excluded_vendor']}, junk={qual_stats['excluded_junk']}), {filter_stats['scored_count']} qualified, {filter_stats['drift_detected']} drift flags, avg_score={filter_stats['average_score']:.1f}")

    return qualified_leads, filter_stats


def _filter_and_rank_leads_soft(leads: list, icp: dict, context: dict | None = None) -> tuple[list, dict]:
    """
    Softer filtering — only hard-exclude obvious junk and vendors, keep everything else.
    Used as fallback when strict filtering removes all leads.
    """
    from services.commercial_qualifier import qualify_and_rank_leads

    soft_icp = dict(icp or {})
    if soft_icp.get("excluded_roles"):
        soft_icp["excluded_roles"] = [
            r for r in soft_icp["excluded_roles"]
            if r in ["developer", "designer", "freelancer"]
        ]

    qualified_leads, qual_stats = qualify_and_rank_leads(leads, soft_icp, context=context)

    filter_stats = {
        "total_found": qual_stats["total"],
        "excluded_count": qual_stats["excluded_vendor"] + qual_stats["excluded_junk"],
        "excluded_reasons": qual_stats["rejected_reasons"],
        "scored_count": qual_stats["qualified"],
        "average_score": qual_stats["avg_score"],
        "drift_detected": qual_stats["drift_detected"],
        "soft_filter": True,
    }

    _log(f"Soft qualification: {filter_stats['scored_count']} leads kept out of {filter_stats['total_found']}")

    return qualified_leads, filter_stats


def get_leads(service: str, target: str) -> dict:
    """Search for leads using the configured provider (no ICP expansion)."""
    provider = get_provider()
    health = provider.health_check()
    if not health.get("ok"):
        return {
            "ok": False,
            "source": type(provider).__name__,
            "leads": [],
            "error": health.get("error", "Provider health check failed"),
        }

    combined_input = f"{service} {target}".strip() if target else service

    from services.icp_extractor import extract_structured_icp
    icp = extract_structured_icp(combined_input)

    result = provider.search_leads(icp=icp, search_expansion={}, limit=10)

    return {
        "ok": result.get("ok", False),
        "source": result.get("provider", type(provider).__name__),
        "leads": result.get("leads", []),
        "error": result.get("error"),
    }


def _build_fallback_queries(service: str, target: str, icp: dict) -> list[str]:
    """Build progressively wider fallback queries when primary search fails."""
    queries = []

    if icp and icp.get("buyer_roles"):
        for role in icp.get("buyer_roles", [])[:3]:
            queries.append(role)

    if target:
        queries.append(target)

    words = (target or service or "").split()
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))

    return queries[:5]


def search_with_expansion(service: str, target: str, plan=None, context: dict | None = None) -> dict:
    """AI-enhanced lead search with buyer-intent expansion and filtering.

    ``plan`` is the structured Discovery Plan (``discoveries.metadata.plan``).
    When present, the provider consumes ONLY structured plan terms — the raw
    objective is never used in provider inputs. Without a plan the legacy
    free-text pipeline runs unchanged.
    """
    import time; _t0 = time.time()
    provider = get_provider()

    _log(f"Using {type(provider).__name__}")
    _log(f"BUYER-INTENT search: service='{service}', target='{target}'"
         + (" (structured plan)" if plan else ""))

    icp = None
    if plan:
        from services.discovery_plan import icp_from_plan
        icp = icp_from_plan(plan)
        _log(f"ICP from plan: industries={icp['buyer_industries']}, "
             f"roles={icp['buyer_roles'][:3]}...")
    else:
        combined_input = f"{service} {target}".strip() if target else service

        try:
            from services.icp_extractor import extract_structured_icp
            icp = extract_structured_icp(combined_input)
            print(f"[TRACE] 6a | ICP EXTRACTION DONE | extract_structured_icp | +{int((time.time()-_t0)*1000)}ms | mode={icp.get('mode')}")

            _log(f"ICP extracted: mode={icp.get('mode')}, offer='{icp.get('offer')}")
            _log(f"buyer_industries: {icp.get('buyer_industries', [])}")
            _log(f"buyer_roles: {icp.get('buyer_roles', [])[:3]}...")
            _log(f"excluded_roles: {icp.get('excluded_roles', [])}")
        except Exception as e:
            _log(f"ICP extraction failed: {e}, using fallback")
            print(f"[TRACE] 6a | ICP EXTRACTION FAILED | extract_structured_icp | +{int((time.time()-_t0)*1000)}ms | error={e}")
            icp = None

    icp = _apply_discovery_context(icp, context)

    try:
        from services.search_expansion import expand_search_intent
        expansion = expand_search_intent(service, target, icp)
        print(f"[TRACE] 6b | SEARCH EXPANSION DONE | expand_search_intent | +{int((time.time()-_t0)*1000)}ms | {len(expansion.get('search_queries', []))} queries")

        _log(f"Expansion result: {len(expansion.get('search_queries', []))} queries")
        _log(f"buyer_roles: {expansion.get('roles', [])[:3]}...")
        _log(f"buyer_industries: {expansion.get('industries', [])}")
    except Exception as e:
        _log(f"Expansion failed: {e}, falling back to deterministic")
        print(f"[TRACE] 6b | SEARCH EXPANSION FAILED | expand_search_intent | +{int((time.time()-_t0)*1000)}ms | error={e}")
        expansion = None

    try:
        result = provider.search_leads(icp=icp, search_expansion=expansion, limit=30)

        if not result.get("ok"):
            return {
                "ok": False,
                "source": result.get("provider", type(provider).__name__),
                "leads": [],
                "error": result.get("error", "Provider search failed"),
                "icp": icp,
                "context_provenance": (context or {}).get("provenance", {}),
            }

        all_leads = result.get("leads", [])

        if not all_leads:
            return {
                "ok": False,
                "source": result.get("provider", type(provider).__name__),
                "leads": [],
                "error": "No leads found. Try a broader target.",
                "icp": icp,
                "context_provenance": (context or {}).get("provenance", {}),
            }

        filtered_leads = all_leads
        filter_stats = {
            "total_found": len(all_leads),
            "excluded_count": 0,
            "scored_count": len(all_leads),
            "average_score": 0,
        }

        if icp and (icp.get("buyer_roles") or icp.get("excluded_roles")):
            _log("Applying buyer-intent filtering and ranking...")
            filtered_leads, filter_stats = _filter_and_rank_leads(all_leads, icp, context=context)

        if not filtered_leads and len(all_leads) >= 3:
            _log("Qualification filtered ALL leads — retrying with relaxed filtering...")
            filtered_leads, filter_stats = _filter_and_rank_leads_soft(all_leads, icp, context=context)

        if not filtered_leads and all_leads:
            _log("No qualified leads after filtering — returning raw leads as fallback")
            filtered_leads = all_leads[:5]
            filter_stats = {
                "total_found": len(all_leads),
                "excluded_count": len(all_leads) - len(filtered_leads),
                "scored_count": len(filtered_leads),
                "average_score": 0,
                "fallback_mode": True,
            }

        _log(f"Final result: {len(filtered_leads)} leads after filtering (from {filter_stats['total_found']} found)")

        return {
            "ok": True,
            "source": result.get("provider", type(provider).__name__),
            "leads": filtered_leads,
            "error": None,
            "expansion": expansion,
            "icp": icp,
            "filter_stats": filter_stats,
            "context_provenance": (context or {}).get("provenance", {}),
        }

    except Exception as error:
        _log(f"error: {error}")
        return {
            "ok": False,
            "source": type(provider).__name__,
            "leads": [],
            "error": str(error),
            "icp": icp,
            "context_provenance": (context or {}).get("provenance", {}),
        }


def _apply_discovery_context(icp: dict | None, context: dict | None) -> dict | None:
    """Supplement ICP fields without changing the provider contract."""
    if not isinstance(icp, dict) and not context:
        return icp
    merged = dict(icp or {})
    knowledge_icp = (context or {}).get("knowledge_icp") or {}
    for key, limit in (
        ("buyer_industries", 4),
        ("buyer_roles", 10),
        ("company_types", 4),
        ("pain_points", 6),
        ("excluded_roles", 10),
        ("keywords", 10),
    ):
        values = list(merged.get(key) or []) + list(knowledge_icp.get(key) or [])
        seen: set[str] = set()
        merged_values = []
        for value in values:
            normalized = str(value).strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                merged_values.append(value)
        merged[key] = merged_values[:limit]
    merged["context_provenance"] = (context or {}).get("provenance", {})
    # Strategic observations remain attribution-only context, never ICP rules.
    merged["strategic_observation_ids"] = [
        item.get("id") for item in (context or {}).get("strategic_observations") or [] if item.get("id")
    ]
    return merged


def _format_lead(index: int, lead: dict) -> str:
    full_name = " ".join(
        part for part in [lead.get("first_name", ""), lead.get("last_name", "")] if part
    ) or (lead.get("name") or "Unknown")
    title = (lead.get("title", "") or "").strip()
    company = (lead.get("company") or "Unknown Company").strip()
    role_part = f" — {title}" if title else ""
    return f"{index}. {full_name}{role_part} @ {company}"


def format_leads_message(leads: list[dict]) -> str:
    formatted_leads = [_format_lead(i, lead) for i, lead in enumerate(leads, 1)]
    count = len(leads)
    return (
        f"I found **{count} promising match{'es' if count != 1 else ''}** ranked by buying potential.\n\n"
        + "\n".join(formatted_leads)
        + "\n\nReply with a number to pick one and I'll draft a personalized message."
    )
