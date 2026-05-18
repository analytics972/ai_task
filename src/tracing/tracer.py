import json
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum


class EventType(str, Enum):
    """Event types matching graph nodes and actions."""
    VALIDATE_INPUT = "validate_input"
    GENERATE_SQL = "generate_sql"
    VALIDATE_SAFETY = "validate_safety"
    VALIDATE_SYNTAX = "validate_syntax"
    EXECUTE_QUERY = "execute_query"
    DECIDE_RETRY = "decide_retry"
    ERROR_REPORTER = "error_reporter"
    ERROR = "error"
    GRAPH_NODE = "graph_node"


@dataclass
class TraceEvent:
    timestamp: str
    event_type: EventType
    step_name: str
    duration_ms: float
    sequence: int  # Event number (1, 2, 3, ...)
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    error: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    model: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


class ExecutionTracer:
    def __init__(self, trace_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None):
        self.trace_id = trace_id
        self.session_id = session_id
        self.user_id = user_id
        self.events: list[TraceEvent] = []
        self.start_time = time.time()
        self.sequence_counter = 0

    def log_event(
        self,
        event_type: EventType,
        step_name: str,
        input_data: Optional[dict] = None,
        output_data: Optional[dict] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        if duration_ms is None:
            duration_ms = (time.time() - self.start_time) * 1000

        self.sequence_counter += 1
        event = TraceEvent(
            timestamp=timestamp,
            event_type=event_type,
            step_name=step_name,
            duration_ms=duration_ms,
            sequence=self.sequence_counter,
            input_data=input_data,
            output_data=output_data,
            error=error,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        self.events.append(event)

    def get_trace(self) -> dict:
        total_duration = (time.time() - self.start_time) * 1000
        total_input_tokens = sum(e.input_tokens or 0 for e in self.events)
        total_output_tokens = sum(e.output_tokens or 0 for e in self.events)

        trace = {
            "trace_id": self.trace_id,
            "total_duration_ms": total_duration,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "events": [event.to_dict() for event in self.events],
        }
        if self.session_id:
            trace["session_id"] = self.session_id
        if self.user_id:
            trace["user_id"] = self.user_id
        return trace

    def save_trace(self, filepath: str) -> None:
        trace = self.get_trace()
        with open(filepath, "w") as f:
            json.dump(trace, f, indent=2)

    def print_trace(self) -> None:
        trace = self.get_trace()
        print(f"\nTrace {trace['trace_id']}: {trace['total_duration_ms']:.0f}ms")
        print(f"Tokens - Input: {trace['total_input_tokens']}, Output: {trace['total_output_tokens']}")
        for i, event in enumerate(trace["events"], 1):
            print(f"  [{i}] {event['step_name']}: {event['duration_ms']:.0f}ms", end="")
            if event.get('input_tokens'):
                print(f" [Tokens: {event['input_tokens']}/{event.get('output_tokens', 0)}]", end="")
            if event["error"]:
                print(f" ERROR: {event['error']}", end="")
            print()

    def format_trace_summary(self) -> str:
        trace = self.get_trace()
        lines = []

        lines.append("Execution Path:")
        lines.append("  [0] START")
        for event in trace["events"]:
            seq = event.get("sequence", 0)
            step_name = event["step_name"]
            event_type = event["event_type"]

            if event_type == "error":
                lines.append(f"  [{seq}] ERROR: {step_name}")
                if event.get("error"):
                    error_msg = event["error"][:80]
                    lines.append(f"        {error_msg}...")
            else:
                lines.append(f"  [{seq}] {step_name}")

        lines.append(f"  [{len(trace['events']) + 1}] END")
        lines.append("")
        lines.append(f"query_id: {trace['trace_id']}")
        lines.append(f"duration_ms: {trace['total_duration_ms']:.0f}")
        lines.append(f"tokens_in: {trace['total_input_tokens']}")
        lines.append(f"tokens_out: {trace['total_output_tokens']}")
        lines.append(f"total_events: {len(trace['events'])}")

        return "\n".join(lines)


_thread_local = threading.local()


def get_tracer(trace_id: Optional[str] = None, session_id: Optional[str] = None,
               user_id: Optional[str] = None) -> ExecutionTracer:
    """Get or create tracer for current thread. Thread-safe for concurrent requests."""
    if not hasattr(_thread_local, 'tracer') or _thread_local.tracer is None:
        if trace_id is None:
            trace_id = datetime.now(timezone.utc).isoformat()
        _thread_local.tracer = ExecutionTracer(trace_id, session_id=session_id, user_id=user_id)
    return _thread_local.tracer


def reset_tracer() -> None:
    """Reset tracer for current thread. Call at start of each request."""
    if hasattr(_thread_local, 'tracer'):
        _thread_local.tracer = None
