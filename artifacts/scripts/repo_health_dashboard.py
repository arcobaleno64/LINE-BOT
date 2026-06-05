#!/usr/bin/env python3
"""Repo health dashboard — scans artifacts/ and produces a summary report."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAIPEI = timezone(timedelta(hours=8))

ARTIFACT_TYPES = ("task", "research", "plan", "code", "verify", "status", "decision", "improvement")

DONE_STATES = {"done", "closed"}
BLOCKED_STATES = {"blocked"}
STALE_DAYS = 14


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repo health dashboard")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--stale-days", type=int, default=STALE_DAYS, help="Days before a task is considered stale")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown")
    return parser.parse_args()


def load_status(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_task_id(path: Path) -> str:
    return path.stem.replace(".status", "")


def get_state(status: dict) -> str:
    return (status.get("state") or status.get("current_state") or "unknown").lower()


def get_owner(status: dict) -> str:
    return status.get("current_owner") or status.get("owner") or "unknown"


def get_last_updated(status: dict) -> str:
    return status.get("last_updated", "")


def parse_datetime(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


ARTIFACT_DIRS = {
    "task": "tasks",
    "research": "research",
    "plan": "plans",
    "code": "code",
    "verify": "verify",
    "status": "status",
    "decision": "decisions",
    "improvement": "improvement",
}


def discover_artifacts(root: Path, task_id: str) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for atype in ARTIFACT_TYPES:
        dirname = ARTIFACT_DIRS[atype]
        if atype == "status":
            pattern = f"{task_id}.status.json"
        else:
            pattern = f"{task_id}.{atype}.md"
        folder = root / "artifacts" / dirname
        result[atype] = (folder / pattern).exists()
    return result


def get_missing_artifacts(status: dict) -> list[str]:
    missing = status.get("missing_artifacts", [])
    if missing:
        return missing
    artifacts_map = status.get("artifacts", {})
    if isinstance(artifacts_map, dict):
        return [k for k, v in artifacts_map.items() if v is None]
    return []


def build_dashboard(root: Path, stale_days: int) -> dict:
    status_dir = root / "artifacts" / "status"
    now = datetime.now(TAIPEI)
    stale_cutoff = now - timedelta(days=stale_days)

    tasks: list[dict] = []
    total = 0
    done_count = 0
    blocked_count = 0
    stale_count = 0
    missing_verify_count = 0
    artifact_coverage: dict[str, int] = {t: 0 for t in ARTIFACT_TYPES}
    artifact_total: dict[str, int] = {t: 0 for t in ARTIFACT_TYPES}

    for status_path in sorted(status_dir.glob("TASK-*.status.json")):
        task_id = get_task_id(status_path)
        status = load_status(status_path)
        state = get_state(status)
        owner = get_owner(status)
        last_updated_str = get_last_updated(status)
        last_updated_dt = parse_datetime(last_updated_str)

        is_done = state in DONE_STATES
        is_blocked = state in BLOCKED_STATES
        is_stale = False
        if last_updated_dt and not is_done:
            is_stale = last_updated_dt < stale_cutoff

        artifacts = discover_artifacts(root, task_id)
        has_code = artifacts.get("code", False)
        has_verify = artifacts.get("verify", False)
        missing_verify = has_code and not has_verify and not is_done

        total += 1
        if is_done:
            done_count += 1
        if is_blocked:
            blocked_count += 1
        if is_stale:
            stale_count += 1
        if missing_verify:
            missing_verify_count += 1

        for atype in ARTIFACT_TYPES:
            artifact_total[atype] += 1
            if artifacts.get(atype, False):
                artifact_coverage[atype] += 1

        blocked_reason = status.get("blocked_reason", "")
        blockers = status.get("blockers", [])

        tasks.append({
            "task_id": task_id,
            "state": state,
            "owner": owner,
            "last_updated": last_updated_str,
            "is_stale": is_stale,
            "is_blocked": is_blocked,
            "missing_verify": missing_verify,
            "artifacts": artifacts,
            "blocked_reason": blocked_reason or ("; ".join(blockers) if blockers else ""),
        })

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": {
            "total_tasks": total,
            "done": done_count,
            "blocked": blocked_count,
            "stale": stale_count,
            "missing_verify": missing_verify_count,
            "completion_pct": round(done_count / total * 100, 1) if total else 0,
        },
        "artifact_coverage": {
            atype: {
                "present": artifact_coverage[atype],
                "total": artifact_total[atype],
                "pct": round(artifact_coverage[atype] / artifact_total[atype] * 100, 1) if artifact_total[atype] else 0,
            }
            for atype in ARTIFACT_TYPES
        },
        "tasks": tasks,
    }


def render_markdown(dashboard: dict) -> str:
    lines: list[str] = []
    s = dashboard["summary"]
    lines.append("# Repo Health Dashboard\n")
    lines.append(f"Generated: {dashboard['generated_at']}\n")

    lines.append("## Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Total Tasks | {s['total_tasks']} |")
    lines.append(f"| Done | {s['done']} ({s['completion_pct']}%) |")
    lines.append(f"| Blocked | {s['blocked']} |")
    lines.append(f"| Stale (>{dashboard.get('stale_days', STALE_DAYS)}d) | {s['stale']} |")
    lines.append(f"| Missing Verify (has code) | {s['missing_verify']} |")
    lines.append("")

    lines.append("## Artifact Coverage\n")
    lines.append("| Type | Present | Total | Coverage |")
    lines.append("|---|---:|---:|---:|")
    for atype, info in dashboard["artifact_coverage"].items():
        lines.append(f"| {atype} | {info['present']} | {info['total']} | {info['pct']}% |")
    lines.append("")

    blocked = [t for t in dashboard["tasks"] if t["is_blocked"]]
    if blocked:
        lines.append("## Blocked Tasks\n")
        lines.append("| Task | Owner | Reason | Last Updated |")
        lines.append("|---|---|---|---|")
        for t in blocked:
            lines.append(f"| {t['task_id']} | {t['owner']} | {t['blocked_reason'][:60]} | {t['last_updated'][:19]} |")
        lines.append("")

    stale = [t for t in dashboard["tasks"] if t["is_stale"]]
    if stale:
        lines.append("## Stale Tasks\n")
        lines.append("| Task | State | Owner | Last Updated |")
        lines.append("|---|---|---|---|")
        for t in stale:
            lines.append(f"| {t['task_id']} | {t['state']} | {t['owner']} | {t['last_updated'][:19]} |")
        lines.append("")

    missing_v = [t for t in dashboard["tasks"] if t["missing_verify"]]
    if missing_v:
        lines.append("## Missing Verification (has code artifact)\n")
        lines.append("| Task | State | Owner |")
        lines.append("|---|---|---|")
        for t in missing_v:
            lines.append(f"| {t['task_id']} | {t['state']} | {t['owner']} |")
        lines.append("")

    lines.append("## All Tasks\n")
    lines.append("| Task | State | Owner | Last Updated | Artifacts |")
    lines.append("|---|---|---|---|---|")
    for t in dashboard["tasks"]:
        present = [a for a, v in t["artifacts"].items() if v]
        state_upper = str(t["state"]).upper()
        flags: list[str] = []
        if t["is_blocked"] and state_upper != "BLOCKED":
            flags.append("BLOCKED")
        if t["is_stale"] and state_upper != "STALE":
            flags.append("STALE")
        if t["missing_verify"] and state_upper != "NO-VERIFY":
            flags.append("NO-VERIFY")
        suffix = f" {' '.join(flags)}" if flags else ""
        artifact_str = ", ".join(present)
        lines.append(f"| {t['task_id']} | {t['state']}{suffix} | {t['owner']} | {t['last_updated'][:19]} | {artifact_str} |")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    dashboard = build_dashboard(root, args.stale_days)
    dashboard["stale_days"] = args.stale_days

    if args.json:
        print(json.dumps(dashboard, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(dashboard))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
