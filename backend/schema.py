"""
Dynamic schema fetching for Supabase.

Discovery order (first success wins):
  1. Direct information_schema query via service role key
  2. get_schema_info() RPC  — create once via the SQL in setup_schema_rpc.sql
  3. OpenAPI root spec     — also needs service role, but tried anyway
  4. Row-sampling per table (only useful when tables have data)

No table names or column names are hardcoded here.
All discovery is driven by the credentials in .env.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

_schema_cache: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _credentials() -> tuple[str, str, str]:
    """Return (url, anon_key, service_key). service_key may be empty."""
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon  = os.getenv("SUPABASE_ANON_KEY", "")
    svc   = os.getenv("SUPABASE_SERVICE_KEY", "")   # optional — enables full schema
    return url, anon, svc


def _auth_headers(key: str) -> dict:
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Accept":        "application/json",
    }


def _rows_to_schema_string(rows: list) -> str:
    """Convert information_schema rows → readable schema string."""
    tables: dict[str, list] = {}
    for row in rows:
        tname = row.get("table_name", "")
        if not tname:
            continue
        tables.setdefault(tname, []).append(row)

    if not tables:
        return ""

    parts = []
    for tname, cols in tables.items():
        col_defs = []
        for col in cols:
            cdef = f"  {col.get('column_name', '?')} {col.get('data_type', 'unknown')}"
            if col.get("is_nullable") == "NO":
                cdef += " NOT NULL"
            col_defs.append(cdef)
        parts.append(f"Table: {tname}\n" + "\n".join(col_defs))

    return "\n\n".join(parts)


def _schema_from_information_schema(url: str, key: str) -> str:
    """
    Query information_schema.columns directly via PostgREST.
    Requires the service role key (anon cannot access information_schema).
    """
    try:
        resp = requests.get(
            f"{url}/rest/v1/information_schema.columns",
            headers=_auth_headers(key),
            params={
                "table_schema": "eq.public",
                "select":       "table_name,column_name,data_type,is_nullable,ordinal_position",
                "order":        "table_name,ordinal_position",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return _rows_to_schema_string(rows)
    except Exception:
        pass
    return ""


def _schema_from_rpc(url: str, key: str) -> str:
    """
    Call the get_schema_info() RPC function if it exists.
    Accessible by the anon key once the SQL function is created.
    See: setup_schema_rpc.sql in the project root.
    """
    try:
        resp = requests.post(
            f"{url}/rest/v1/rpc/get_schema_info",
            headers={**_auth_headers(key), "Content-Type": "application/json"},
            json={},
            timeout=10,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return _rows_to_schema_string(rows)
    except Exception:
        pass
    return ""


def _schema_from_openapi(url: str, key: str) -> tuple[str, list[str]]:
    """
    Fetch the OpenAPI spec from the PostgREST root.
    Returns (schema_str, table_names).  schema_str is empty if tables are
    empty; table_names is always populated when the spec succeeds.
    Requires service role on most Supabase projects.
    """
    try:
        resp = requests.get(
            f"{url}/rest/v1/",
            headers={**_auth_headers(key), "Accept": "application/openapi+json"},
            timeout=10,
        )
        if resp.status_code != 200:
            return "", []

        spec = resp.json()
        # Collect table names from OpenAPI paths
        table_names = [
            p.lstrip("/")
            for p in spec.get("paths", {})
            if p.startswith("/") and not p.startswith("/rpc")
        ]

        # Try to extract column types from the spec definitions
        defs = spec.get("definitions", spec.get("components", {}).get("schemas", {}))
        parts = []
        for tname in table_names:
            defn = defs.get(tname, {})
            props = defn.get("properties", {})
            if props:
                col_defs = [f"  {col} {meta.get('type', 'unknown')}"
                            for col, meta in props.items()]
                parts.append(f"Table: {tname}\n" + "\n".join(col_defs))

        return "\n\n".join(parts), table_names
    except Exception:
        pass
    return "", []


def _schema_from_row_sampling(url: str, key: str, table_names: list[str]) -> str:
    """
    Fetch one row per table to learn column names from live data.
    Only useful when the tables actually contain rows.
    """
    headers = _auth_headers(key)
    parts = []
    for tname in table_names:
        try:
            resp = requests.get(
                f"{url}/rest/v1/{tname}",
                headers=headers,
                params={"limit": "1"},
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and data[0]:
                    col_defs = [f"  {c}" for c in data[0].keys()]
                    parts.append(f"Table: {tname}\n" + "\n".join(col_defs))
        except Exception:
            continue
    return "\n\n".join(parts)


def _discover_tables_via_anon(url: str, key: str) -> list[str]:
    """
    Discover accessible public tables using the anon key by querying
    pg_catalog.pg_tables via RPC or via a direct PostgREST table listing.
    Falls back to querying pg_tables through the Supabase RPC endpoint.
    """
    # Try: RPC that wraps pg_catalog (works with anon if SECURITY DEFINER)
    try:
        resp = requests.post(
            f"{url}/rest/v1/rpc/list_public_tables",
            headers={**_auth_headers(key), "Content-Type": "application/json"},
            json={},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                tables = [r.get("tablename") or r.get("table_name") for r in data]
                tables = [t for t in tables if t]
                if tables:
                    return tables
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_database_schema() -> str:
    """
    Dynamically fetch the complete database schema from Supabase.

    Strategy waterfall (first success wins):

    With SUPABASE_SERVICE_KEY set (recommended for full schema):
      1. information_schema.columns  — complete with types & nullability
      2. OpenAPI spec                — complete with column types from definitions

    With only SUPABASE_ANON_KEY (limited but works):
      3. get_schema_info() RPC       — complete, requires one-time SQL setup
      4. list_public_tables() RPC    — discovers table list, then row-samples
      5. Row sampling                — only works when tables have rows

    To enable full dynamic schema without the service key, run the SQL in
    setup_schema_rpc.sql once in your Supabase SQL editor.
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    url, anon_key, svc_key = _credentials()
    if not url or not anon_key:
        return "(Error: SUPABASE_URL or SUPABASE_ANON_KEY not set in .env)"

    # ── 1. Service role: information_schema (most accurate) ──────────────────
    if svc_key:
        result = _schema_from_information_schema(url, svc_key)
        if result:
            _schema_cache = result
            return _schema_cache

    # ── 2. Anon key: get_schema_info() RPC (needs one-time SQL setup) ────────
    result = _schema_from_rpc(url, anon_key)
    if result:
        _schema_cache = result
        return _schema_cache

    # ── 3. Service role: OpenAPI spec ─────────────────────────────────────────
    if svc_key:
        schema_str, table_names = _schema_from_openapi(url, svc_key)
        if schema_str:
            _schema_cache = schema_str
            return _schema_cache
        # Even if schema_str is empty (tables have no rows), we have table_names
        if table_names:
            result = _schema_from_row_sampling(url, anon_key, table_names)
            if result:
                _schema_cache = result
                return _schema_cache

    # ── 4. Anon key: list_public_tables() RPC ────────────────────────────────
    table_names = _discover_tables_via_anon(url, anon_key)
    if table_names:
        result = _schema_from_row_sampling(url, anon_key, table_names)
        if result:
            _schema_cache = result
            return _schema_cache

    # ── 5. Anon key: try OpenAPI anyway (may work on some projects) ───────────
    schema_str, table_names = _schema_from_openapi(url, anon_key)
    if schema_str:
        _schema_cache = schema_str
        return _schema_cache
    if table_names:
        result = _schema_from_row_sampling(url, anon_key, table_names)
        if result:
            _schema_cache = result
            return _schema_cache

    # ── Fallback ──────────────────────────────────────────────────────────────
    _schema_cache = (
        "(Could not fetch database schema. "
        "Option A: Add SUPABASE_SERVICE_KEY to .env. "
        "Option B: Run setup_schema_rpc.sql in your Supabase SQL editor — "
        "this creates a get_schema_info() function accessible by the anon key.)"
    )
    return _schema_cache


def invalidate_schema_cache() -> None:
    """Force a fresh fetch on the next call to get_database_schema()."""
    global _schema_cache
    _schema_cache = None


def execute_sql(query: str) -> dict:
    """Execute a SQL query via the Supabase RPC run_query function."""
    from config.settings import get_supabase_client
    client = get_supabase_client()
    try:
        query = query.strip().rstrip(";")
        result = client.rpc("run_query", {"sql_query": query}).execute()
        if result.data:
            data = [row for row in result.data if row and isinstance(row, dict)]
            return {"success": True, "data": data, "error": None}
        return {"success": True, "data": [], "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}