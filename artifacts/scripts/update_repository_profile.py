#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from workflow_constants import REQUIRED_TOPICS, TOPIC_PATTERN


def parse_topics(raw: str) -> List[str]:
    topics: List[str] = []
    for token in raw.split(","):
        value = token.strip().lower()
        if not value:
            continue
        if value not in topics:
            topics.append(value)
    return topics


def normalize_topics(topics: List[str]) -> List[str]:
    normalized: List[str] = []
    for topic in topics:
        value = str(topic).strip().lower()
        if not value:
            continue
        if value in normalized:
            continue
        if not TOPIC_PATTERN.match(value):
            raise ValueError(f"Invalid topic '{topic}'. Topics must be lowercase-kebab-case.")
        normalized.append(value)
    for required in REQUIRED_TOPICS:
        if required not in normalized:
            normalized.append(required)
    if len(normalized) < 6 or len(normalized) > 12:
        raise ValueError(f"Topics must contain 6-12 entries after normalization, got {len(normalized)}")
    return normalized


def update_profile(profile_path: Path, project_name: str, project_summary: str, topics_arg: str | None) -> None:
    profile = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    existing_topics = profile.get("topics", []) if isinstance(profile.get("topics", []), list) else []
    topics = parse_topics(topics_arg) if topics_arg else [str(item) for item in existing_topics]
    topics = normalize_topics(topics)

    about = f"{project_name.strip()} - {project_summary.strip()}"
    about_len = len(about)
    if about_len < 80 or about_len > 200:
        raise ValueError(
            f"Generated 'about' must be 80-200 chars, got {about_len}. "
            "Adjust --project-summary length to satisfy repository profile guard."
        )

    profile["about"] = about
    profile["topics"] = topics

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update .github/repository-profile.json for About/topics bootstrap.")
    parser.add_argument("--project-name", required=True, help="Project name used in repository about.")
    parser.add_argument("--project-summary", required=True, help="One-line project summary used in repository about.")
    parser.add_argument("--topics", help="Optional comma-separated topics. Required topics are auto-appended if missing.")
    parser.add_argument("--profile-path", default=".github/repository-profile.json", help="Target repository profile path.")
    args = parser.parse_args()

    update_profile(Path(args.profile_path), args.project_name, args.project_summary, args.topics)
    print(f"[OK] Updated repository profile: {args.profile_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
