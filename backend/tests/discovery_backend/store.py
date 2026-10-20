"""Small thread-safe table adapter for real Discovery repositories, not SQL/RLS.

Only the listed fixture tables and query operations exist. Unknown operations
fail rather than delegating to a real client. State lasts for this process only.
"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4
from tests.discovery_backend.datasets import build_workspace_leads, lead_row, validate_profile

USER = "10000000-0000-4000-8000-000000000001"
ORG = "10000000-0000-4000-8000-000000000002"
SESSION = "10000000-0000-4000-8000-000000000003"
A = "20000000-0000-4000-8000-000000000001"
B = "20000000-0000-4000-8000-000000000002"
FOREIGN = "20000000-0000-4000-8000-000000000003"
TABLES = {"users", "identity_users", "memberships", "workspaces", "workspace_leads",
          "workspace_companies", "companies", "jobs", "discoveries", "search_results",
          "discovery_leads", "discovery_companies", "web_session_bindings", "workflow_sessions"}


class SyntheticStore:
    def __init__(self, profile="small"):
        self.profile = validate_profile(profile)
        self.lock = RLock()
        self.run_id = str(uuid4())
        self.tables = {name: [] for name in TABLES}
        self.next_fault = ""
        self.tables["users"] = [{"id": USER, "username": "Synthetic Operator"}]
        self.tables["identity_users"] = [{"id": USER, "display_name": "Synthetic Operator"}]
        self.tables["memberships"] = [{"user_id": USER, "organization_id": ORG, "status": "active", "role": "owner"}]
        self.tables["workspaces"] = [{"id": workspace, "organization_id": org,
            "owner_user_id": USER, "name": name, "status": "active", "deleted_at": None}
            for workspace, org, name in [(A, ORG, "Alpha Synthetic"), (B, ORG, "Beta Synthetic"),
                                         (FOREIGN, "other-org", "Inaccessible Synthetic")]]
        self.tables["workspace_leads"] = build_workspace_leads(self.profile, A, B, FOREIGN)
        self.fixture_counts = {"workspace_a": sum(row["workspace_id"] == A for row in self.tables["workspace_leads"]),
                               "workspace_b": sum(row["workspace_id"] == B for row in self.tables["workspace_leads"]),
                               "foreign": sum(row["workspace_id"] == FOREIGN for row in self.tables["workspace_leads"]),
                               "total": len(self.tables["workspace_leads"])}

    def add_lead(self, index, workspace, title, industry="ecommerce", location="London"):
        self.tables["workspace_leads"].append(lead_row(index, workspace, title, industry, location))

    def table(self, name):
        if name not in TABLES:
            raise RuntimeError(f"Unapproved synthetic table: {name}")
        return Query(self, name)


class Query:
    def __init__(self, store, table):
        self.store, self.name = store, table
        self.filters, self.orders = [], []
        self.columns, self.operation, self.payload = "*", "select", None
        self.offset, self.cap, self.negated = 0, None, False

    def select(self, columns="*"): self.columns = columns; return self
    def eq(self, key, value): self.filters.append(lambda row: row.get(key) == value); return self
    def in_(self, key, values): self.filters.append(lambda row: row.get(key) in values); return self
    def is_(self, key, value):
        expected = None if value == "null" else value
        negate, self.negated = self.negated, False
        self.filters.append(lambda row: (row.get(key) == expected) != negate)
        return self
    @property
    def not_(self): self.negated = True; return self
    def order(self, key, desc=False): self.orders.append((key, desc)); return self
    def limit(self, count): self.cap = count; return self
    def range(self, start, end): self.offset, self.cap = start, end - start + 1; return self
    def insert(self, payload): self.operation, self.payload = "insert", deepcopy(payload); return self
    def update(self, payload): self.operation, self.payload = "update", deepcopy(payload); return self

    def execute(self):
        with self.store.lock:
            rows = self.store.tables[self.name]
            if self.operation == "insert":
                payload = self.payload if isinstance(self.payload, list) else [self.payload]
                if self.name == "search_results":
                    fault, self.store.next_fault = self.store.next_fault, ""
                    if fault == "fail-staging":
                        raise RuntimeError("Synthetic staging failure")
                    if fault == "truncate-staging":
                        payload = payload[:-1]
                inserted = []
                for value in payload:
                    now = datetime.now(timezone.utc).isoformat()
                    value = {"id": str(uuid4()), "created_at": now, "updated_at": now, "deleted_at": None, **value}
                    rows.append(value)
                    inserted.append(value)
                return SimpleNamespace(data=deepcopy(inserted))
            selected = [row for row in rows if all(check(row) for check in self.filters)]
            if self.operation == "update":
                for row in selected:
                    row.update(self.payload)
            for key, desc in reversed(self.orders):
                selected.sort(key=lambda row: row.get(key) or "", reverse=desc)
            selected = selected[self.offset:self.offset + self.cap if self.cap is not None else None]
            result = deepcopy(selected)
            if self.name == "discoveries":
                for row in result:
                    for relation in ("discovery_leads", "discovery_companies"):
                        if relation not in self.columns:
                            continue
                        links = deepcopy([link for link in self.store.tables[relation] if link["discovery_id"] == row["id"]])
                        if f"{relation}(count)" in self.columns:
                            row["lead_count" if relation == "discovery_leads" else "company_count"] = [{"count": len(links)}]
                        else:
                            for link in links:
                                if relation == "discovery_leads":
                                    link["workspace_lead"] = deepcopy(next((lead for lead in self.store.tables["workspace_leads"] if lead["id"] == link["lead_id"]), {}))
                            row[relation] = links
            return SimpleNamespace(data=result)
