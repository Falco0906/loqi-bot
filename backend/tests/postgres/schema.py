"""Metadata-only catalog snapshots and offline comparisons, never production reads.

Production metadata must be supplied by an operator in this versioned format.
Function/default definitions can contain literals: operators must review exports
for embedded secrets before supplying them. This tool never exports table rows.
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

from tests.postgres.harness import connect_local
from tests.postgres.catalog_contract import COLUMNS, FOREIGN_KEYS, UNIQUE_INDEXES, CHECKS

FUNCTION = "create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)"

TABLES = (
    "identity_users", "organizations", "workspaces", "workspace_members",
    "companies", "leads", "workspace_companies", "workspace_leads", "lead_sources",
    "lead_signals", "campaigns", "campaign_leads", "strategies", "drafts",
    "discoveries", "discovery_companies", "discovery_leads", "memberships", "invitations",
)
# Include only execution roles, contract owners and their grant ancestors. Role
# passwords are never queried; inherited privileges must not disappear from the
# comparison merely because an intermediate role has a different name.
ROLE_SCOPE = """WITH RECURSIVE seeds(oid) AS (
    SELECT oid FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role','loqi_test_owner')
    UNION SELECT relowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND c.relname=ANY(%s)
    UNION SELECT nspowner FROM pg_namespace WHERE nspname='public'
    UNION SELECT proowner FROM pg_proc WHERE oid=to_regprocedure(
      'public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)')
  ), relevant(oid) AS (
    SELECT oid FROM seeds UNION SELECT m.roleid FROM pg_auth_members m
      JOIN relevant r ON m.member=r.oid)
