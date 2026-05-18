"""SQL query execution with result limits and error sanitization."""
from sqlalchemy import text, Engine
from sqlalchemy.orm import Session
from typing import Any
import logging
import re

logger = logging.getLogger(__name__)

MAX_RESULTS = 1000


class QueryExecutor:
    """Executes SQL queries and returns results with safety limits."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def _apply_limit(self, sql: str) -> str:
        """Add LIMIT clause if not present to prevent large result sets."""
        sql_stripped = sql.strip()
        sql_upper = sql_stripped.upper()

        if "LIMIT" not in sql_upper:
            sql_stripped = sql_stripped.rstrip(";")
            return sql_stripped + f" LIMIT {MAX_RESULTS}"
        return sql_stripped

    def execute(self, sql_query: str) -> list[dict]:
        """Execute SQL query and return results as list of dicts. No tracing - caller handles this."""
        sql_query = self._apply_limit(sql_query)

        try:
            with self.engine.connect() as connection:
                result = connection.execute(text(sql_query))
                rows = result.fetchall()

                if not rows:
                    return []

                columns = result.keys()
                results = [dict(zip(columns, row)) for row in rows]
                return results

        except Exception as e:
            logger.error("Query execution error: %s | SQL: %s", str(e), sql_query)
            raise

    def execute_with_session(self, sql_query: str, session: Session) -> list[dict]:
        """Execute query using provided session. No tracing - caller handles this."""
        sql_query = self._apply_limit(sql_query)

        try:
            result = session.execute(text(sql_query))
            rows = result.fetchall()

            if not rows:
                return []

            columns = result.keys()
            results = [dict(zip(columns, row)) for row in rows]
            return results

        except Exception as e:
            logger.error("Query execution error: %s | SQL: %s", str(e), sql_query)
            raise
