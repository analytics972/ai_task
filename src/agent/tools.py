"""Database tools for schema discovery, SQL validation, and query execution."""
import json
import logging
import sqlglot
from .schema import SchemaManager
from .executor import QueryExecutor
from sqlalchemy import Engine

logger = logging.getLogger(__name__)


class DatabaseTools:
    """Tools for database operations with SQL injection protection."""

    def __init__(self, engine: Engine):
        self.schema_manager = SchemaManager(engine)
        self.executor = QueryExecutor(engine)

    def get_schema(self) -> str:
        """Get the database schema. Cached for performance."""
        return self.schema_manager.get_schema_info()

    def query_database(self, sql: str) -> str:
        """Execute SQL query and return results as JSON string."""
        try:
            results = self.executor.execute(sql)
            return json.dumps(results)
        except Exception as e:
            logger.error("Query failed: %s", str(e))
            return json.dumps({"error": "Query execution failed. Please rephrase your question."})

    def validate_sql_safety(self, sql: str) -> dict:
        """Validate SQL using AST parsing. Only SELECT and WITH allowed."""
        try:
            statements = sqlglot.parse(sql)
            if not statements:
                return {"valid": False, "error": "SQL query could not be parsed"}

            for stmt in statements:
                stmt_type = type(stmt).__name__

                if not isinstance(stmt, (sqlglot.expressions.Select, sqlglot.expressions.With)):
                    return {
                        "valid": False,
                        "error": f"Only SELECT and WITH queries allowed, found: {stmt_type}"
                    }

            return {"valid": True}

        except sqlglot.ParseError as e:
            return {"valid": False, "error": f"SQL syntax error: {str(e)}"}
        except Exception as e:
            logger.error("SQL validation error: %s", str(e))
            return {"valid": False, "error": "SQL validation failed"}

    def validate_sql_syntax(self, sql: str) -> dict:
        """Validate SQL syntax (delegates to validate_sql_safety with AST)."""
        return self.validate_sql_safety(sql)
