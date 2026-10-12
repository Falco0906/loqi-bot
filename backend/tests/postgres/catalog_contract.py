"""Bounded catalog preflight for a fresh bootstrap and migration 048.

    Expected properties come from 006, 007, 008, 014, 016 and 025. This is
    contract metadata, not replacement DDL or a production schema snapshot.
"""
import re

from tests.postgres.harness import OWNER, UnsafeLocalPostgres

# Fresh PG16 namespace allowlist. No temp/user namespace is needed by bootstrap.
SYSTEM_SCHEMAS = ("pg_catalog", "pg_toast", "information_schema")
FRESH_QUERY = """SELECT 'schema', nspname FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog','pg_toast','information_schema','public')
    UNION ALL SELECT 'relation', n.nspname||'.'||c.relname FROM pg_class c
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'routine', n.nspname||'.'||p.proname FROM pg_proc p
      JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'type', n.nspname||'.'||t.typname FROM pg_type t
      JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'foreign_server', srvname FROM pg_foreign_server
    UNION ALL SELECT 'foreign_wrapper', fdwname FROM pg_foreign_data_wrapper
    UNION ALL SELECT 'event_trigger', evtname FROM pg_event_trigger
    UNION ALL SELECT 'extension', extname FROM pg_extension WHERE extname<>'plpgsql'
    UNION ALL SELECT 'language', lanname FROM pg_language
      WHERE lanname NOT IN ('internal','c','sql','plpgsql')
    UNION ALL SELECT 'publication', pubname FROM pg_publication
    UNION ALL SELECT 'subscription', subname FROM pg_subscription
      WHERE subdbid=(SELECT oid FROM pg_database WHERE datname=current_database())
    UNION ALL SELECT 'large_object', oid::text FROM pg_largeobject_metadata
    UNION ALL SELECT 'default_acl', oid::text FROM pg_default_acl
    UNION ALL SELECT 'database_role_setting', setrole::text FROM pg_db_role_setting
      WHERE setdatabase=0 OR setdatabase=(SELECT oid FROM pg_database WHERE datname=current_database())
    UNION ALL SELECT 'cast', oid::text FROM pg_cast WHERE oid>=16384
    UNION ALL SELECT 'access_method', amname FROM pg_am
      WHERE amname NOT IN ('heap','btree','hash','gist','gin','spgist','brin')
    UNION ALL SELECT 'tablespace', spcname FROM pg_tablespace
      WHERE spcname NOT IN ('pg_default','pg_global')
    UNION ALL SELECT 'operator', n.nspname||'.'||o.oprname FROM pg_operator o
      JOIN pg_namespace n ON n.oid=o.oprnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'collation', n.nspname||'.'||c.collname FROM pg_collation c
      JOIN pg_namespace n ON n.oid=c.collnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'conversion', n.nspname||'.'||c.conname FROM pg_conversion c
      JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'operator_class', n.nspname||'.'||o.opcname FROM pg_opclass o
      JOIN pg_namespace n ON n.oid=o.opcnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'operator_family', n.nspname||'.'||o.opfname FROM pg_opfamily o
      JOIN pg_namespace n ON n.oid=o.opfnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'text_search_config', n.nspname||'.'||t.cfgname FROM pg_ts_config t
      JOIN pg_namespace n ON n.oid=t.cfgnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'text_search_dictionary', n.nspname||'.'||t.dictname FROM pg_ts_dict t
      JOIN pg_namespace n ON n.oid=t.dictnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'text_search_parser', n.nspname||'.'||t.prsname FROM pg_ts_parser t
      JOIN pg_namespace n ON n.oid=t.prsnamespace WHERE n.nspname<>ALL(%s)
    UNION ALL SELECT 'text_search_template', n.nspname||'.'||t.tmplname FROM pg_ts_template t
      JOIN pg_namespace n ON n.oid=t.tmplnamespace WHERE n.nspname<>ALL(%s)"""


def verify_fresh_database(cursor):
    cursor.execute(FRESH_QUERY, (list(SYSTEM_SCHEMAS),) * 12)
    rows = cursor.fetchall()
    if rows:
        categories = ", ".join(sorted({row[0] for row in rows}))
        raise UnsafeLocalPostgres("Bootstrap requires a fresh disposable database; unexpected " + categories)


