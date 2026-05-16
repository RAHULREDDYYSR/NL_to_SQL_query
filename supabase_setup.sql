-- ============================================================
-- Run ONCE in Supabase SQL Editor:
-- Project: https://supabase.com/dashboard/project/bvzdcovjdehzldspissp/sql
-- ============================================================

-- ── 1. get_schema_info ───────────────────────────────────────
-- Lets the anon key read information_schema without direct access.

CREATE OR REPLACE FUNCTION get_schema_info()
RETURNS TABLE(
    table_name       text,
    column_name      text,
    data_type        text,
    is_nullable      text,
    ordinal_position int
)
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT
        c.table_name::text,
        c.column_name::text,
        c.data_type::text,
        c.is_nullable::text,
        c.ordinal_position::int
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
    ORDER BY c.table_name, c.ordinal_position;
$$;

GRANT EXECUTE ON FUNCTION get_schema_info() TO anon;
GRANT EXECUTE ON FUNCTION get_schema_info() TO authenticated;


-- ── 2. run_query ─────────────────────────────────────────────
-- Executes a dynamic SELECT and returns rows as a JSON array.
-- Only SELECT statements are allowed; any mutation raises an error.

CREATE OR REPLACE FUNCTION run_query(sql_query text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result json;
    lower_query text := lower(trim(sql_query));
BEGIN
    -- Safety guard: reject anything that isn't a SELECT
    IF lower_query NOT LIKE 'select%' THEN
        RAISE EXCEPTION 'Only SELECT statements are permitted. Got: %', left(sql_query, 80);
    END IF;

    EXECUTE format('SELECT json_agg(t) FROM (%s) t', sql_query) INTO result;

    -- Return an empty array rather than NULL for zero-row results
    RETURN COALESCE(result, '[]'::json);
END;
$$;

GRANT EXECUTE ON FUNCTION run_query(text) TO anon;
GRANT EXECUTE ON FUNCTION run_query(text) TO authenticated;
