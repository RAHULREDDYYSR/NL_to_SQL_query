from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from config.settings import get_openai_client


class ValidatorOutput(BaseModel):
    """Structured output for the validator agent."""
    refined_query: str = Field(
        description="The refined, clearer version of the user's natural language query. "
                    "If the query is out-of-context or invalid, return the original query unchanged."
    )
    is_valid: bool = Field(
        description="True if the query is relevant to the database schema and can be answered with SQL. "
                    "False if the query is out-of-context, irrelevant, or not answerable from the database."
    )
    error: Optional[str] = Field(
        default=None,
        description="A clear, human-friendly error message ONLY when is_valid is False. "
                    "Explain why the query is out-of-context or cannot be answered. "
                    "Must be None when is_valid is True."
    )


def validate_and_refine_query(state: dict) -> dict:
    """
    Agent 1: Validate and refine the user's natural language query.
    - Checks if the query is relevant to the database schema
    - Refines the query in natural language for clarity
    - Returns is_valid=False with a descriptive error if query is out-of-context
    """
    user_query = state["user_query"]
    db_schema = state.get("db_schema", "")
    client = get_openai_client()

    system_prompt = """You are a query validator and refiner for a SQL query system.

Your job is to:
1. Determine if the user's query is relevant to the provided database schema.
2. If relevant, refine the query to be clearer and more specific for SQL generation.
3. If NOT relevant (out-of-context, nonsensical, or about topics unrelated to the database), mark it as invalid and explain why.

A query is INVALID if:
- It asks about topics completely unrelated to the database tables/columns
- It is a general knowledge question (e.g., "What is the capital of France?")
- It requests operations that are impossible or unrelated to the data available
- It is gibberish or cannot be understood

A query is VALID if it can reasonably be answered using a SQL SELECT query against the given schema."""

    human_prompt = f"""Database Schema:
{db_schema}

User Query: {user_query}

Validate and (if valid) refine this query."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    structured_client = client.with_structured_output(ValidatorOutput)
    result: ValidatorOutput = structured_client.invoke(messages)

    return {
        "refined_query": result.refined_query,
        "is_valid": result.is_valid,
        "error": result.error,
        "db_schema": db_schema
    }