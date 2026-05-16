import streamlit as st
from backend.workflow import run_nl_to_sql
from backend.schema import execute_sql

st.set_page_config(page_title="NL to SQL Query Generator", page_icon="🔍")

st.title("🔍 Natural Language to SQL Query Generator")
st.markdown("**Agent Mailer Database**")

if "history" not in st.session_state:
    st.session_state.history = []

user_query = st.text_area(
    "Enter your query in natural language:",
    placeholder="e.g., Show me all users who have active job applications",
    height=100
)

if st.button("Generate SQL & Execute", type="primary"):
    if not user_query.strip():
        st.error("Please enter a query")
    else:
        with st.spinner("Processing your query through agents..."):
            try:
                result = run_nl_to_sql(user_query)

                # ── Validator rejected the query ──────────────────────────────
                if not result.get("is_valid", True):
                    error_msg = result.get("error") or "Your query is out of context for this database."
                    st.error(f"❌ **Query Rejected by Validator**\n\n{error_msg}")
                    st.info(
                        "💡 Try asking something about **users**, **job descriptions**, or **generated contents** "
                        "in the Agent Mailer database."
                    )

                # ── Valid query ───────────────────────────────────────────────
                else:
                    st.success("✅ Query generated successfully!")

                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("📝 Refined Query")
                        st.text(result.get("refined_query", ""))
                    with col2:
                        st.subheader("🔄 Iterations")
                        st.write(f"Total: {result.get('iteration', 0)}")

                    st.subheader("💾 Generated SQL")
                    st.code(result.get("sql_query", ""), language="sql")

                    if result.get("status") == "ok":
                        st.subheader("✅ Evaluation Status")
                        st.success(result.get("feedback", "Query validated successfully"))

                        st.subheader("⚡ Executing Query...")
                        exec_result = execute_sql(result["sql_query"])

                        if exec_result["success"]:
                            st.success("Query executed!")

                            data = exec_result.get("data", [])
                            if data:
                                st.subheader("📊 Results")
                                st.dataframe(data)
                            else:
                                st.info("No results returned")

                            st.session_state.history.append({
                                "query": user_query,
                                "sql": result["sql_query"],
                                "result": exec_result
                            })
                        else:
                            st.error(f"Execution failed: {exec_result['error']}")
                    else:
                        st.warning(f"⚠️ Query needs revision after {result.get('iteration', 0)} iteration(s): {result.get('feedback')}")

            except Exception as e:
                st.error(f"An error occurred: {str(e)}")

if st.session_state.history:
    st.divider()
    st.subheader("📜 Query History")
    for idx, item in enumerate(reversed(st.session_state.history[-5:])):
        with st.expander(f"Query {idx + 1}"):
            st.text_area("Natural Language", item["query"], disabled=True, key=f"nl_{idx}")
            st.code(item["sql"], language="sql", key=f"sql_{idx}")
            if item["result"]["success"]:
                st.success("Executed successfully")
            else:
                st.error(f"Error: {item['result']['error']}")