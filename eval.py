#!/usr/bin/env python3
"""CLI evaluator for the golden test set."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from src.agent import run_qa

GOLDEN = [
    {
        "question": "Why does order cancellation silently fail?",
        "expected_symbol": "cancel_order",
        "expect_not_found": False,
    },
    {
        "question": "How is the late fee calculated?",
        "expected_symbol": "calc_lf",
        "expect_not_found": False,
    },
    {
        "question": "What is the refund policy?",
        "expected_symbol": None,
        "expect_not_found": True,
    },
]


def main():
    parser = argparse.ArgumentParser(description="Run golden eval set")
    parser.add_argument("--repo", default="../acc-ai-hackathon/sample")
    parser.add_argument("--model", default="claude-opus-4-8")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    total_score = 0
    print(f"\nRunning eval on repo: {args.repo}  model: {args.model}\n")
    print("-" * 70)

    for i, entry in enumerate(GOLDEN, 1):
        print(f"[{i}] {entry['question']}")
        result = run_qa(entry["question"], args.repo, model=args.model)
        answer = result["answer"]
        chunks = result["retrieved_chunks"]

        if entry["expect_not_found"]:
            answer_ok = "not found" in answer.lower() or "cannot answer" in answer.lower()
            citation_ok = True  # no citation expected
        else:
            answer_ok = bool(answer) and "not found" not in answer.lower()
            citation_ok = (
                any(entry["expected_symbol"] in c.symbol for c in chunks)
                if entry["expected_symbol"]
                else True
            )

        score = int(answer_ok) + int(citation_ok)
        total_score += score
        print(f"    Answer  {'PASS' if answer_ok else 'FAIL'}  |  Citation  {'PASS' if citation_ok else 'FAIL'}  |  score {score}/2")
        print(f"    Answer: {answer[:120]}{'…' if len(answer) > 120 else ''}")
        if chunks:
            print(f"    Sources: {', '.join(f'{c.file_path}:{c.start_line}' for c in chunks[:3])}")
        print()

    print("-" * 70)
    print(f"TOTAL: {total_score} / 6")


if __name__ == "__main__":
    main()
