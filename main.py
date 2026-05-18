#!/usr/bin/env python3
import os
import json
from dotenv import load_dotenv
from src.database.connection import get_engine, init_db
from src.database.seed import seed_database
from src.agent.graph import create_qa_agent
from sqlalchemy.orm import Session
from src.tracing import get_tracer

load_dotenv()


def main():
    db_url = os.getenv("DATABASE_URL", "sqlite:///university.db")
    api_key = os.getenv("GEMINI_API_KEY", "mock-key-for-testing")
    force_reseed = os.getenv("FORCE_RESEED", "false").lower() == "true"

    engine = get_engine(db_url)
    init_db(engine)

    with Session(engine) as session:
        seed_database(session, force_reseed=force_reseed)

        agent = create_qa_agent(engine, api_key=api_key)
        run_queries(agent)




def run_queries(agent):
    """Run test queries and display results."""
    test_questions = [
        # Simple aggregation
        "How many teachers are in the Computer Science department?",

        # Aggregation - total count
        # "How many students are enrolled in total?",
    ]

    results = []
    for i, question in enumerate(test_questions, 1):
        result = agent.query(question, trace_id=f"query-{i:03d}",
                           session_id="demo-session", verbose=True)
        results.append({
            "query": i,
            "question": question,
            "answer": result["answer"],
            "trace": result["trace"]
        })

        tracer = get_tracer()
        print(tracer.format_trace_summary())
        print()

    print("Full Results (JSON):")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
