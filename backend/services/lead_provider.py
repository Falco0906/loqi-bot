import os
import re


def _log(message: str) -> None:
    print(f"[lead_provider] {message}")


def _score_lead(lead: dict, icp: dict) -> tuple[int, list[str]]:
    """
    Score a lead based on buyer-ICP match.
    Returns (score, score_reasons)
    """
    score = 0
    reasons = []
    
    title = (lead.get("title") or "").lower()
    company = (lead.get("company") or "").lower()
    name = (lead.get("name") or "").lower()
    
    buyer_roles = [r.lower() for r in (icp.get("buyer_roles") or [])]
    buyer_industries = [i.lower() for i in (icp.get("buyer_industries") or [])]
    excluded_roles = [r.lower() for r in (icp.get("excluded_roles") or [])]
    
    for role in buyer_roles:
        if role in title:
            score += 30
            reasons.append(f"buyer_role_match:{role}")
            break
    
    for industry in buyer_industries:
        if industry in company:
            score += 20
            reasons.append(f"buyer_industry_match:{industry}")
            break
    
    if any(excluded in title for excluded in excluded_roles):
        score -= 50
        reasons.append("excluded_role_penalty")
    
    excluded_patterns = [
        r"\bdev(eloper)?\b",
        r"\bdesign(er)?\b",
        r"\bfreelance\b",
        r"\bfreelancer\b",
        r"\bconsult(ant|ing)?\b",
        r"\bagency\b",
        r"\bseo\b",
        r"\bmarketing\b.*specialist",
        r"\bwriter\b",
        r"\bcopywriter\b",
    ]
    for pattern in excluded_patterns:
        if re.search(pattern, title):
            score -= 40
            reasons.append("excluded_pattern_match")
            break
    
    if "owner" in title or "founder" in title or "co-founder" in title:
        score += 15
        reasons.append("decision_maker_title")
    
    if "manager" in title or "director" in title or "vp" in title or "head" in title:
        score += 10
        reasons.append("leadership_title")
    
    score = max(0, score)
    
    return score, reasons


def _filter_and_rank_leads(leads: list, icp: dict) -> tuple[list, dict]:
    """
    Filter excluded leads and rank remaining by buyer-ICP match.
    Returns (filtered_and_ranked_leads, filtering_stats)
    """
    scored_leads = []
    rejected = []
    filter_stats = {
        "total_found": len(leads),
        "excluded_count": 0,
        "excluded_reasons": {},
        "scored_count": 0,
        "average_score": 0,
    }
    
    for lead in leads:
        is_excluded, reason = _check_if_excluded(lead, icp)
        
        if is_excluded:
            rejected.append({
                "lead": lead,
                "reason": reason,
            })
            filter_stats["excluded_count"] += 1
            filter_stats["excluded_reasons"][reason] = filter_stats["excluded_reasons"].get(reason, 0) + 1
            continue
        
        score, score_reasons = _score_lead(lead, icp)
        scored_leads.append({
            "lead": lead,
            "score": score,
            "reasons": score_reasons,
        })
    
    scored_leads.sort(key=lambda x: x["score"], reverse=True)
    
    final_leads = [item["lead"] for item in scored_leads]
    
    filter_stats["scored_count"] = len(scored_leads)
    if scored_leads:
        total_score = sum(item["score"] for item in scored_leads)
        filter_stats["average_score"] = total_score / len(scored_leads)
    
    _log(f"Filtering: {filter_stats['excluded_count']} excluded, {filter_stats['scored_count']} kept")
    if rejected:
        _log(f"Rejected leads: {rejected[:3]}...")
    
    return final_leads, filter_stats


def _check_if_excluded(lead: dict, icp: dict) -> tuple[bool, str]:
    """Check if a lead should be excluded"""
    from services.icp_extractor import is_lead_excluded
    return is_lead_excluded(lead, icp)