# type, NOT NULL. Columns used/read/inserted by 048 and identity relationships.
COLUMNS = {
    "identity_users": {"id": ("uuid", True)},
    "companies": {"id": ("uuid", True)},
    "leads": {"id": ("uuid", True)},
    "workspaces": {"id": ("uuid", True), "organization_id": ("text", True),
        "slug": ("text", True),
        "owner_user_id": ("uuid", False), "deleted_at": ("timestamp with time zone", False), "status": ("text", True)},
    "workspace_members": {"id": ("uuid", True), "workspace_id": ("uuid", True),
        "user_id": ("uuid", True), "role": ("text", True), "status": ("text", True),
        "deleted_at": ("timestamp with time zone", False)},
    "memberships": {"id": ("uuid", True), "organization_id": ("text", True),
        "user_id": ("text", True), "role": ("text", True), "status": ("text", True)},
    "workspace_leads": {"id": ("uuid", True), "workspace_id": ("uuid", True),
        "lead_id": ("uuid", True), "company_id": ("uuid", False), "deleted_at": ("timestamp with time zone", False)},
    "campaigns": {"id": ("uuid", True), "workspace_id": ("uuid", True),
        "organization_id": ("text", True), "discovery_id": ("uuid", False),
        "deleted_at": ("timestamp with time zone", False), "metadata": ("jsonb", True),
        "settings": ("jsonb", True), "version": ("integer", True),
        "created_at": ("timestamp with time zone", True), "updated_at": ("timestamp with time zone", True),
        **{name: ("text", True) for name in ("name", "objective", "status", "search_query", "created_by", "updated_by")}},
    "discoveries": {"id": ("uuid", True), "workspace_id": ("uuid", True),
        "deleted_at": ("timestamp with time zone", False), "status": ("text", True)},
    "campaign_leads": {"id": ("uuid", True), "campaign_id": ("uuid", True), "lead_id": ("uuid", True),
        "added_by": ("text", True), "status": ("text", True), "deleted_at": ("timestamp with time zone", False),
        "created_at": ("timestamp with time zone", True), "updated_at": ("timestamp with time zone", True)},
    "strategies": {"id": ("uuid", True), "campaign_id": ("uuid", True), "version": ("integer", True),
        "is_current": ("boolean", True), "generated_at": ("timestamp with time zone", True),
        "created_at": ("timestamp with time zone", True),
        **{name: ("jsonb", True) for name in ("sequence", "offer", "objections", "raw")},
        **{name: ("text", True) for name in ("objective", "audience", "channel", "messaging_angle", "tone",
            "persona", "generated_by", "model_used")}},
}
DEFAULTS = {
    "campaigns": {"settings": "'{}'::jsonb", "version": "1", "created_at": "now()", "updated_at": "now()"},
    "campaign_leads": {"id": "gen_random_uuid()", "status": "'added'::text", "created_at": "now()", "updated_at": "now()"},
    "strategies": {"id": "gen_random_uuid()", "version": "1", "is_current": "true", "generated_at": "now()", "created_at": "now()"},
}
# No membership FKs exist in 025: organization text membership is canonical.
FOREIGN_KEYS = {
    "workspaces": [("owner_user_id", "identity_users", "id", "n")],
    "workspace_members": [("workspace_id", "workspaces", "id", "c"), ("user_id", "identity_users", "id", "c")],
    "workspace_leads": [("workspace_id", "workspaces", "id", "c"), ("lead_id", "leads", "id", "c"),
        ("company_id", "companies", "id", "n")],
    "campaigns": [("workspace_id", "workspaces", "id", "c"), ("discovery_id", "discoveries", "id", "n")],
    "discoveries": [("workspace_id", "workspaces", "id", "c")],
    "campaign_leads": [("campaign_id", "campaigns", "id", "c"), ("lead_id", "workspace_leads", "id", "c")],
    "strategies": [("campaign_id", "campaigns", "id", "c")],
}
UNIQUE_INDEXES = {
    "workspaces": [("organization_id", "slug")], "workspace_members": [("workspace_id", "user_id")],
    "workspace_leads": [("workspace_id", "lead_id")], "campaign_leads": [("campaign_id", "lead_id")],
    "memberships": [("user_id", "organization_id")], "strategies": [("campaign_id", "version")],
}
PARTIAL_TABLES = {"workspaces", "workspace_members", "workspace_leads", "campaign_leads"}
CHECKS = {
    "workspaces": {"status": ("active", "suspended", "archived")},
    "workspace_members": {"role": ("owner", "admin", "member", "viewer"), "status": ("active", "invited", "suspended")},
    "memberships": {"role": ("owner", "admin", "member"), "status": ("pending", "active", "removed", "left")},
    "campaigns": {"status": ("planning", "active", "paused", "completed", "archived", "cancelled", "failed", "deleted")},
    "discoveries": {"status": ("queued", "searching", "completed", "failed", "cancelled")},
    "campaign_leads": {"status": ("added", "active", "removed", "paused")},
    "strategies": {"version": None},
}
PRIVILEGES = {
    "workspaces": ("SELECT", "UPDATE"), "memberships": ("SELECT", "UPDATE"),
    "workspace_leads": ("SELECT", "UPDATE"), "discoveries": ("SELECT", "UPDATE"),
    "campaigns": ("SELECT", "INSERT", "UPDATE"),
    "campaign_leads": ("SELECT", "INSERT"), "strategies": ("SELECT", "INSERT"),
}

