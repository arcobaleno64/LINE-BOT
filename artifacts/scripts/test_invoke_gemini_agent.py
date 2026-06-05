from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


WRAPPER = Path(__file__).resolve().parent / "Invoke-GeminiAgent.ps1"


def _build_lifecycle_inspector_exe(tmp_path: Path, command_name: str) -> tuple[Path, str]:
    directory = tmp_path / f"inspector-{command_name}"
    directory.mkdir()
    script_path = directory / f"{command_name}_inspector.py"
    marker_name = f"{command_name}_lifecycle_marker.txt"
    script_path.write_text(
        textwrap.dedent(f"""
        from __future__ import annotations
        import sys
        from pathlib import Path
        cwd = Path.cwd()
        task_path = cwd / "artifacts" / "tasks" / "TASK-fake.task.md"
        plan_path = cwd / "artifacts" / "plans" / "TASK-fake.plan.md"
        marker = cwd / "{marker_name}"
        lines = [
            f"task_visible={{int(task_path.exists())}}",
            f"plan_visible={{int(plan_path.exists())}}",
        ]
        marker.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
        sys.exit(0)
        """).strip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        exe_path = directory / f"{command_name}.cmd"
        exe_path.write_text(
            f'@echo off\r\n"{sys.executable}" "{script_path}" %*\r\nexit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
        )
    else:
        exe_path = directory / command_name
        exe_path.write_text(
            f'#!/usr/bin/env sh\nexec "{sys.executable}" "{script_path}" "$@"\n',
            encoding="utf-8",
        )
        exe_path.chmod(0o755)
    return exe_path, marker_name


def _seed_lifecycle_artifacts(repo: Path) -> None:
    (repo / "artifacts" / "tasks").mkdir(parents=True, exist_ok=True)
    (repo / "artifacts" / "plans").mkdir(parents=True, exist_ok=True)
    (repo / "artifacts" / "tasks" / "TASK-fake.task.md").write_text("fake task\n", encoding="utf-8")
    (repo / "artifacts" / "plans" / "TASK-fake.plan.md").write_text("fake plan\n", encoding="utf-8")


def _models_from_calls(calls: list[dict]) -> list[str]:
    models = []
    for call in calls:
        args = call["args"]
        models.append(args[args.index("-m") + 1])
    return models


def test_default_model_is_flash_lite(fake_gemini_exe, run_wrapper):
    fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
    result = run_wrapper(
        WRAPPER,
        "-Prompt",
        "hello",
        "-Executable",
        fake_gemini_exe.path,
        "-MaxRetriesPerTier",
        "0",
        "-BaseBackoffSeconds",
        "0",
    )
    assert result.returncode == 0, result.combined_output
    assert _models_from_calls(fake_gemini_exe.calls()) == ["gemini-3.1-flash-lite-preview"]


def test_flash_lite_capacity_failure_falls_back_to_flash_preview(fake_gemini_exe, run_wrapper):
    fake_gemini_exe.configure(
        stdout="__OK__",
        exit_code=0,
        sequence=[
            {"stdout": "429 MODEL_CAPACITY_EXHAUSTED", "exit_code": 1},
            {"stdout": "429 MODEL_CAPACITY_EXHAUSTED", "exit_code": 1},
            {"stdout": "429 MODEL_CAPACITY_EXHAUSTED", "exit_code": 1},
        ],
    )
    result = run_wrapper(
        WRAPPER,
        "-Prompt",
        "hello",
        "-Executable",
        fake_gemini_exe.path,
        "-MaxRetriesPerTier",
        "2",
        "-BaseBackoffSeconds",
        "0",
    )
    assert result.returncode == 0, result.combined_output
    models = _models_from_calls(fake_gemini_exe.calls())
    assert models[:3] == ["gemini-3.1-flash-lite-preview"] * 3
    assert models[3] == "gemini-3-flash-preview"


def test_auto_fallback_models_array_includes_pro(fake_gemini_exe, run_wrapper):
    text = WRAPPER.read_text(encoding="utf-8")
    models_block = text.split("$Models = @(", 1)[1].split(")", 1)[0]
    assert "gemini-3.1-pro-preview" in models_block

    fake_gemini_exe.configure(stdout="429 MODEL_CAPACITY_EXHAUSTED", exit_code=1)
    result = run_wrapper(
        WRAPPER,
        "-Prompt",
        "hello",
        "-Executable",
        fake_gemini_exe.path,
        "-MaxRetriesPerTier",
        "0",
        "-BaseBackoffSeconds",
        "0",
    )
    assert result.returncode == 1
    assert "gemini-3.1-pro-preview" in _models_from_calls(fake_gemini_exe.calls())


# region TASK-1060: lifecycle exclusion in pre-dispatch stash baseline


class TestGeminiLifecycleExclusion:
    def test_default_exclude_keeps_lifecycle_visible_during_dispatch(self, tmp_path, tmp_repo, run_wrapper):
        _seed_lifecycle_artifacts(tmp_repo)
        exe_path, marker_name = _build_lifecycle_inspector_exe(tmp_path, "gemini")
        result = run_wrapper(
            WRAPPER,
            "-Prompt", "hello",
            "-Executable", str(exe_path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
            "-AllowedPaths", "out.research.md",
        )
        assert result.returncode == 0, result.combined_output
        marker_path = tmp_repo / marker_name
        assert marker_path.exists(), f"inspector marker missing; wrapper output:\n{result.combined_output}"
        marker_text = marker_path.read_text(encoding="utf-8")
        assert "task_visible=1" in marker_text, marker_text
        assert "plan_visible=1" in marker_text, marker_text
        assert "Pre-dispatch state stashed at" in result.combined_output

    def test_opt_in_include_stashes_lifecycle_during_dispatch(self, tmp_path, tmp_repo, run_wrapper):
        _seed_lifecycle_artifacts(tmp_repo)
        exe_path, marker_name = _build_lifecycle_inspector_exe(tmp_path, "gemini")
        result = run_wrapper(
            WRAPPER,
            "-Prompt", "hello",
            "-Executable", str(exe_path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
            "-AllowedPaths", "out.research.md",
            "-IncludeLifecycleInBaseline",
        )
        assert result.returncode == 0, result.combined_output
        marker_path = tmp_repo / marker_name
        assert marker_path.exists(), f"inspector marker missing; wrapper output:\n{result.combined_output}"
        marker_text = marker_path.read_text(encoding="utf-8")
        assert "task_visible=0" in marker_text, marker_text
        assert "plan_visible=0" in marker_text, marker_text
        assert "Pre-dispatch state stashed at" in result.combined_output

    def test_user_pre_existing_stash_not_misclaimed(self, tmp_path, tmp_repo, run_wrapper, fake_gemini_exe):
        subprocess.run(
            ["git", "stash", "push", "-u", "-m", "user-pre-existing"],
            cwd=tmp_repo, check=True, capture_output=True, text=True,
        )
        _seed_lifecycle_artifacts(tmp_repo)
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        result = run_wrapper(
            WRAPPER,
            "-Prompt", "hello",
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
            "-AllowedPaths", "out.research.md",
        )
        assert result.returncode == 0, result.combined_output
        assert "stash msg" in result.combined_output and "not found" in result.combined_output, result.combined_output
        list_result = subprocess.run(
            ["git", "stash", "list"],
            cwd=tmp_repo, capture_output=True, text=True, check=True,
        )
        assert "user-pre-existing" in list_result.stdout, list_result.stdout


# endregion TASK-1060


# region TASK-1062: Bug A (lifecycle untracked classification) + Bug B (stdin always)
# AC-3 dual-wrapper parity completed in TASK-1062 reopen pass; Option A scope
# shrinkage in artifacts/decisions/TASK-1062.decision.md superseded after the
# new gemini.cmd stdin-without-`-p` smoke test confirmed pure-stdin pipe is
# viable (gemini CLI reads stdin as the prompt; help-text "Defaults to
# interactive mode" reflects an empty-stdin default, not a hard requirement).


class TestGeminiBugAClassification:
    """TASK-1062 Bug A: lifecycle pre-existing untracked artifacts must not be
    misclassified as sub-agent writes when the post-dispatch guard runs."""

    def test_lifecycle_untracked_preserved_when_unchanged(self, tmp_path, tmp_repo, run_wrapper, fake_gemini_exe):
        # C-1 (Bug A reverse): seed pre-dispatch lifecycle untracked artifacts
        # outside AllowedPaths, dispatch with a fake exe that does not touch
        # them, and assert they survive post-dispatch (no false-positive
        # violation, no Restore-PostDispatchDelta deletion).
        _seed_lifecycle_artifacts(tmp_repo)
        (tmp_repo / "artifacts" / "status").mkdir(parents=True, exist_ok=True)
        status_path = tmp_repo / "artifacts" / "status" / "TASK-fake.status.json"
        status_path.write_text('{"task_id": "TASK-fake"}\n', encoding="utf-8")
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        result = run_wrapper(
            WRAPPER,
            "-Prompt", "hello",
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
            "-AllowedPaths", "artifacts/research/TASK-fake.research.md",
            "-AutoRestore",
        )
        assert result.returncode == 0, result.combined_output
        task_path = tmp_repo / "artifacts" / "tasks" / "TASK-fake.task.md"
        plan_path = tmp_repo / "artifacts" / "plans" / "TASK-fake.plan.md"
        assert task_path.exists(), f"task artifact deleted; output:\n{result.combined_output}"
        assert plan_path.exists(), f"plan artifact deleted; output:\n{result.combined_output}"
        assert status_path.exists(), f"status artifact deleted; output:\n{result.combined_output}"
        assert "Lifecycle pre-existing untracked (unchanged)" in result.combined_output

    def test_lifecycle_untracked_modified_by_subagent_is_restored(self, tmp_path, tmp_repo, run_wrapper):
        # C-2 (Bug A forward): sub-agent modifies a pre-dispatch lifecycle
        # untracked artifact outside AllowedPaths -> wrapper detects violation
        # and restores via git cat-file blob to pre-dispatch content.
        _seed_lifecycle_artifacts(tmp_repo)
        task_path = tmp_repo / "artifacts" / "tasks" / "TASK-fake.task.md"
        original_content = task_path.read_text(encoding="utf-8")

        # Build an inspector exe that mutates the lifecycle file during dispatch.
        directory = tmp_path / "mutator-gemini"
        directory.mkdir()
        script_path = directory / "gemini_mutator.py"
        script_path.write_text(
            textwrap.dedent("""
            from __future__ import annotations
            import sys
            from pathlib import Path
            cwd = Path.cwd()
            target = cwd / "artifacts" / "tasks" / "TASK-fake.task.md"
            target.write_text("MUTATED BY SUB-AGENT\\n", encoding="utf-8")
            sys.exit(0)
            """).strip(),
            encoding="utf-8",
        )
        if os.name == "nt":
            exe_path = directory / "gemini.cmd"
            exe_path.write_text(
                f'@echo off\r\n"{sys.executable}" "{script_path}" %*\r\nexit /b %ERRORLEVEL%\r\n',
                encoding="utf-8",
            )
        else:
            exe_path = directory / "gemini"
            exe_path.write_text(
                f'#!/usr/bin/env sh\nexec "{sys.executable}" "{script_path}" "$@"\n',
                encoding="utf-8",
            )
            exe_path.chmod(0o755)

        result = run_wrapper(
            WRAPPER,
            "-Prompt", "hello",
            "-Executable", str(exe_path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
            "-AllowedPaths", "artifacts/research/TASK-fake.research.md",
            "-AutoRestore",
        )
        # Wrapper exits 2 because the sub-agent wrote outside AllowedPaths.
        assert result.returncode == 2, result.combined_output
        assert task_path.exists(), "task artifact deleted instead of restored"
        assert task_path.read_text(encoding="utf-8") == original_content, (
            f"task artifact not restored to pre-dispatch content; got:\n{task_path.read_text(encoding='utf-8')}"
        )
        assert "Restored lifecycle untracked (pre-dispatch blob)" in result.combined_output


class TestGeminiBugBStdinAlways:
    """TASK-1062 Bug B (Gemini side, completing AC-3 dual-wrapper parity):
    wrapper always pipes prompt via stdin to avoid Windows cmd.exe batch-parser
    truncating multiline prompts at the first LF/CR. gemini CLI reads stdin as
    the prompt when no `-p` flag is present."""

    def test_multiline_prompt_under_threshold_is_piped_via_stdin(self, fake_gemini_exe, run_wrapper):
        # G-3 (Bug B reverse): 5000-char multiline prompt must arrive at the
        # sub-agent intact via stdin, not via -p arg (which previously caused
        # gemini.cmd to receive only the first line of multi-line prompts and
        # reply with a generic "I am ready" initialization message).
        body_lines = ["[ROLE]"] + ["payload line " + str(i).rjust(4, "0") for i in range(450)]
        prompt = "\n".join(body_lines)
        while len(prompt) < 5000:
            prompt += "\nfiller " + str(len(prompt))
        prompt = prompt[:5000]
        assert "\n" in prompt and len(prompt) == 5000

        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        result = run_wrapper(
            WRAPPER,
            "-Prompt", prompt,
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
        )
        assert result.returncode == 0, result.combined_output
        assert "(stdin_pipe=True, prompt_size=5000)" in result.combined_output
        calls = fake_gemini_exe.calls()
        assert calls, "fake exe was never called"
        last = calls[-1]
        # Prompt must NOT appear as an argv element (no -p $Prompt path).
        assert prompt not in last["args"], "prompt leaked into argv (cmdline truncation risk)"
        # Prompt MUST arrive via stdin, in full, with newlines intact.
        stdin_seen = last.get("stdin", "")
        assert prompt.rstrip("\n") in stdin_seen, (
            f"prompt not present in fake exe stdin (got {len(stdin_seen)} chars)"
        )
        assert stdin_seen.count("\n") >= 5, (
            f"newlines lost in stdin transport (got {stdin_seen.count(chr(10))})"
        )

    def test_short_single_line_prompt_still_dispatches(self, fake_gemini_exe, run_wrapper):
        # G-4 (Bug B regression smoke): short single-line prompt still works
        # under the always-stdin path; wrapper exit 0; stdin echo present.
        prompt = "x" * 100
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        result = run_wrapper(
            WRAPPER,
            "-Prompt", prompt,
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
        )
        assert result.returncode == 0, result.combined_output
        assert "(stdin_pipe=True, prompt_size=100)" in result.combined_output
        last = fake_gemini_exe.calls()[-1]
        assert prompt not in last["args"], "prompt leaked into argv"
        stdin_seen = last.get("stdin", "")
        assert prompt in stdin_seen, "prompt missing from stdin"


# endregion TASK-1062


class TestGeminiBoundsCheck:
    """TASK-1067: Gemini wrapper enforces prompt size bounds — warn @ 500,
    reject @ 5000. -SuppressSizeWarn opts out. Aligns with
    docs/dispatch_prompt_discipline.md 500-char threshold."""

    def test_prompt_under_warn_threshold_dispatches_silently(self, fake_gemini_exe, run_wrapper):
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        prompt = "x" * 300
        result = run_wrapper(
            WRAPPER,
            "-Prompt", prompt,
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
        )
        assert result.returncode == 0, result.combined_output
        assert "exceeds soft limit" not in result.combined_output
        assert "exceeds reject limit" not in result.combined_output

    def test_prompt_in_warn_range_emits_warning_but_dispatches(self, fake_gemini_exe, run_wrapper):
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        prompt = "y" * 600
        result = run_wrapper(
            WRAPPER,
            "-Prompt", prompt,
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
        )
        assert result.returncode == 0, result.combined_output
        normalized = " ".join(result.combined_output.split())
        assert "exceeds soft limit 500" in normalized

    def test_prompt_over_reject_threshold_exits_four(self, fake_gemini_exe, run_wrapper):
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        prompt = "z" * 6000
        result = run_wrapper(
            WRAPPER,
            "-Prompt", prompt,
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
        )
        assert result.returncode == 4, result.combined_output
        normalized = " ".join(result.combined_output.split())
        assert "exceeds reject limit 5000" in normalized

    def test_suppress_size_warn_bypasses_reject(self, fake_gemini_exe, run_wrapper):
        fake_gemini_exe.configure(stdout="__OK__", exit_code=0)
        prompt = "w" * 6000
        result = run_wrapper(
            WRAPPER,
            "-Prompt", prompt,
            "-Executable", str(fake_gemini_exe.path),
            "-MaxRetriesPerTier", "0",
            "-BaseBackoffSeconds", "0",
            "-SuppressSizeWarn",
        )
        assert result.returncode == 0, result.combined_output
        assert "exceeds reject limit" not in result.combined_output
        assert "exceeds soft limit" not in result.combined_output
