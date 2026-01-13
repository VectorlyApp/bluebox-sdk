#!/usr/bin/env python3
"""
Script to run benchmark tests against generated routines.

This script:
1. Loads a test config file with task, ground truth routine, and test definitions
2. Optionally runs the routine discovery pipeline using WebHacker
3. Runs deterministic and LLM tests comparing generated vs ground truth routines
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from openai import OpenAI

from web_hacker.data_models.benchmarks import (
    DeterministicTest,
    LLMTest,
    LLMTestResult,
    RoutineDiscoveryEvaluation,
)
from web_hacker.data_models.routine.routine import Routine
from web_hacker.sdk import WebHacker


def load_test_config(config_path: str) -> dict:
    """Load a test configuration file."""
    with open(config_path, "r") as f:
        return json.load(f)


def run_routine_discovery(
    task: str,
    cdp_captures_dir: str,
    output_dir: str | None = None,
    llm_model: str = "gpt-5",
    verbose: bool = False
) -> dict | None:
    """
    Run the WebHacker routine discovery pipeline.

    Args:
        task: The task description for the routine
        cdp_captures_dir: Path to the directory containing CDP captures
        output_dir: Path to the output directory (optional, uses temp dir if not provided)
        llm_model: The LLM model to use for discovery
        verbose: Whether to print detailed progress

    Returns:
        The discovered routine as a dict, or None if discovery failed
    """
    if verbose:
        print(f"\nRunning routine discovery...")
        print(f"  Task: {task}")
        print(f"  CDP captures: {cdp_captures_dir}")
        print(f"  LLM model: {llm_model}")

    # Use temp dir if no output dir provided
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="benchmark_discovery_")

    if verbose:
        print(f"  Output dir: {output_dir}")

    start_time = time.time()

    try:
        hacker = WebHacker(llm_model=llm_model)
        result = hacker.discover_routine(
            task=task,
            cdp_captures_dir=cdp_captures_dir,
            output_dir=output_dir,
        )

        elapsed = time.time() - start_time

        if verbose:
            print(f"  Discovery completed in {elapsed:.1f}s")

        if result and result.routine:
            return result.routine.model_dump()
        else:
            if verbose:
                print("  Warning: Discovery returned no routine")
            return None

    except Exception as e:
        elapsed = time.time() - start_time
        if verbose:
            print(f"  Discovery failed after {elapsed:.1f}s: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Run benchmark tests against routines"
    )
    parser.add_argument(
        "config_path",
        help="Path to the test config JSON file"
    )
    parser.add_argument(
        "--generated-routine",
        help="Path to a generated routine JSON file (optional, defaults to using ground truth)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed test results"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--run-llm-tests",
        action="store_true",
        help="Run LLM-based tests (requires OpenAI API key)"
    )
    parser.add_argument(
        "--cdp-captures-dir",
        help="Path to CDP captures directory to run routine discovery"
    )
    parser.add_argument(
        "--output-dir",
        help="Path to output directory for discovery results (optional, uses temp dir if not provided)"
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-5",
        help="LLM model to use for routine discovery (default: gpt-5)"
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip routine discovery even if cdp-captures-dir is provided"
    )
    parser.add_argument(
        "--results-file",
        help="Path to save the full evaluation results as JSON"
    )

    args = parser.parse_args()

    # Load the test config
    config = load_test_config(args.config_path)

    # Create the evaluation object upfront
    evaluation = RoutineDiscoveryEvaluation(
        name=config.get("name", "Unknown"),
        description=config.get("description", ""),
        task=config.get("task", ""),
        ground_truth_routine=Routine.model_validate(config.get("ground_truth_routine", {})),
        deterministic_tests=[DeterministicTest.model_validate(t) for t in config.get("deterministic_tests", [])],
        llm_tests=[LLMTest.model_validate(t) for t in config.get("llm_tests", [])],
    )

    # Determine the generated routine
    generated = None

    # Option 1: Run routine discovery if CDP captures provided and not skipped
    if args.cdp_captures_dir and not args.skip_discovery:
        if not args.json:
            print(f"\n{'='*60}")
            print("Routine Discovery")
            print(f"{'='*60}")

        start_time = time.time()
        try:
            generated = run_routine_discovery(
                task=evaluation.task,
                cdp_captures_dir=args.cdp_captures_dir,
                output_dir=args.output_dir,
                llm_model=args.llm_model,
                verbose=not args.json
            )
            evaluation.discovery_duration = time.time() - start_time
            if generated is None:
                evaluation.error = "Discovery returned no routine"
        except Exception as e:
            evaluation.discovery_duration = time.time() - start_time
            evaluation.error = str(e)
            if not args.json:
                print(f"  Error: {evaluation.error}")

    # Option 2: Load from provided generated routine file
    elif args.generated_routine:
        with open(args.generated_routine, "r") as f:
            generated = json.load(f)

    # Option 3: Fall back to ground truth (for testing the test framework itself)
    else:
        generated = config.get("ground_truth_routine", {}).copy()
        if not args.json:
            print("\nNote: Using ground truth as generated routine (no discovery or generated routine provided)")

    # Update evaluation with generated routine
    if generated:
        evaluation.generated_routine = Routine.model_validate(generated)

    # Build the data object that tests will evaluate against
    data = {
        "ground_truth_routine": evaluation.ground_truth_routine.model_dump(),
        "generated_routine": generated,
        "task": evaluation.task
    }

    # If discovery failed and we have no generated routine, we can't run tests
    if generated is None:
        evaluation.summary = evaluation.summarize_results()
        if args.results_file:
            with open(args.results_file, "w") as f:
                json.dump(evaluation.model_dump(), f, indent=2)
        if args.json:
            print(evaluation.model_dump_json(indent=2))
        else:
            print(f"\nError: Cannot run tests - routine discovery failed: {evaluation.error}")
        sys.exit(1)

    if not args.json:
        print(f"\nRunning benchmark: {evaluation.name}")
        print(f"Description: {evaluation.description}")
        print(f"\n{'='*60}")
        print("Deterministic Tests:")
        print(f"{'='*60}")

    # Run deterministic tests using evaluation object
    det_passed = 0
    for test in evaluation.deterministic_tests:
        result = test.run(data)
        if result:
            det_passed += 1
        if args.verbose or not args.json:
            status = "✓" if result else "✗"
            print(f"  {status} {test.name}")
            if not result:
                print(f"    Expression: {test.expression.stringify()}")

    det_total = len(evaluation.deterministic_tests)

    # Run LLM tests if requested
    llm_passed, llm_total = 0, 0
    if args.run_llm_tests and evaluation.llm_tests:
        if not args.json:
            print(f"\n{'='*60}")
            print("LLM Tests:")
            print(f"{'='*60}")

        client = OpenAI()
        for test in evaluation.llm_tests:
            # Build the full prompt with routine dumps and scoring instructions
            ground_truth_dump = json.dumps(evaluation.ground_truth_routine.model_dump(), indent=2)
            generated_dump = json.dumps(evaluation.generated_routine.model_dump(), indent=2) if evaluation.generated_routine else "null"

            full_prompt = (
                f"{test.prompt}\n\n"
                f"Task: {evaluation.task}\n\n"
                f"Ground Truth Routine:\n{ground_truth_dump}\n\n"
                f"Generated Routine:\n{generated_dump}\n\n"
                f"Provide a score between {test.score_range[0]} and {test.score_range[1]}.\n"
                f"Respond with JSON in this exact format:\n"
                f'{{"score": <number>, "rationale": "<explanation>"}}'
            )

            # Run the LLM evaluation
            response = client.responses.parse(
                model=test.model,
                input=[{"role": "user", "content": full_prompt}],
                text_format=LLMTestResult
            )
            result = response.output_parsed
            test.results.append(result)

            test_passed = result.passed(test.passing_threshold)
            if test_passed:
                llm_passed += 1
            llm_total += 1

            if args.verbose or not args.json:
                status = "✓" if test_passed else "✗"
                print(f"  {status} {test.name}: {result.score:.2f} (threshold: {test.passing_threshold})")
                if result.rationale:
                    print(f"    Rationale: {result.rationale[:100]}...")

    # Generate summary
    evaluation.summary = evaluation.summarize_results()

    # Save results file if requested
    if args.results_file:
        with open(args.results_file, "w") as f:
            json.dump(evaluation.model_dump(), f, indent=2)
        if not args.json:
            print(f"\nResults saved to: {args.results_file}")

    if args.json:
        print(evaluation.model_dump_json(indent=2))
    else:
        print(f"\n{'='*60}")
        print("Summary:")
        print(f"{'='*60}")
        if det_total > 0:
            print(f"Deterministic: {det_passed}/{det_total} passed ({100*det_passed/det_total:.1f}%)")
        else:
            print("Deterministic: No tests to run")

        if args.run_llm_tests and llm_total > 0:
            print(f"LLM Tests: {llm_passed}/{llm_total} passed ({100*llm_passed/llm_total:.1f}%)")
        elif args.run_llm_tests:
            print("LLM Tests: No tests to run")

        total_passed = det_passed + llm_passed
        total_tests = det_total + llm_total
        if total_tests > 0:
            print(f"\nTotal: {total_passed}/{total_tests} passed ({100*total_passed/total_tests:.1f}%)")
        print(f"{'='*60}\n")

        # Exit with non-zero code if any tests failed
        if total_passed < total_tests:
            sys.exit(1)


if __name__ == "__main__":
    main()