QUERIES = {
    "relations": """SELECT c.relname, jsonb_build_object('kind',c.relkind,'owner',pg_get_userbyid(c.relowner),
        'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity) FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s)""",
    "columns": """SELECT c.relname||'.'||a.attname, jsonb_build_object('type',format_type(a.atttypid,a.atttypmod),
        'not_null',a.attnotnull,'default',pg_get_expr(d.adbin,d.adrelid),'identity',a.attidentity,'generated',a.attgenerated)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped""",
    "foreign_keys": """SELECT c.relname, jsonb_build_object(
        'columns',ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY x(num,ord)
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=x.num ORDER BY x.ord),
        'referenced_schema',rn.nspname,'referenced_table',rc.relname,
        'referenced_columns',ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY x(num,ord)
            JOIN pg_attribute a ON a.attrelid=rc.oid AND a.attnum=x.num ORDER BY x.ord),
        'delete',k.confdeltype,'update',k.confupdtype,'match',k.confmatchtype,
        'validated',k.convalidated,'deferrable',k.condeferrable)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_class rc ON rc.oid=k.confrelid JOIN pg_namespace rn ON rn.oid=rc.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND k.contype='f'""",
    "indexes": """SELECT c.relname, jsonb_build_object('columns',
        ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY x(num,ord)
          LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=x.num ORDER BY x.ord),
        'unique',i.indisunique,'primary',i.indisprimary,'valid',i.indisvalid,'ready',i.indisready,
        'immediate',i.indimmediate,'predicate',pg_get_expr(i.indpred,i.indrelid),'method',am.amname,
        'nulls_not_distinct',i.indnullsnotdistinct)
        FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_class ix ON ix.oid=i.indexrelid JOIN pg_am am ON am.oid=ix.relam
        WHERE n.nspname='public' AND c.relname=ANY(%s)""",
    "checks": """SELECT c.relname, jsonb_build_object('expression',pg_get_expr(k.conbin,k.conrelid),
        'validated',k.convalidated,'no_inherit',k.connoinherit) FROM pg_constraint k
        JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND k.contype='c'""",
    "privileges": """SELECT c.relname, jsonb_build_object(
        'SELECT',has_table_privilege('service_role',c.oid,'SELECT'),
        'INSERT',has_table_privilege('service_role',c.oid,'INSERT'),
        'UPDATE',has_table_privilege('service_role',c.oid,'UPDATE'))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s)""",
    "hooks": """SELECT c.relname, jsonb_build_object('trigger_count',
        (SELECT count(*) FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal),
        'rule_count',(SELECT count(*) FROM pg_rewrite r WHERE r.ev_class=c.oid))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s)""",
}


def _expression(value):
    # Only harmless rendering differences in the finite known expressions.
    parts = re.split(r"('(?:[^']|'')*')", value or "")
    return "".join(part if part.startswith("'") else re.sub(r"[\s()]|::text", "", part).lower() for part in parts)


