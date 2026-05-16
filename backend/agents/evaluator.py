from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from config.settings import get_openai_client


class EvaluatorOutput(BaseModel):
    """Structured output for the SQL evaluator agent."""
    status: Literal["ok", "needs_revision"] = Field(
        description="'ok' if the SQL query is correct and aligns with the intent. "
                    "'needs_revision' if there are syntax errors, wrong table/column names, "
                    "intent misalignment, missing JOINs, or dangerous operations."
    )
    feedback: str = Field(
        description="When status is 'ok': a brief confirmation of why the query is good. "
                    "When status is 'needs_revision': specific, actionable feedback describing "
                    "exactly what needs to be fixed in the SQL query."
    )


def evaluate_sql(state: dict) -> dict:
    """
    Agent 3: Evaluate the generated SQL query.
    - Validates PostgreSQL syntax
    - Checks schema usage
    - Verifies intent alignment
    - Returns status: 'ok' or 'needs_revision' with feedback
    """
    refined_query = state["refined_query"]
    db_schema = state.get("db_schema")
    sql_query = state["sql_query"]
    feedback = state.get("feedback", "")
    current_iteration = state.get("iteration", 0)

    if not db_schema:
        from backend.schema import get_database_schema
        db_schema = get_database_schema()

    client = get_openai_client()

    system_prompt = """You are a SQL query evaluator for PostgreSQL.
Your job is to verify that the generated SQL query correctly answers the original request.

Evaluation rules:
1. SYNTAX — check for valid PostgreSQL syntax.
2. SCHEMA ALIGNMENT — table and column names must match the schema exactly.
   EXCEPTION: if the schema is listed as unavailable or empty, do NOT mark the
   query as needing revision for column/table issues — the generator made its
   best guess. Only flag real syntax errors in that case.
3. INTENT MATCH — the query must actually answer what was asked.
   - If the user asked for specific columns (names, totals, etc.), SELECT * is wrong.
   - If the user asked for a count, a plain SELECT is wrong.
4. SAFETY — no DROP, DELETE without WHERE, or destructive operations.
5. COMPLETENESS — flag missing JOINs or filters only if they clearly change the result.

Mark status 'ok' when the query is correct and complete.
Mark status 'needs_revision' only when there is a concrete, fixable issue.
Your feedback must be specific and actionable — state exactly what column/clause to change."""

    current_iteration_display = f" (revision #{current_iteration})" if current_iteration > 0 else ""

    human_prompt = f"""Database Schema:
{db_schema}

Original Request: {refined_query}

Generated SQL{current_iteration_display}:
```sql
{sql_query}
```

Evaluate the SQL against the checklist above and return your verdict."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    structured_client = client.with_structured_output(EvaluatorOutput)
    result: EvaluatorOutput = structured_client.invoke(messages)

    return {
        "status": result.status,
        "feedback": result.feedback,
        "db_schema": db_schema,
        "iteration": current_iteration + 1
    }