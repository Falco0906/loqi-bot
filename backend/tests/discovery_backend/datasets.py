"""Deterministic startup datasets for isolated Discovery tests; no I/O."""
PROFILES = {"small", "large"}


def validate_profile(profile):
    if profile not in PROFILES:
        raise ValueError("Unknown isolated Discovery profile; choose small or large")
    return profile


def lead_id(index):
    return f"70000000-0000-4000-8000-{index:012d}"


def lead_row(index, workspace, title, industry="ecommerce", location="London"):
    return {
        "id": lead_id(index), "workspace_id": workspace,
        "first_name": "Synthetic", "last_name": f"Person {index}", "title": title,
        "email": f"person{index}@example.invalid", "deleted_at": None, "source": "csv_import",
        "metadata": {"csv_import": {"company": "Synthetic Shop", "industry": industry, "location": location}},
    }


def build_workspace_leads(profile, workspace_a, workspace_b, foreign_workspace):
    """Return fresh rows; never mutate/reseed an existing store."""
    validate_profile(profile)
    titles = ("Head of Operations", "Operations Manager", "COO")
    if profile == "large":
        rows = [lead_row(index, workspace_a, titles[(index - 1) // 200]) for index in range(1, 601)]
        rows += [lead_row(601, workspace_a, "COO", location="Toronto"),
                 lead_row(602, workspace_a, "COO", industry="", location=""),
                 lead_row(603, workspace_a, "Software Engineer"),
                 lead_row(604, workspace_a, "COO", industry="Retail"),
                 lead_row(605, workspace_b, "Head of Operations"),
                 lead_row(606, workspace_b, "COO"), lead_row(607, foreign_workspace, "COO")]
    else:
        rows = [lead_row(index, workspace_a, titles[(index - 1) % 3]) for index in range(1, 55)]
        rows += [lead_row(55, workspace_a, "COO", location="Toronto"),
                 lead_row(56, workspace_a, "COO", industry="", location=""),
                 lead_row(57, workspace_a, "Engineer"), lead_row(58, workspace_a, "COO", industry="Retail"),
                 lead_row(59, workspace_b, "COO"), lead_row(60, foreign_workspace, "COO")]
    return rows
