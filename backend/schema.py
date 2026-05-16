"""
Dynamic database schema fetcher — uses supabase-py exclusively.

Strategy (in order):
  1. Call the `get_schema_info` RPC (needs one-time SQL in supabase_setup.sql)
  2. Probe all accessible tables; read column names from a sample row
  3. For tables that are empty, request a non-existing column to force a
     PostgREST error that lists valid column names in its hint/message
  4. Return a descriptive error string so the LLM knows schema is unavailable
"""

from __future__ import annotations

_schema_cache: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client():
    from config.settings import get_supabase_client
    return get_supabase_client()


def _rows_to_schema_string(rows: list[dict]) -> str:
    """Convert information_schema-style rows into a human-readable string."""
    tables: dict[str, list[dict]] = {}
    for row in rows:
        tname = row.get("table_name", "")
        if not tname:
            continue
        tables.setdefault(tname, []).append(row)

    parts = []
    for tname, cols in tables.items():
        col_lines = []
        for col in cols:
            col_def = f"  {col.get('column_name', '?')} {col.get('data_type', 'unknown')}"
            if col.get("is_nullable") == "NO":
                col_def += " NOT NULL"
            col_lines.append(col_def)
        parts.append(f"Table: {tname}\n" + "\n".join(col_lines))

    return "\n\n".join(parts)


# ── Strategy 1: get_schema_info RPC ──────────────────────────────────────────

def _fetch_via_rpc(client) -> str:
    """
    Call the custom get_schema_info() Postgres function.
    Requires running supabase_setup.sql once in the Supabase SQL Editor.
    """
    try:
        result = client.rpc("get_schema_info", {}).execute()
        if result.data and isinstance(result.data, list):
            schema = _rows_to_schema_string(result.data)
            if schema:
                return schema
    except Exception:
        pass
    return ""


# ── Strategy 2: probe tables ──────────────────────────────────────────────────

# Tables to probe — only the ones confirmed accessible by the anon role.
# Add more as your project grows.
_CANDIDATE_TABLES = [
    "profiles", "users", "posts", "articles", "comments",
    "products", "orders", "order_items", "categories",
    "tasks", "notes", "todos", "messages", "notifications",
    "jobs", "applications", "companies", "teams", "settings",
]


def _columns_from_empty_table(client, table_name: str) -> list[str]:
    """
    When a table is empty, trigger a PostgREST error by selecting a
    deliberately invalid column. PostgREST's error hint lists valid columns.
    Falls back to empty list if the hint isn't parseable.
    """
    try:
        # Request a column that certainly doesn't exist
        client.table(table_name).select("__probe_column_doesnt_exist__").limit(1).execute()
    except Exception as e:
        err = str(e)
        # PostgREST error format: "... Hint: valid columns are: id, name, ..."
        if "valid columns are:" in err.lower() or "column" in err.lower():
            import re
            # Try to find the hint section listing columns
            match = re.search(r"(?:valid columns are|hint)[:\s]+([^\}\"]+)", err, re.IGNORECASE)
            if match:
                raw = match.group(1).strip(" .\"'")
                cols = [c.strip(" \"'") for c in raw.split(",") if c.strip()]
                if cols:
                    return cols
    return []


def _probe_tables(client, candidates: list[str]) -> str:
    """Try each candidate table; collect column names."""
    parts = []
    for tname in candidates:
        try:
            result = client.table(tname).select("*").limit(1).execute()

            if result.data:
                # Got a row — read column names from dict keys
                cols = list(result.data[0].keys())
                col_lines = [f"  {c}" for c in cols]
                parts.append(f"Table: {tname}\n" + "\n".join(col_lines))

            else:
                # Table exists but is empty — probe for column names
                cols = _columns_from_empty_table(client, tname)
                if cols:
                    col_lines = [f"  {c}" for c in cols]
                    parts.append(f"Table: {tname}\n" + "\n".join(col_lines))
                else:
                    # Table exists, can't determine columns — note it anyway
                    parts.append(f"Table: {tname}\n  (empty — run supabase_setup.sql for column details)")

        except Exception as e:
            err = str(e)
            # Skip tables that genuinely don't exist
            if (
                "does not exist" in err
                or "PGRST204" in err
                or "PGRST116" in err
                or "schema cache" in err.lower()
            ):
                continue
            # Otherwise surface the error in the schema string
            parts.append(f"Table: {tname}\n  (error: {err[:100]})")

    return "\n\n".join(parts)


# ── Public API ────────────────────────────────────────────────────────────────

def get_database_schema() -> str:
    """
    Return a human-readable schema string for the connected Supabase project.
    Results are cached in-process; call invalidate_schema_cache() to reset.
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    client = _get_client()

    # Strategy 1: RPC (most accurate, needs supabase_setup.sql run once)
    schema = _fetch_via_rpc(client)
    if schema:
        _schema_cache = schema
        return _schema_cache

    # Strategy 2: probe known candidate tables
    schema = _probe_tables(client, _CANDIDATE_TABLES)
    if schema:
        _schema_cache = schema
        return _schema_cache

    # Nothing worked
    _schema_cache = (
        "(Database schema unavailable. "
        "Please run supabase_setup.sql in the Supabase SQL Editor to enable "
        "dynamic schema fetching via the get_schema_info() RPC function.)"
    )
    return _schema_cache


def invalidate_schema_cache() -> None:
    """Clear the in-process cache so the next call re-fetches fresh schema."""
    global _schema_cache
    _schema_cache = None


def execute_sql(query: str) -> dict:
    """
    Execute a SQL query via the Supabase run_query RPC function.

    run_query() returns a single JSON array value (the result of json_agg),
    so result.data is either:
      - A JSON-parsed list of row dicts  (supabase-py may auto-parse it)
      - A list containing a single JSON string / nested list
    We normalise all cases into a plain list[dict].
    """
    client = _get_client()
    try:
        query = query.strip().rstrip(";")
        result = client.rpc("run_query", {"sql_query": query}).execute()

        raw = result.data

        # Case 1: supabase-py returned a list of dicts directly
        if isinstance(raw, list) and all(isinstance(r, dict) for r in raw):
            return {"success": True, "data": raw, "error": None}

        # Case 2: run_query returned a JSON array — supabase-py gives us a
        # list with one element which is the parsed JSON array
        if isinstance(raw, list) and len(raw) == 1:
            inner = raw[0]
            if isinstance(inner, list):
                data = [r for r in inner if isinstance(r, dict)]
                return {"success": True, "data": data, "error": None}
            if isinstance(inner, dict):
                return {"success": True, "data": [inner], "error": None}

        # Case 3: empty result
        return {"success": True, "data": [], "error": None}

    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}