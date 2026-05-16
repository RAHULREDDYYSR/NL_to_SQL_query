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
Evaluate the generated SQL query for correctness, schema alignment, and intent match.
Be strict but fair — only request revision if there is a real issue."""

    feedback_context = f"\n\nPrevious feedback:\n{feedback}" if feedback else ""

    human_prompt = f"""Database Schema:
{db_schema}

Original Request: {refined_query}

Generated SQL:
{sql_query}{feedback_context}

Evaluate the SQL. Check for:
1. Syntax errors
2. Incorrect table/column names (must match schema exactly)
3. Intent misalignment with the original request
4. Missing JOINs where needed
5. Dangerous operations (no DROP, DELETE without WHERE)"""

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