def verify_contract_metadata(data):
    """Pure validation, with bounded diagnostics that never print SQL payloads."""
    def require(condition, label):
        if not condition:
            raise UnsafeLocalPostgres("Migration 048 prerequisite mismatch: " + label)
    for table, columns in COLUMNS.items():
        relation = data["relations"].get(table)
        require(relation == {"kind": "r", "owner": OWNER, "rls": False, "force_rls": False}, table + " relation/owner/RLS")
        require(data["hooks"].get(table) == {"trigger_count": 0, "rule_count": 0}, table + " unexpected trigger/rule")
        for name, (kind, not_null) in columns.items():
            actual = data["columns"].get(table + "." + name)
            require(actual is not None and actual["type"] == kind and actual["not_null"] is not_null
                and actual["identity"] == "" and actual["generated"] == "", table + "." + name + " type/nullability")
        for column, expected in DEFAULTS.get(table, {}).items():
            actual = data["columns"].get(table + "." + column)
            require(actual is not None and actual["default"] == expected, table + "." + column + " RPC insertion default")
        if table in {"campaigns", "campaign_leads", "strategies"}:
            supplied = {"campaigns": {"id", "workspace_id", "organization_id", "name", "objective", "status", "search_query",
                "discovery_id", "created_by", "updated_by", "metadata"},
                "campaign_leads": {"campaign_id", "lead_id", "added_by"},
                "strategies": {"campaign_id", "objective", "audience", "channel", "messaging_angle", "sequence", "tone",
                    "persona", "offer", "objections", "raw", "generated_by", "model_used"}}[table]
            for key, column in data["columns"].items():
                if key.startswith(table + ".") and key.split(".")[1] not in supplied:
                    require(not column["not_null"] or column["default"] is not None,
                        key + " omitted by RPC requires a default or nullable column")
        rows = data["indexes"].get(table, [])
        def usable(index):
            return all(index[key] is True for key in ("unique", "valid", "ready", "immediate")) and index["method"] == "btree" and index["nulls_not_distinct"] is False
        require(any(usable(i) and i["primary"] is True and i["columns"] == ["id"] and i["predicate"] is None for i in rows), table + " primary key(id)")
        for columns in UNIQUE_INDEXES.get(table, []):
            predicate = "deleted_atisnull" if table in PARTIAL_TABLES else ""
            require(any(usable(i) and i["columns"] == list(columns) and _expression(i["predicate"]) == predicate for i in rows), table + " canonical unique index " + ",".join(columns))
        for column, referenced, refcol, deletion in FOREIGN_KEYS.get(table, []):
            expected = {"columns": [column], "referenced_schema": "public", "referenced_table": referenced,
                "referenced_columns": [refcol], "delete": deletion, "update": "a", "match": "s", "validated": True, "deferrable": False}
            require(expected in data["foreign_keys"].get(table, []), table + "." + column + " foreign key")
        for column, values in CHECKS.get(table, {}).items():
            expression = "version>=1" if values is None else column + "=anyarray[" + ",".join("'" + value + "'" for value in values) + "]"
            require(any(check["validated"] is True and check["no_inherit"] is False
                and _expression(check["expression"]) == expression for check in data["checks"].get(table, [])), table + "." + column + " CHECK")
        for privilege in PRIVILEGES.get(table, []):
            require(data["privileges"].get(table, {}).get(privilege) is True, "service_role " + table + " " + privilege)


def verify_campaign_prerequisites(cursor):
    data = {name: {} for name in QUERIES}
    multiple = {"foreign_keys", "indexes", "checks"}
    for name, query in QUERIES.items():
        cursor.execute(query, (list(COLUMNS),))
        for identity, definition in cursor.fetchall():
            if name in multiple:
                data[name].setdefault(identity, []).append(definition)
            else:
                if identity in data[name]:
                    raise UnsafeLocalPostgres("Duplicate prerequisite catalog identity")
                data[name][identity] = definition
    cursor.execute("SELECT has_schema_privilege('service_role','public','USAGE'),"
        "has_schema_privilege(current_user,'public','CREATE')")
    if cursor.fetchone() != (True, True):
        raise UnsafeLocalPostgres("Migration 048 requires service schema USAGE and owner schema CREATE")
    verify_contract_metadata(data)
