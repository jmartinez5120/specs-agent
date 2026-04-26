#!/usr/bin/env python3
"""AI scenario generation benchmark + quality assessment.

Runs against the live Docker stack (API on localhost:8765).
Tests AI-generated test data across multiple real-world OpenAPI specs.

Usage:
    python tests/test_ai_scenarios.py

Requirements:
    - Docker stack running: docker compose up -d
    - AI enabled: SPECS_AGENT_AI_ENABLED=1

Reports:
    - Per-spec timing (total plan generation, AI fields vs Faker fields)
    - Quality assessment: are AI values contextually relevant?
    - Happy path vs sad path coverage
    - Comparison: AI-enhanced plan vs Faker-only plan
"""

import json
import sys
import time
from typing import Any
from urllib.request import Request, urlopen

API = "http://localhost:8765"

# ------------------------------------------------------------------ #
# Real-world OpenAPI specs to test against
# ------------------------------------------------------------------ #

SPECS = {
    "Petstore v3": "https://petstore3.swagger.io/api/v3/openapi.json",
    "httpbin": "https://httpbin.org/spec.json",
}

# Also test against localhost if available
LOCAL_SPECS = {
    "Local API (8080)": "http://localhost:8080/v3/api-docs",
}


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = Request(
        f"{API}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urlopen(req, timeout=300) as resp:
        text = resp.read()
        if not text or resp.status == 204:
            return {}
        return json.loads(text)


def load_spec(source: str) -> dict | None:
    try:
        result = api("POST", "/specs/load", {"source": source})
        return result
    except Exception as e:
        print(f"  ⚠ Failed to load {source}: {e}")
        return None


def generate_plan(raw_spec: dict, source: str) -> tuple[dict, float]:
    """Generate a plan and return (plan_dict, elapsed_seconds)."""
    start = time.time()
    result = api("POST", "/plans/generate", {
        "spec": {"raw_spec": raw_spec, "source": source}
    })
    elapsed = time.time() - start
    return result, elapsed


def generate_plan_no_ai(raw_spec: dict, source: str) -> tuple[dict, float]:
    """Generate with AI temporarily disabled."""
    # Save current config
    config = api("GET", "/config")
    was_enabled = config.get("ai_enabled", False)

    # Disable AI
    config["ai_enabled"] = False
    api("PUT", "/config", config)

    start = time.time()
    result = api("POST", "/plans/generate", {
        "spec": {"raw_spec": raw_spec, "source": source}
    })
    elapsed = time.time() - start

    # Restore
    config["ai_enabled"] = was_enabled
    api("PUT", "/config", config)

    return result, elapsed


# ------------------------------------------------------------------ #
# Analysis helpers
# ------------------------------------------------------------------ #


def is_faker_template(value: Any) -> bool:
    if isinstance(value, str):
        return "{{$" in value or "{{" in value
    return False


def count_faker_vs_concrete(body: Any) -> tuple[int, int]:
    """Count (faker_templates, concrete_values) in a body dict."""
    faker = 0
    concrete = 0
    if isinstance(body, dict):
        for v in body.values():
            if isinstance(v, dict):
                f, c = count_faker_vs_concrete(v)
                faker += f
                concrete += c
            elif is_faker_template(v):
                faker += 1
            elif v is not None:
                concrete += 1
    elif isinstance(body, list):
        for item in body:
            f, c = count_faker_vs_concrete(item)
            faker += f
            concrete += c
    return faker, concrete


def analyze_plan(plan: dict, label: str) -> dict:
    """Analyze a plan's test cases and return stats."""
    cases = plan.get("test_cases", [])
    total = len(cases)
    happy = [c for c in cases if c.get("test_type") == "happy"]
    sad = [c for c in cases if c.get("test_type") == "sad"]
    enabled = [c for c in cases if c.get("enabled")]

    total_faker = 0
    total_concrete = 0
    bodies_with_data = 0
    sample_bodies: list[dict] = []

    for c in cases:
        body = c.get("body")
        if body and isinstance(body, dict):
            bodies_with_data += 1
            f, co = count_faker_vs_concrete(body)
            total_faker += f
            total_concrete += co
            if len(sample_bodies) < 5:
                sample_bodies.append({
                    "name": c["name"],
                    "method": c["method"],
                    "body": body,
                })

    return {
        "label": label,
        "total_cases": total,
        "happy_path": len(happy),
        "sad_path": len(sad),
        "enabled": len(enabled),
        "bodies_with_data": bodies_with_data,
        "faker_fields": total_faker,
        "concrete_fields": total_concrete,
        "sample_bodies": sample_bodies,
    }


# ------------------------------------------------------------------ #
# Main test runner
# ------------------------------------------------------------------ #


def main():
    print("=" * 70)
    print("AI SCENARIO GENERATION — BENCHMARK + QUALITY ASSESSMENT")
    print("=" * 70)
    print()

    # Check stack health
    try:
        health = api("GET", "/health")
        print(f"✓ API: {health}")
    except Exception as e:
        print(f"✗ API unreachable: {e}")
        sys.exit(1)

    ai_status = api("GET", "/ai/status")
    print(f"✓ AI status: enabled={ai_status.get('enabled')}, "
          f"available={ai_status.get('available')}, "
          f"model={ai_status.get('model_path', 'none')}")
    print()

    # Clear AI cache for fresh benchmark
    cleared = api("POST", "/ai/cache/clear")
    print(f"✓ Cache cleared: {cleared}")
    print()

    all_specs = {}
    all_specs.update(SPECS)

    # Try local specs
    for name, url in LOCAL_SPECS.items():
        try:
            api("POST", "/specs/load", {"source": url})
            all_specs[name] = url
        except Exception:
            print(f"  ⓘ {name} not available, skipping")

    results: list[dict] = []

    for spec_name, spec_url in all_specs.items():
        print("-" * 70)
        print(f"SPEC: {spec_name}")
        print(f"  Source: {spec_url}")
        print()

        loaded = load_spec(spec_url)
        if not loaded:
            continue

        spec = loaded["spec"]
        endpoints = spec.get("endpoints", [])
        print(f"  Title: {spec['title']} v{spec['version']}")
        print(f"  Endpoints: {len(endpoints)}")
        print()

        raw_spec = spec["raw_spec"]

        # --- Faker-only plan ---
        print("  [1/2] Generating Faker-only plan...")
        faker_plan, faker_time = generate_plan_no_ai(raw_spec, spec_url)
        faker_stats = analyze_plan(faker_plan, f"{spec_name} (Faker)")
        print(f"       Time: {faker_time:.2f}s")
        print(f"       Cases: {faker_stats['total_cases']} "
              f"(happy: {faker_stats['happy_path']}, sad: {faker_stats['sad_path']})")
        print(f"       Bodies: {faker_stats['bodies_with_data']} "
              f"({faker_stats['faker_fields']} faker, {faker_stats['concrete_fields']} concrete)")
        print()

        # --- AI-enhanced plan ---
        print("  [2/2] Generating AI-enhanced plan...")
        ai_plan, ai_time = generate_plan(raw_spec, spec_url)
        ai_stats = analyze_plan(ai_plan, f"{spec_name} (AI)")
        print(f"       Time: {ai_time:.2f}s")
        print(f"       Cases: {ai_stats['total_cases']} "
              f"(happy: {ai_stats['happy_path']}, sad: {ai_stats['sad_path']})")
        print(f"       Bodies: {ai_stats['bodies_with_data']} "
              f"({ai_stats['faker_fields']} faker, {ai_stats['concrete_fields']} concrete)")
        print()

        # --- Comparison ---
        improvement = ai_stats['concrete_fields'] - faker_stats['concrete_fields']
        print(f"  COMPARISON:")
        print(f"    Speed: Faker {faker_time:.2f}s vs AI {ai_time:.2f}s "
              f"(+{ai_time - faker_time:.2f}s)")
        print(f"    Concrete fields: Faker {faker_stats['concrete_fields']} → "
              f"AI {ai_stats['concrete_fields']} "
              f"({'+'  if improvement >= 0 else ''}{improvement})")
        print()

        # --- Sample bodies side-by-side ---
        if ai_stats['sample_bodies']:
            print(f"  SAMPLE BODIES (AI-enhanced):")
            for sb in ai_stats['sample_bodies'][:3]:
                print(f"    {sb['name']}:")
                for k, v in sb['body'].items():
                    marker = "🤖" if not is_faker_template(v) and isinstance(v, str) and len(str(v)) > 3 else "🎲"
                    print(f"      {marker} {k}: {json.dumps(v)[:80]}")
            print()

        results.append({
            "spec_name": spec_name,
            "endpoints": len(endpoints),
            "faker_time": faker_time,
            "ai_time": ai_time,
            "faker_stats": faker_stats,
            "ai_stats": ai_stats,
        })

    # --- Second run (cache hit) ---
    if results:
        print("=" * 70)
        print("CACHE HIT BENCHMARK (second generation, all specs)")
        print("=" * 70)
        print()

        for r in results:
            spec_name = r["spec_name"]
            spec_url = all_specs[spec_name]
            loaded = load_spec(spec_url)
            if not loaded:
                continue

            start = time.time()
            api("POST", "/plans/generate", {
                "spec": {"raw_spec": loaded["spec"]["raw_spec"], "source": spec_url}
            })
            cached_time = time.time() - start
            print(f"  {spec_name}: {cached_time:.2f}s (was {r['ai_time']:.2f}s)")
            r["cached_time"] = cached_time

    # --- Final summary ---
    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print()
    print(f"{'Spec':<30} {'Endpoints':<10} {'Faker':<10} {'AI 1st':<10} {'AI cached':<10} {'Concrete +':<12}")
    print("-" * 82)
    for r in results:
        improvement = r['ai_stats']['concrete_fields'] - r['faker_stats']['concrete_fields']
        cached = r.get('cached_time', 0)
        print(f"{r['spec_name']:<30} {r['endpoints']:<10} "
              f"{r['faker_time']:<10.2f} {r['ai_time']:<10.2f} "
              f"{cached:<10.2f} {'+' + str(improvement) if improvement >= 0 else str(improvement):<12}")

    print()

    # AI cache stats
    cache_stats = api("GET", "/ai/status").get("cache", {})
    print(f"Cache: {cache_stats.get('entries', 0)} entries, "
          f"{cache_stats.get('size_bytes', 0) / 1024:.1f} KB")

    return results


if __name__ == "__main__":
    results = main()
