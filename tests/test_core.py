"""Essential tests for University Q&A Agent - validates database, schema, validation, and end-to-end flow."""
import pytest
import json
from sqlalchemy import inspect
from unittest.mock import patch, MagicMock

from src.database.models import Teacher, Student, Course, Enrollment
from src.agent.schema import SchemaManager
from src.agent.executor import QueryExecutor
from src.agent.tools import DatabaseTools
from src.agent.graph import create_qa_agent


class TestDatabase:
    """Test database models and schema."""

    def test_models_and_seed_data(self, test_session):
        """Verify all models exist and seed data is loaded."""
        assert test_session.query(Teacher).count() == 5
        assert test_session.query(Student).count() == 5
        assert test_session.query(Course).count() == 4
        assert test_session.query(Enrollment).count() == 10


class TestSchemaAndQuery:
    """Test schema discovery and query execution."""

    def test_schema_reflection(self, seeded_engine):
        """Verify SQLAlchemy discovers all tables at runtime."""
        inspector = inspect(seeded_engine)
        tables = inspector.get_table_names()
        assert 'teachers' in tables
        assert 'students' in tables
        assert 'courses' in tables
        assert 'enrollments' in tables

    def test_simple_query_execution(self, seeded_engine):
        """Verify SQL queries execute correctly."""
        executor = QueryExecutor(seeded_engine)
        results = executor.execute("SELECT COUNT(*) as count FROM teachers")
        assert len(results) == 1
        assert results[0]['count'] == 5


class TestSQLValidation:
    """Test SQL safety and syntax validation."""

    def test_safety_validation(self, seeded_engine):
        """Verify dangerous operations (DROP, DELETE) are blocked."""
        tools = DatabaseTools(seeded_engine)

        result = tools.validate_sql_safety("DROP TABLE teachers")
        assert not result["valid"]
        assert "DROP" in result["error"] or "Only SELECT and WITH" in result["error"]

        result = tools.validate_sql_safety("SELECT * FROM teachers")
        assert result["valid"]

    def test_syntax_validation(self, seeded_engine):
        """Verify only SELECT and WITH queries are allowed."""
        tools = DatabaseTools(seeded_engine)

        assert tools.validate_sql_syntax("SELECT * FROM teachers")["valid"]

        assert tools.validate_sql_syntax("WITH cte AS (SELECT 1) SELECT * FROM cte")["valid"]

        assert not tools.validate_sql_syntax("INSERT INTO teachers VALUES (1)")["valid"]

    def test_query_through_tools(self, seeded_engine):
        """Verify queries execute through DatabaseTools and return JSON."""
        tools = DatabaseTools(seeded_engine)
        result = tools.query_database("SELECT COUNT(*) as count FROM teachers")

        assert "count" in result
        results_list = json.loads(result)
        assert len(results_list) > 0


class TestAgentFlow:
    """Test end-to-end agent query processing with full trace validation."""

    @patch('google.genai.Client')
    def test_agent_complete_e2e_flow(self, mock_client_class, seeded_engine):
        """Test complete end-to-end flow from START through all validation nodes to END.

        Full success path:
        START → validate_input → generate_sql → validate_safety → validate_syntax
             → execute_query → decide_retry → END

        Validates:
        1. Input question passes validation
        2. LLM generates valid SQL
        3. SQL passes safety check (no DROP/DELETE/INSERT/UPDATE)
        4. SQL passes syntax check (SELECT or WITH only)
        5. Query executes successfully against database
        6. Routing decision completes (no retry needed)
        7. Final answer includes query results
        8. Trace captures all steps with proper timestamps
        """
        mock_response = MagicMock()
        mock_response.text = "SQL Query:\nSELECT COUNT(*) as count FROM teachers\n\nAnswer: 5 teachers found."
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=100,
            candidates_token_count=30
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        agent = create_qa_agent(seeded_engine, api_key="test-key")
        result = agent.query("How many teachers total?", trace_id="e2e-001", session_id="test-session")

        assert result['answer'] is not None
        assert 'Query:' in result['answer']  # Query succeeded
        assert 'Results:' in result['answer']  # Results are included
        assert 'Error' not in result['answer']  # No errors

        trace = result['trace']
        assert trace['trace_id'] == "e2e-001"
        assert 'events' in trace

        events = trace['events']
        event_types = [event['event_type'] for event in events]
        event_names = [event['step_name'] for event in events]

        assert len(events) >= 5, f"Expected >= 5 events, got {len(events)}: {event_names}"

        expected_nodes = ['validate_input', 'generate_sql', 'validate_safety',
                         'validate_syntax', 'execute_query']
        for expected in expected_nodes:
            found = any(expected.lower() in str(et).lower() for et in event_types)
            assert found, f"Missing expected node: {expected}. Got: {event_types}"

        for event in events:
            assert 'event_type' in event, "Missing event_type"
            assert 'step_name' in event, "Missing step_name"
            assert 'timestamp' in event, "Missing timestamp"
            assert 'sequence' in event, "Missing sequence number"

        error_events = [e for e in events if e.get('error') is not None]
        assert len(error_events) == 0, f"Unexpected errors in trace: {error_events}"

        output_events = [e for e in events if e.get('output_data') is not None]
        assert len(output_events) > 0, "No output data captured - query may not have executed"

    def test_agent_error_handling(self, seeded_engine):
        """Test agent handles invalid input and traces error path."""
        agent = create_qa_agent(seeded_engine, api_key="test-key")
        result = agent.query("", trace_id="test-error", session_id="test-session")

        assert "Error" in result['answer']

        trace = result['trace']
        assert trace['trace_id'] == "test-error"
        assert len(trace['events']) > 0
