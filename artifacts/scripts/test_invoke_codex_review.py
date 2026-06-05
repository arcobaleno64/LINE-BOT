from __future__ import annotations

from pathlib import Path


WRAPPER = Path(__file__).resolve().parent / "Invoke-CodexReview.ps1"


def _models_from_calls(calls: list[dict]) -> list[str]:
    models = []
    for call in calls:
        args = call["args"]
        models.append(args[args.index("-m") + 1])
    return models


def test_dry_run_does_not_call_codex_or_write_reviews(fake_codex_exe, run_wrapper, tmp_repo):
    result = run_wrapper(
        WRAPPER,
        "-DryRun",
        "-DiffSource",
        "unstaged",
        env=fake_codex_exe.env(),
    )
    assert result.returncode == 0, result.combined_output
    assert "[DRY-RUN]" in result.stdout
    assert fake_codex_exe.calls() == []
    assert not (tmp_repo / "artifacts" / "reviews").exists()


def test_default_council_models_dispatch_in_order(fake_codex_exe, run_wrapper):
    fake_codex_exe.configure(stdout="__REVIEW__", exit_code=0)
    result = run_wrapper(
        WRAPPER,
        "-DiffSource",
        "unstaged",
        env=fake_codex_exe.env(),
    )
    assert result.returncode == 0, result.combined_output
    models = _models_from_calls(fake_codex_exe.calls())
    grouped = [model for index, model in enumerate(models) if index == 0 or model != models[index - 1]]
    assert grouped == ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"]


def test_review_outputs_include_current_frontmatter_fields(fake_codex_exe, run_wrapper, tmp_repo):
    fake_codex_exe.configure(stdout="__REVIEW_BODY__", exit_code=0)
    result = run_wrapper(
        WRAPPER,
        "-DiffSource",
        "unstaged",
        env=fake_codex_exe.env(),
    )
    assert result.returncode == 0, result.combined_output
    review_files = sorted((tmp_repo / "artifacts" / "reviews").glob("*.md"))
    assert len(review_files) == 3
    for review_file in review_files:
        text = review_file.read_text(encoding="utf-8").lstrip("\ufeff")
        assert text.startswith("---\n")
        for field in ("model:", "effort:", "diff_source:", "commit_anchor:", "generated_at:", "exit_code:"):
            assert field in text


def test_suppress_size_warn_switch_accepted(fake_codex_exe, run_wrapper):
    """TASK-1067: -SuppressSizeWarn switch must parse without error in review wrapper.
    Smoke test only; real bounds (100000 / 200000) require fake large diff, deferred."""
    result = run_wrapper(
        WRAPPER,
        "-DryRun",
        "-DiffSource",
        "unstaged",
        "-SuppressSizeWarn",
        env=fake_codex_exe.env(),
    )
    assert result.returncode == 0, result.combined_output
    assert "[DRY-RUN]" in result.stdout
