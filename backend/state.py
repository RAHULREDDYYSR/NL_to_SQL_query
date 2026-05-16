from typing import Optional, TypedDict


class QueryState(TypedDict):
    user_query: str
    refined_query: str
    is_valid: bool
    error: Optional[str]
    sql_query: str
    status: str
    feedback: str
    iteration: int
    db_schema: str
    execution_result: Optional[dict]