def get_leads(service: str, target: str) -> dict:
    """Original deterministic lead search"""
    provider = os.getenv("LEAD_PROVIDER", "free").strip().lower()

    _log(f"using: {provider}")
    _log(f"input: {service}, {target}")

    try:
        if provider == "apollo":
            from services.apollo import search_leads
            return search_leads(target)

        if provider == "free":
            from services.free_leads import search_free_leads, SerpAPIError
            leads = search_free_leads(target)
            return {
                "ok": True,
                "source": "free",
                "leads": leads,
                "error": None,
            }

        raise Exception(f"Invalid LEAD_PROVIDER: {provider}")
    except Exception as error:
        _log(f"error: {error}")
        error_message = str(error)
        return {
            "ok": False,
            "source": provider,
            "leads": [],
            "error": error_message,
        }


def search_with_expansion(service: str, target: str) -> dict:
    """AI-enhanced lead search with buyer-intent expansion and filtering"""
    provider = os.getenv("LEAD_PROVIDER", "free").strip().lower()

    _log(f"BUYER-INTENT search: service='{service}', target='{target}'")

    combined_input = f"{service} {target}".strip() if target else service

    try:
        from services.icp_extractor import extract_structured_icp
        icp = extract_structured_icp(combined_input)

        _log(f"ICP extracted: mode={icp.get('mode')}, offer='{icp.get('offer')}")
        _log(f"buyer_industries: {icp.get('buyer_industries', [])}")
        _log(f"buyer_roles: {icp.get('buyer_roles', [])[:3]}...")
        _log(f"excluded_roles: {icp.get('excluded_roles', [])}")
    except Exception as e:
        _log(f"ICP extraction failed: {e}, using fallback")
        icp = None

    try:
        from services.search_expansion import expand_search_intent
        expansion = expand_search_intent(service, target, icp)

        _log(f"Expansion result: {len(expansion.get('search_queries', []))} queries")
        _log(f"buyer_roles: {expansion.get('roles', [])[:3]}...")
        _log(f"buyer_industries: {expansion.get('industries', [])}")
    except Exception as e:
        _log(f"Expansion failed: {e}, falling back to deterministic")
        expansion = None

    if provider != "free":
        _log(f"Provider {provider} doesn't support expansion, using deterministic")
        return get_leads(service, target)

    try:
        from services.free_leads import search_free_leads, SerpAPIError
        
        all_leads = []
        seen_urls = set()
        
        if expansion and expansion.get("search_queries"):
            search_queries = expansion["search_queries"]
            
            for query in search_queries:
                query_text = query.replace('site:linkedin.com/in "', '').replace('"', '')
                _log(f"Searching (buyer-focused): {query_text}")
                
                try:
                    leads = search_free_leads(query_text)
                    
                    for lead in leads:
                        if lead.get("linkedin_url") and lead["linkedin_url"] not in seen_urls:
                            seen_urls.add(lead["linkedin_url"])
                            all_leads.append(lead)
                            
                    _log(f"Found {len(leads)} leads for query, total unique: {len(all_leads)}")
                    
                except SerpAPIError as e:
                    _log(f"Query failed: {e}")
                    continue
                    
        else:
            _log("No expansion, using direct search")
            leads = search_free_leads(target or service)
            all_leads = leads

        if not all_leads:
            return {
                "ok": False,
                "source": "free",
                "leads": [],
                "error": "No leads found for expanded search",
                "icp": icp,
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
            filtered_leads, filter_stats = _filter_and_rank_leads(all_leads, icp)

        _log(f"Final result: {len(filtered_leads)} leads after filtering (from {filter_stats['total_found']} found)")

        return {
            "ok": True,
            "source": "free",
            "leads": filtered_leads,
            "error": None,
            "expansion": expansion,
            "icp": icp,
            "filter_stats": filter_stats,
        }

    except Exception as error:
        _log(f"error: {error}")
        error_message = str(error)
        return {
            "ok": False,
            "source": provider,
            "leads": [],
            "error": error_message,
            "icp": icp,
        }