"""
# Every query returns stable identity plus schema metadata, not application rows.
QUERIES = {
    "tables": """SELECT c.relname, jsonb_build_object('owner', pg_get_userbyid(c.relowner),
        'kind',c.relkind,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND c.relkind IN ('r','p')""",
    "columns": """SELECT c.relname||'.'||a.attname,
        jsonb_build_object('type',format_type(a.atttypid,a.atttypmod),'nullable',NOT a.attnotnull,
        'default',pg_get_expr(d.adbin,d.adrelid),'position',a.attnum,
        'identity',a.attidentity,'generated',a.attgenerated,
        'collation',(SELECT collname FROM pg_collation WHERE oid=a.attcollation))
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped""",
    "constraints": """SELECT c.relname||'.'||k.conname,
        jsonb_build_object('kind',k.contype,'definition',pg_get_constraintdef(k.oid,true),
        'validated',k.convalidated,'deferrable',k.condeferrable,'deferred',k.condeferred,
        'columns',ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY x(num,ord)
          JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=x.num ORDER BY x.ord),
        'referenced_table',(SELECT relname FROM pg_class WHERE oid=k.confrelid))
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s)""",
    "indexes": """SELECT c.relname||'.'||i.relname,
        jsonb_build_object('definition',pg_get_indexdef(x.indexrelid),'unique',x.indisunique,
        'primary',x.indisprimary,'valid',x.indisvalid,'predicate',pg_get_expr(x.indpred,x.indrelid),
        'columns',ARRAY(SELECT a.attname FROM unnest(x.indkey) WITH ORDINALITY y(num,ord)
          LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=y.num ORDER BY y.ord))
        FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s)""",
    "triggers": """SELECT c.relname||'.'||t.tgname,
        jsonb_build_object('definition',pg_get_triggerdef(t.oid,true),'enabled',t.tgenabled,
        'function',t.tgfoid::regprocedure::text)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND NOT t.tgisinternal""",
    "functions": """SELECT p.oid::regprocedure::text,
        jsonb_build_object('definition',pg_get_functiondef(p.oid),'owner',pg_get_userbyid(p.proowner),
        'security_definer',p.prosecdef,'configuration',p.proconfig,'acl',p.proacl::text)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.oid=to_regprocedure(
          'public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)')""",
    "roles": ROLE_SCOPE + """SELECT rolname, jsonb_build_object('superuser',rolsuper,'create_db',rolcreatedb,
        'create_role',rolcreaterole,'bypass_rls',rolbypassrls,'login',rolcanlogin,'inherit',rolinherit,
        'replication',rolreplication,'connection_limit',rolconnlimit)
        FROM pg_roles WHERE oid IN (SELECT oid FROM relevant)""",
    "grants": """SELECT c.relname, jsonb_build_object('acl',c.relacl::text)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND c.relkind IN ('r','p')""",
    "policies": """SELECT tablename||'.'||policyname,
        jsonb_build_object('permissive',permissive,'roles',roles,'command',cmd,'using',qual,'check',with_check)
        FROM pg_policies WHERE schemaname='public' AND tablename=ANY(%s)""",
    "role_memberships": ROLE_SCOPE + """SELECT parent.rolname||'.'||child.rolname||'.'||grantor.rolname,
        jsonb_build_object('admin_option',m.admin_option,'inherit_option',m.inherit_option,'set_option',m.set_option)
        FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles child ON child.oid=m.member
        JOIN pg_roles grantor ON grantor.oid=m.grantor
        WHERE m.member IN (SELECT oid FROM relevant)""",
    "schema_grants": """SELECT nspname, jsonb_build_object('owner',pg_get_userbyid(nspowner),'acl',nspacl::text)
        FROM pg_namespace WHERE nspname='public'""",
    "extensions": """SELECT extname, jsonb_build_object('version',extversion,'schema',n.nspname)
        FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace""",
    "column_grants": """SELECT c.relname||'.'||a.attname, jsonb_build_object('acl',a.attacl::text)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped""",
    "default_grants": """SELECT pg_get_userbyid(d.defaclrole)||'.'||COALESCE(n.nspname,'*')||'.'||d.defaclobjtype,
        jsonb_build_object('acl',d.defaclacl::text) FROM pg_default_acl d
        LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        WHERE (n.nspname='public' OR d.defaclnamespace=0)
        AND d.defaclrole IN (SELECT oid FROM pg_roles WHERE rolname IN
          ('loqi_test_owner','anon','authenticated','service_role')
          UNION SELECT relowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s)
          UNION SELECT nspowner FROM pg_namespace WHERE nspname='public'
          UNION SELECT proowner FROM pg_proc WHERE oid=to_regprocedure(
            'public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)'))""",
}
TABLE_QUERY_SECTIONS = {"tables", "columns", "constraints", "indexes", "triggers", "grants", "policies", "column_grants", "default_grants", "roles", "role_memberships"}
FIELDS = {
    "tables": {"owner", "kind", "rls", "force_rls"},
    "columns": {"type", "nullable", "default", "position", "identity", "generated", "collation"},
    "constraints": {"kind", "definition", "validated", "deferrable", "deferred", "columns", "referenced_table"},
    "indexes": {"definition", "unique", "primary", "valid", "predicate", "columns"},
    "triggers": {"definition", "enabled", "function"},
    "functions": {"definition", "owner", "security_definer", "configuration", "acl"},
    "roles": {"superuser", "create_db", "create_role", "bypass_rls", "login", "inherit", "replication", "connection_limit"},
    "grants": {"acl"}, "policies": {"permissive", "roles", "command", "using", "check"},
    "role_memberships": {"admin_option", "inherit_option", "set_option"},
    "schema_grants": {"owner", "acl"}, "extensions": {"version", "schema"},
    "migration_history": {"version", "checksum"},
    "column_grants": {"acl"}, "default_grants": {"acl"},
}
# Null ACLs/defaults/configurations have real PostgreSQL meaning. Only these
# non-null catalog properties are required to be known; null is not a blanket
# synonym for absent privileges or missing metadata.
KNOWN_FIELDS = {
    "tables": FIELDS["tables"],
    "columns": {"type", "nullable", "position", "identity", "generated"},
    "constraints": {"kind", "definition", "validated", "deferrable", "deferred", "columns"},
    "indexes": {"definition", "unique", "primary", "valid", "columns"},
    "triggers": FIELDS["triggers"],
    "functions": {"definition", "owner", "security_definer"},
    "roles": FIELDS["roles"], "role_memberships": FIELDS["role_memberships"],
    "schema_grants": {"owner"}, "extensions": FIELDS["extensions"],
    "migration_history": FIELDS["migration_history"],
}


def validate_snapshot(snapshot):
    if (not isinstance(snapshot, dict) or set(snapshot) != {"format", "provenance", "scope", "sections"}
            or snapshot["format"] != 2 or snapshot["scope"] != list(TABLES)):
        raise ValueError("Unsupported schema-only snapshot format or scope")
    provenance = snapshot["provenance"]
    if (not isinstance(provenance, dict) or set(provenance) != {"kind", "schema_only"}
            or provenance["kind"] not in {"local_capture", "operator_supplied", "repository_expectation"}
            or provenance["schema_only"] is not True):
        raise ValueError("Schema-only provenance is required")
    sections = snapshot["sections"]
    if not isinstance(sections, dict) or set(sections) != set(FIELDS):
        raise ValueError("All schema sections must be present; use null for unknown metadata")
    for section, rows in sections.items():
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise ValueError("Schema sections must be lists or unknown")
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"id", "definition"}
                    or not isinstance(row["id"], str) or row["id"] in seen
                    or not isinstance(row["definition"], dict) or set(row["definition"]) != FIELDS[section]):
                raise ValueError("Invalid or duplicate schema metadata entry")
            seen.add(row["id"])
            if section == "functions" and row["id"] != FUNCTION:
                raise ValueError("Only the bounded campaign function may be supplied")
    return snapshot


def fingerprint_literals(sections):
    """Do not export raw SQL/default/configuration strings that may embed secrets.

    Hashes preserve exact change detection, NOT human review or semantic proof.
    An operator's source metadata still requires confidential manual review.
    """
    sensitive = {"columns": ("default",), "functions": ("definition", "configuration"),
        "constraints": ("definition",), "indexes": ("definition", "predicate"),
        "triggers": ("definition",), "policies": ("using", "check")}
    for section, fields in sensitive.items():
        for row in sections.get(section) or []:
            for field in fields:
                value = row["definition"][field]
                if value is not None:
                    encoded = json.dumps(value, sort_keys=True).encode()
                    row["definition"][field] = "sha256:" + hashlib.sha256(encoded).hexdigest()


def capture_local(target):
    sections = {}
    with connect_local(target) as connection, connection.cursor() as cursor:
        # connect_local ends its identity/role probes with rollback. This is the
        # first statement of a new transaction; all catalogs share one snapshot.
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for name, query in QUERIES.items():
            cursor.execute(query, (list(TABLES),) if name in TABLE_QUERY_SECTIONS else None)
            sections[name] = [{"id": identity, "definition": definition} for identity, definition in cursor.fetchall()]
    # There is no automatic migration ledger in this narrow bootstrap. Never
    # pretend the repository manifest proves which migrations production applied.
    sections["migration_history"] = None
    fingerprint_literals(sections)
    return validate_snapshot({"format": 2, "scope": list(TABLES), "sections": sections,
        "provenance": {"kind": "local_capture", "schema_only": True}})


def contract_completeness(snapshot, *, require_function=True):
    """Presence/type coverage, not the stricter local prerequisite verifier.

    Ownership, CHECK expressions, FK actions and permissions remain exact
    comparison surfaces; verify_campaign_prerequisites is their local validator.
    """
    sections = snapshot["sections"]
    missing = []
    def entries(section):
        return {r["id"]: r["definition"] for r in sections[section] or []}
    tables, columns = entries("tables"), entries("columns")
    for table, required in COLUMNS.items():
        if table not in tables:
            missing.append("table:" + table)
        elif tables[table]["kind"] != "r":
            missing.append("ordinary_table:" + table)
        for column, (kind, not_null) in required.items():
            value = columns.get(table + "." + column)
            if value is None or value["type"] != kind or value["nullable"] is not (not not_null):
                missing.append("column:" + table + "." + column)
        constraints = [v for k, v in entries("constraints").items() if k.startswith(table + ".")]
        if not any(v["kind"] == "p" and v["columns"] == ["id"] for v in constraints):
            missing.append("primary_key:" + table)
        for column, referenced, _, _ in FOREIGN_KEYS.get(table, []):
            if not any(v["kind"] == "f" and v["columns"] == [column] and v["referenced_table"] == referenced for v in constraints):
                missing.append("foreign_key:" + table + "." + column)
        for column in CHECKS.get(table, {}):
            if not any(v["kind"] == "c" and column in v["columns"] for v in constraints):
                missing.append("check:" + table + "." + column)
        indexes = [v for k, v in entries("indexes").items() if k.startswith(table + ".")]
        for key in UNIQUE_INDEXES.get(table, []):
            if not any(v["unique"] is True and v["valid"] is True and v["columns"] == list(key) for v in indexes):
                missing.append("unique_index:" + table + "." + ",".join(key))
        if table not in entries("grants"):
            missing.append("table_acl:" + table)
        for column in required:
            if table + "." + column not in entries("column_grants"):
                missing.append("column_acl:" + table + "." + column)
    for role in ("anon", "authenticated", "service_role"):
        if role not in entries("roles"):
            missing.append("role:" + role)
    for table in tables.values():
        if table["owner"] is not None and table["owner"] not in entries("roles"):
            missing.append("owner_role:" + table["owner"])
    if "public" not in entries("schema_grants"):
        missing.append("schema_acl:public")
    owners = [v["owner"] for v in entries("schema_grants").values()] + [v["owner"] for v in entries("functions").values()]
    for owner in owners:
        if owner is not None and owner not in entries("roles"):
            missing.append("owner_role:" + owner)
    if require_function and FUNCTION not in entries("functions"):
        missing.append("function:" + FUNCTION)
    unknown = [name for name, rows in sections.items() if rows is None]
    unknown_fields = [section + ":" + row["id"] + "." + field
        for section, fields in KNOWN_FIELDS.items() for row in sections[section] or []
        for field in sorted(fields) if row["definition"][field] is None]
    return {"complete": not missing and not unknown and not unknown_fields,
        "required_objects_present": not missing, "missing": missing,
        "unknown": unknown, "unknown_fields": unknown_fields,
        "local_prerequisite_validation": "not_established_by_snapshot"}


def compare_snapshots(left, right, *, require_function=True):
    """Exact metadata comparison; do not hide owner/grant/definition differences."""
    validate_snapshot(left)
    validate_snapshot(right)
    differences, unknown = [], []
    for section in FIELDS:
        a, b = left["sections"][section], right["sections"][section]
        if a is None or b is None:
            unknown.append(section)
            continue
        a = {row["id"]: row["definition"] for row in a}
        b = {row["id"]: row["definition"] for row in b}
        for identity in sorted(a.keys() | b.keys()):
            if a.get(identity) != b.get(identity):
                differences.append({"section": section, "id": identity,
                    "kind": "changed" if identity in a and identity in b else "missing_left" if identity not in a else "missing_right"})
    completeness = [contract_completeness(s, require_function=require_function) for s in (left, right)]
    return {"status": "different" if differences else "incomplete" if unknown or not all(c["complete"] for c in completeness) else "metadata_equal",
        "metadata_equal": not differences and not unknown and not any(c["unknown_fields"] for c in completeness),
        "contract_completeness": completeness,
        "differences": differences, "unknown_sections": unknown,
        "production_equivalence_verified": False,
        "note": "Operator provenance is not independently authenticated; exact metadata equality is not runtime equivalence."}


def compare_bootstrap_artifacts(left, right):
    """Compare observations from two independent approved bootstrap executions.

    Source hashes alone are never a substitute for the captured catalog data.
    This cannot authenticate operator-supplied artifacts or establish production
    equivalence. Unknown migration history stays unknown.
    """
    fields = {"database", "run_id", "manifest_sha256", "snapshot"}
    if set(left) != fields or set(right) != fields:
        raise ValueError("Bootstrap artifacts require database/run/manifest identities and snapshots")
    from uuid import UUID
    for artifact in (left, right):
        run = str(UUID(artifact["run_id"]))
        if artifact["database"] != "loqi_test_" + run.replace("-", ""):
            raise ValueError("Artifact is not a disposable database identity")
        validate_snapshot(artifact["snapshot"])
        if artifact["snapshot"]["provenance"]["kind"] != "local_capture":
            raise ValueError("Bootstrap comparison needs observed local captures")
    if left["run_id"] == right["run_id"] or left["manifest_sha256"] != right["manifest_sha256"]:
        raise ValueError("Two independent runs of the same reviewed manifest are required")
    return compare_snapshots(left["snapshot"], right["snapshot"], require_function=False)


def main():
    parser = argparse.ArgumentParser(description="Offline schema-metadata comparison; never connects")
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--bootstrap-artifacts", action="store_true")
    args = parser.parse_args()
    compare = compare_bootstrap_artifacts if args.bootstrap_artifacts else compare_snapshots
    report = compare(json.loads(args.left.read_text()), json.loads(args.right.read_text()))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "metadata_equal" else 1


if __name__ == "__main__":
    raise SystemExit(main())
