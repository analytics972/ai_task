"""LangGraph-based Q&A agent with 7-node deterministic pipeline and retry logic."""
import os
import json
import logging
import time
import re
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from google import genai
from google.genai import types
from sqlalchemy import Engine

from .tools import DatabaseTools
from ..tracing import get_tracer, EventType, reset_tracer

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_QUESTION_LENGTH = 2000
API_TIMEOUT_MSEC = 15000


class ValidationError(Exception):
    """Raised when SQL validation fails - triggers retry."""
    pass


class ValidationResult(TypedDict):
    """Result of SQL validation."""
    valid: bool
    error: str | None


class AgentState(TypedDict):
    """State object passed through the LangGraph pipeline."""
    question: str
    schema: str | None
    sql_query: str | None
    query_results: str | None
    final_answer: str
    error: str | None
    attempt: int
    retry: bool | None
    retry_reason: str | None


class UniversityQAAgent:
    """Question-answering agent using deterministic 7-node LangGraph pipeline.

    Flow: validate_input → generate_sql → validate_safety → validate_syntax
          → execute_query → decide_retry → error_reporter → END

    Max 2 retries on validation failure. Unrecoverable errors route directly to error_reporter.
    """

    SYSTEM_INSTRUCTION = """You are a database SQL generator. Convert the question to SQL.

SUPPORTED QUERY TYPES:
- Aggregations: COUNT, SUM, AVG, MIN, MAX, GROUP BY, HAVING
- Joins: INNER JOIN, LEFT JOIN, RIGHT JOIN across multiple tables
- Filtering: WHERE clauses with multiple conditions
- Ordering: ORDER BY, sorting results
- Multi-step reasoning: Subqueries, CTEs (WITH clauses)
- Complex analysis: Combining joins with aggregations

RULES:
- Generate ONLY SELECT or WITH queries
- Never use DROP, DELETE, INSERT, UPDATE
- Ensure valid SQL syntax
- Return results even if empty
- Do NOT wrap SQL in markdown code blocks (no ```)
- Return raw SQL only, no markdown formatting
- Use proper JOINs for related data across tables
- Use GROUP BY for aggregations with conditions
- Use subqueries when multi-step logic is needed
- ALWAYS use column aliases (AS) when selecting multiple columns to avoid ambiguity
- Make column names descriptive in the SELECT clause
- Include LIMIT clauses to prevent large result sets unless asking for aggregates

Format your response as:
SQL Query:
SELECT ... FROM ...

Example (simple):
SQL Query:
SELECT COUNT(*) FROM users WHERE active = true

Example (aggregation with join):
SQL Query:
SELECT department, COUNT(*) as teacher_count FROM teachers GROUP BY department

Example (multi-column with aliases - IMPORTANT):
SQL Query:
SELECT t.name AS teacher_name, s.name AS student_name FROM students s
JOIN enrollments e ON s.id = e.student_id
JOIN course_offerings co ON e.course_offering_id = co.id
JOIN teachers t ON co.teacher_id = t.id"""

    def __init__(self, engine: Engine, api_key: str | None = None, model: str | None = None):
        self.engine = engine
        self.tools = DatabaseTools(engine)

        if api_key is None:
            api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        if not model:
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        self.client = genai.Client(
            api_key=api_key,
            http_options={"timeout": API_TIMEOUT_MSEC}
        )
        self.model = model

        self.generate_config = types.GenerateContentConfig(
            system_instruction=self.SYSTEM_INSTRUCTION
        )

        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build 7-node LangGraph with conditional routing."""
        graph = StateGraph(AgentState)

        graph.add_node("validate_input", self._validate_input)
        graph.add_node("generate_sql", self._generate_sql)
        graph.add_node("validate_safety", self._validate_sql_safety)
        graph.add_node("validate_syntax", self._validate_sql_syntax)
        graph.add_node("execute_query", self._execute_query)
        graph.add_node("decide_retry", self._decide_retry)
        graph.add_node("error_reporter", self._error_reporter)

        graph.add_edge(START, "validate_input")

        graph.add_conditional_edges(
            "validate_input",
            lambda state: "error_reporter" if state.get("error") else "generate_sql",
            {"error_reporter": "error_reporter", "generate_sql": "generate_sql"}
        )
        graph.add_edge("generate_sql", "validate_safety")

        graph.add_conditional_edges(
            "validate_safety",
            lambda state: "decide_retry" if state.get("retry") else "validate_syntax",
            {"decide_retry": "decide_retry", "validate_syntax": "validate_syntax"}
        )

        graph.add_conditional_edges(
            "validate_syntax",
            lambda state: "decide_retry" if state.get("retry") else "execute_query",
            {"decide_retry": "decide_retry", "execute_query": "execute_query"}
        )

        graph.add_conditional_edges(
            "execute_query",
            lambda state: "decide_retry" if state.get("retry") or state.get("error") else "end",
            {"decide_retry": "decide_retry", "end": END}
        )

        graph.add_conditional_edges(
            "decide_retry",
            lambda state: (
                "generate_sql" if state.get("retry") and not state.get("final_answer")
                else "error_reporter" if state.get("retry_reason") or state.get("error")
                else "end"
            ),
            {"generate_sql": "generate_sql", "error_reporter": "error_reporter", "end": END}
        )

        graph.add_edge("error_reporter", END)

        return graph.compile()

    def _validate_input(self, state: AgentState) -> AgentState:
        """Node 1: Validate question is not empty and fetch schema.

        Pre: state["question"] is set
        Post: state["schema"] loaded, state["error"] set on failure
        """
        tracer = get_tracer()
        question = state["question"].strip()

        if not question:
            state["error"] = "Question cannot be empty"
            state["final_answer"] = "Error: Question cannot be empty"
            logger.warning("Empty question provided")
            tracer.log_event(
                event_type=EventType.ERROR,
                step_name="Input Validation",
                error="Empty question",
            )
        elif len(question) > MAX_QUESTION_LENGTH:
            state["error"] = f"Question exceeds {MAX_QUESTION_LENGTH} characters"
            state["final_answer"] = f"Error: Question too long (max {MAX_QUESTION_LENGTH} chars)"
            logger.warning("Question too long: %d chars", len(question))
            tracer.log_event(
                event_type=EventType.ERROR,
                step_name="Input Validation",
                error=f"Question too long: {len(question)} chars",
            )
        else:
            tracer.log_event(
                event_type=EventType.VALIDATE_INPUT,
                step_name="Input Validation",
                input_data={"question": question},
                output_data={"valid": True},
            )
            state["schema"] = self.tools.get_schema()

        return state

    def _generate_sql(self, state: AgentState) -> AgentState:
        """Node 2: Use LLM to generate SQL from question.

        Pre: state["question"], state["schema"], state["attempt"]
        Post: state["sql_query"] set on success, state["retry"] set on failure
        """
        tracer = get_tracer()

        if state.get("error"):
            return state

        state["retry"] = False

        try:
            prompt = f"""Database Schema:
{state['schema']}

