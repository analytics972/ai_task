from sqlalchemy import inspect, MetaData
from sqlalchemy.engine import Engine
from typing import Any
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError


class SchemaManager:
    """DB-agnostic schema manager. Extracts schema info from any SQLAlchemy-supported DB."""

    SCHEMA_REFLECTION_TIMEOUT = 10  # seconds

    def __init__(self, engine: Engine, cache_ttl: int = 300):
        self.engine = engine
        self.metadata = MetaData()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.metadata.reflect, bind=engine)
                future.result(timeout=self.SCHEMA_REFLECTION_TIMEOUT)
        except FutureTimeoutError:
            raise TimeoutError(f"Schema reflection timed out after {self.SCHEMA_REFLECTION_TIMEOUT}s. Database may be unreachable.")

        self._schema_cache: str | None = None
        self._cache_time: float = 0
        self._cache_ttl = cache_ttl

    def get_schema_info(self) -> str:
        """Return human-readable schema description. Results are cached for cache_ttl seconds."""
        now = time.time()
        if self._schema_cache and (now - self._cache_time) < self._cache_ttl:
            return self._schema_cache

        inspector = inspect(self.engine)
        schema_text = []

        for table_name in inspector.get_table_names():
            schema_text.append(f"\nTable: {table_name}")
            schema_text.append("-" * 40)

            columns = inspector.get_columns(table_name)
            for col in columns:
                col_type = str(col["type"])
                nullable = "NULL" if col["nullable"] else "NOT NULL"
                schema_text.append(f"  - {col['name']}: {col_type} {nullable}")

            foreign_keys = inspector.get_foreign_keys(table_name)
            if foreign_keys:
                schema_text.append("\n  Foreign Keys:")
                for fk in foreign_keys:
                    schema_text.append(
                        f"    {fk['constrained_columns']} -> "
                        f"{fk['referred_table']}.{fk['referred_columns']}"
                    )

        result = "\n".join(schema_text)
        self._schema_cache = result
        self._cache_time = time.time()
        return result

    def invalidate_cache(self):
        """Clear the schema cache. Call this if schema changes."""
        self._schema_cache = None
        self._cache_time = 0

    def get_tables(self) -> list[str]:
        """Get list of all table names."""
        inspector = inspect(self.engine)
        return inspector.get_table_names()

    def get_table_columns(self, table_name: str) -> list[str]:
        """Get column names for a table."""
        inspector = inspect(self.engine)
        columns = inspector.get_columns(table_name)
        return [col["name"] for col in columns]

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists."""
        inspector = inspect(self.engine)
        return table_name in inspector.get_table_names()
