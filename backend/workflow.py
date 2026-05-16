from langgraph.graph import StateGraph, END
from backend.state import QueryState
from backend.agents.validator import validate_and_refine_query
from backend.agents.generator import generate_sql
from backend.agents.evaluator import evaluate_sql
from backend.schema import get_database_schema
from config.settings import MAX_ITERATIONS
from dotenv import load_dotenv
load_dotenv()


def should_continue(state: QueryState) -> str:
    """Determine whether to continue the loop or end."""
    # Stop immediately if the validator flagged the query as invalid
    if not state.get("is_valid", True):
        return "end"
    if state["status"] == "ok":
        return "end"
    if state["iteration"] >= MAX_ITERATIONS:
        return "end"
    return "continue"


def route_after_validate(state: QueryState) -> str:
    """After validation: proceed to generate if valid, else end early."""
    if not state.get("is_valid", True):
        return "end"
    return "generate"


def create_workflow() -> StateGraph:
    """Create the LangGraph workflow."""
    workflow = StateGraph(QueryState)

    workflow.add_node("validate", validate_and_refine_query)
    workflow.add_node("generate", generate_sql)
    workflow.add_node("evaluate", evaluate_sql)

    workflow.set_entry_point("validate")

    # Route after validate: skip generation if query is invalid
    workflow.add_conditional_edges(
        "validate",
        route_after_validate,
        {
            "generate": "generate",
            "end": END
        }
    )

    workflow.add_edge("generate", "evaluate")

    workflow.add_conditional_edges(
        "evaluate",
        should_continue,
        {
            "continue": "generate",
            "end": END
        }
    )

    return workflow.compile()


def run_nl_to_sql(user_query: str) -> dict:
    """
    Main function to convert natural language to SQL.
    Returns the final state with SQL query and execution results.
    """
    db_schema = get_database_schema()

    initial_state: QueryState = {
        "user_query": user_query,
        "refined_query": "",
        "is_valid": True,
        "error": None,
        "sql_query": "",
        "status": "pending",
        "feedback": "",
        "iteration": 0,
        "execution_result": None
    }

    initial_state["db_schema"] = db_schema

    graph = create_workflow()

    final_state = graph.invoke(initial_state)

    return final_state