User Question: {state['question']}"""

            if state.get("retry_reason"):
                prompt += f"\n\nPrevious attempt failed: {state['retry_reason']}\nPlease fix the SQL and try again."

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self.generate_config
            )

            sql_query = ""
            match = re.search(r"SQL Query:\s*\n?(.*?)(?:\n\n|$)", response.text, re.DOTALL | re.IGNORECASE)
            if match:
                sql_part = match.group(1).strip()
                sql_part = re.sub(r"^```(?:sql)?\s*\n?", "", sql_part)
                sql_part = re.sub(r"\n?```\s*$", "", sql_part)

                sql_lines = []
                for line in sql_part.split("\n"):
                    line = line.strip()
                    if not line:
                        break
                    sql_lines.append(line)
                sql_query = " ".join(sql_lines).strip()

                if sql_query.count(";") > 1 or (sql_query.count(";") == 1 and not sql_query.endswith(";")):
                    raise ValidationError("Multiple SQL statements detected. Only one SELECT/WITH allowed.")

            if not sql_query or len(sql_query) < 10:
                raise ValidationError(f"Invalid SQL generated: {sql_query}")

            state["sql_query"] = sql_query

            tracer.log_event(
                event_type=EventType.GENERATE_SQL,
                step_name=f"SQL Generation (Attempt {state['attempt']}/{MAX_RETRIES})",
                input_data={"question": state["question"]},
                output_data={"sql": sql_query},
                input_tokens=response.usage_metadata.prompt_token_count if response.usage_metadata else None,
                output_tokens=response.usage_metadata.candidates_token_count if response.usage_metadata else None,
                model=self.model,
            )

        except ValidationError as e:
            logger.warning("SQL generation validation error (attempt %d): %s", state["attempt"], str(e))
            tracer.log_event(
                event_type=EventType.GENERATE_SQL,
                step_name=f"SQL Generation (Attempt {state['attempt']}/{MAX_RETRIES})",
                error=str(e),
            )
            state["retry_reason"] = str(e)
            if state["attempt"] < MAX_RETRIES:
                state["retry"] = True
                state["attempt"] += 1
            else:
                state["error"] = "SQL generation failed"
                state["final_answer"] = "Failed to generate valid SQL after retries"

        except (OSError, TimeoutError) as e:
            error_msg = f"API timeout/network error: {str(e)}"
            logger.warning("SQL generation transient error (attempt %d): %s", state["attempt"], error_msg)
            tracer.log_event(
                event_type=EventType.GENERATE_SQL,
                step_name=f"SQL Generation (Attempt {state['attempt']}/{MAX_RETRIES})",
                error=error_msg,
            )
            state["retry_reason"] = error_msg
            if state["attempt"] < MAX_RETRIES:
                state["retry"] = True
                state["attempt"] += 1
            else:
                state["error"] = "API timeout on retries"
                state["final_answer"] = "Query generation service unavailable"
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
            logger.error("SQL generation unexpected error: %s", error_msg)
            tracer.log_event(
                event_type=EventType.GENERATE_SQL,
                step_name=f"SQL Generation (Attempt {state['attempt']}/{MAX_RETRIES})",
                error=error_msg,
            )
            state["error"] = "Unexpected error during SQL generation"
            state["final_answer"] = "An unexpected error occurred. Please review trace data."

        return state

    def _validate_sql_safety(self, state: AgentState) -> AgentState:
        """Node 3: Validate SQL safety using AST parsing.

        Pre: state["sql_query"] is set
        Post: state["retry"] set if validation failed
        """
        tracer = get_tracer()

        if state.get("error") or not state.get("sql_query"):
            return state

        state["retry"] = False

        safety_check = self.tools.validate_sql_safety(state["sql_query"])

        if not safety_check["valid"]:
            logger.warning("SQL safety check failed: %s", safety_check.get("error"))
            tracer.log_event(
                event_type=EventType.VALIDATE_SAFETY,
                step_name=f"SQL Safety Validation (Attempt {state['attempt']}/{MAX_RETRIES})",
                error=safety_check.get("error"),
            )
            state["retry_reason"] = safety_check.get("error", "Safety check failed")
            if state["attempt"] < MAX_RETRIES:
                state["retry"] = True
                state["attempt"] += 1
                state["sql_query"] = None
            else:
                state["error"] = "SQL safety validation failed"
                state["final_answer"] = "SQL safety validation failed after retries"
        else:
            tracer.log_event(
                event_type=EventType.VALIDATE_SAFETY,
                step_name="SQL Safety Validation",
                input_data={"sql": state["sql_query"]},
                output_data={"valid": True},
            )

        return state

    def _validate_sql_syntax(self, state: AgentState) -> AgentState:
        """Node 4: Validate SQL syntax using AST parsing.

        Pre: state["sql_query"] is set
        Post: state["retry"] set if validation failed
        """
        tracer = get_tracer()

        if state.get("error") or not state.get("sql_query"):
            return state

        state["retry"] = False

        syntax_check = self.tools.validate_sql_syntax(state["sql_query"])

        if not syntax_check["valid"]:
            logger.warning("SQL syntax check failed: %s", syntax_check.get("error"))
            tracer.log_event(
                event_type=EventType.VALIDATE_SYNTAX,
                step_name=f"SQL Syntax Validation (Attempt {state['attempt']}/{MAX_RETRIES})",
                error=syntax_check.get("error"),
            )
            state["retry_reason"] = syntax_check.get("error", "Syntax check failed")
            if state["attempt"] < MAX_RETRIES:
                state["retry"] = True
                state["attempt"] += 1
                state["sql_query"] = None
            else:
                state["error"] = "SQL syntax validation failed"
                state["final_answer"] = "SQL syntax validation failed after retries"
        else:
            tracer.log_event(
                event_type=EventType.VALIDATE_SYNTAX,
                step_name="SQL Syntax Validation",
                input_data={"sql": state["sql_query"]},
                output_data={"valid": True},
            )

        return state

    def _execute_query(self, state: AgentState) -> AgentState:
        """Node 5: Execute validated SQL against database.

        Pre: state["sql_query"] is validated
        Post: state["query_results"] and state["final_answer"] set on success
        """
        tracer = get_tracer()

        if state.get("error") or not state.get("sql_query"):
            return state

        state["retry"] = False

        try:
            results = self.tools.query_database(state["sql_query"])

            if isinstance(results, str):
                try:
                    parsed = json.loads(results)
                    if isinstance(parsed, dict) and "error" in parsed:
                        raise ValidationError(f"Query failed: {parsed['error']}")
                except (json.JSONDecodeError, TypeError):
                    pass

            state["query_results"] = results
            state["final_answer"] = f"Query: {state['sql_query']}\n\nResults: {results}"

            tracer.log_event(
                event_type=EventType.EXECUTE_QUERY,
                step_name="Query Execution",
                input_data={"sql": state["sql_query"]},
                output_data={"results": results},
            )

        except ValidationError as e:
            logger.warning("Query execution error: %s", str(e))
            tracer.log_event(
                event_type=EventType.EXECUTE_QUERY,
                step_name="Query Execution",
                error=str(e),
            )
            state["retry_reason"] = str(e)
            if state["attempt"] < MAX_RETRIES:
                state["retry"] = True
                state["attempt"] += 1
            else:
                state["error"] = "Query execution failed"
                state["final_answer"] = "Query execution failed"

        except (OSError, TimeoutError) as e:
            error_msg = f"Database connection error: {str(e)}"
            logger.warning("Query execution transient error (attempt %d): %s", state["attempt"], error_msg)
            tracer.log_event(
                event_type=EventType.EXECUTE_QUERY,
                step_name="Query Execution",
                error=error_msg,
            )
            state["retry_reason"] = error_msg
            if state["attempt"] < MAX_RETRIES:
                state["retry"] = True
                state["attempt"] += 1
            else:
                state["error"] = "Database unreachable after retries"
                state["final_answer"] = "Database is currently unavailable"
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
            logger.error("Query execution unexpected error: %s", error_msg)
            tracer.log_event(
                event_type=EventType.EXECUTE_QUERY,
                step_name="Query Execution",
                error=error_msg,
            )
            state["error"] = "Unexpected error during query execution"
            state["final_answer"] = "An unexpected error occurred. Please review trace data."

        return state

    def _decide_retry(self, state: AgentState) -> AgentState:
        """Node 6: Decide routing: retry, error_reporter, or END.

        This is a routing-only node. No state changes, just logging.
        """
        tracer = get_tracer()

        if state.get("retry") and not state.get("final_answer"):
            decision = "retry generate_sql"
        elif state.get("retry_reason") or state.get("error"):
            decision = "error_reporter"
        elif state.get("final_answer"):
            decision = "finalize and END"
        else:
            decision = "END"

        tracer.log_event(
            event_type=EventType.DECIDE_RETRY,
            step_name=f"Routing: {decision}",
            output_data={
                "retry": state.get("retry"),
                "has_answer": bool(state.get("final_answer")),
                "attempt": state.get("attempt"),
            },
        )

        return state

    def _error_reporter(self, state: AgentState) -> AgentState:
        """Node 7: Finalize error message. Ensures final_answer is always set.

        Pre: state["final_answer"] may be empty
        Post: state["final_answer"] is guaranteed to be set
        """
        tracer = get_tracer()

        if not state.get("final_answer"):
            if state.get("retry_reason"):
                state["final_answer"] = f"Error: {state['retry_reason']}"
            elif state.get("error"):
                state["final_answer"] = f"Error: {state['error']}"
            else:
                state["final_answer"] = "Error: Unable to process question"

        error_msg = state.get("retry_reason") or state.get("error", "Unknown error")
        tracer.log_event(
            event_type=EventType.ERROR,
            step_name="Error Reporter",
            error=error_msg,
            output_data={"final_answer": state.get("final_answer")},
        )

        return state

    def query(self, question: str, trace_id: str | None = None, session_id: str | None = None,
              verbose: bool = False) -> dict:
        """Process a question and return answer with full trace.

        Args:
            question: User's natural language question
            trace_id: Optional trace identifier for logging
            session_id: Optional session ID for audit
            verbose: If True, stream output instead of batching

        Returns:
            dict with keys: question, answer, trace
        """
        if trace_id:
            reset_tracer()
        tracer = get_tracer(trace_id, session_id=session_id)

        initial_state: AgentState = {
            "question": question,
            "schema": None,
            "sql_query": None,
            "query_results": None,
            "final_answer": "",
            "error": None,
            "attempt": 1,
            "retry": False,
            "retry_reason": None,
        }

        if verbose:
            final_state = self._execute_with_streaming(initial_state)
        else:
            final_state = self.graph.invoke(initial_state)

        tracer.log_event(
            event_type=EventType.GRAPH_NODE,
            step_name="END",
            output_data={"final_answer": final_state["final_answer"]},
        )

        trace = tracer.get_trace()

        return {
            "question": question,
            "answer": final_state["final_answer"],
            "trace": trace,
        }

    def _execute_with_streaming(self, initial_state: AgentState) -> AgentState:
        """Execute graph and stream output."""
        final_state = None

        for output in self.graph.stream(initial_state):
            for node_name, state in output.items():
                final_state = state

        return final_state


def create_qa_agent(engine: Engine, api_key: str | None = None, model: str | None = None) -> UniversityQAAgent:
    """Factory function to create a Q&A agent instance."""
    return UniversityQAAgent(engine, api_key, model)
