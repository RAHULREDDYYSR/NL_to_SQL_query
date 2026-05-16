from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from config.settings import get_openai_client


class GeneratorOutput(BaseModel):
    """Structured output for the SQL generator agent."""
    sql_query: str = Field(
        description="A valid PostgreSQL SELECT query generated from the natural language request. "
                    "Must only be a SELECT statement — no INSERT, UPDATE, DELETE, or DROP. "
                    "Use the exact table and column names from the schema."
    )
    explanation: str = Field(
        description="A brief one-sentence explanation of what this SQL query does."
    )


def generate_sql(state: dict) -> dict:
    """
    Agent 2: Generate SQL query from refined natural language query.
    - Uses database schema
    - Generates PostgreSQL SELECT queries with structured output
    """
    refined_query = state["refined_query"]
    db_schema = state.get("db_schema")
    feedback = state.get("feedback")
    previous_sql = state.get("sql_query")

    if not db_schema:
        from backend.schema import get_database_schema
        db_schema = get_database_schema()

    client = get_openai_client()

    system_prompt = """You are a SQL query generator for PostgreSQL.
Generate only SELECT queries (no INSERT, UPDATE, DELETE, DROP).
Use proper PostgreSQL syntax with correct table and column names from the schema.
When given feedback on a previous attempt, you MUST fix ALL the issues described — do not return the same query.
Always provide a brief explanation of what the query does."""

    if feedback and previous_sql:
        human_prompt = f"""Database Schema:
{db_schema}

Original Natural Language Request:
{refined_query}

Previous SQL Query (INCORRECT — do NOT return this again):
```sql
{previous_sql}
```

Evaluator Feedback (fix EVERY point listed):
{feedback}

Generate a corrected PostgreSQL SELECT query that fully addresses all feedback above."""
    else:
        human_prompt = f"""Database Schema:
{db_schema}

Natural Language Query: {refined_query}

Generate a PostgreSQL SELECT query."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    structured_client = client.with_structured_output(GeneratorOutput)
    result: GeneratorOutput = structured_client.invoke(messages)

    return {
        "sql_query": result.sql_query.strip(),
        "db_schema": db_schema
    }