from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "artifacts" / "scripts"


def _powershell_exe() -> str:
    if os.name == "nt":
        ps = shutil.which("powershell.exe") or shutil.which("pwsh")
    else:
        ps = shutil.which("pwsh")
    if not ps:
        pytest.skip("PowerShell unavailable")
    return ps


@dataclass
class WrapperResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


@dataclass
class FakeExe:
    path: Path
    log_path: Path
    behavior_path: Path
    directory: Path

    def configure(self, *, stdout: str = "__OK__", stderr: str = "", exit_code: int = 0, sequence=None) -> None:
        payload = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "sequence": sequence or [],
        }
        self.behavior_path.write_text(json.dumps(payload), encoding="utf-8")

    def clear_log(self) -> None:
        self.log_path.write_text("", encoding="utf-8")

    def calls(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = str(self.directory) + os.pathsep + env.get("PATH", "")
        return env


def _write_fake_exe(tmp_path: Path, command_name: str) -> FakeExe:
    directory = tmp_path / f"fake-{command_name}"
    directory.mkdir()
    log_path = directory / f"{command_name}.jsonl"
    behavior_path = directory / f"{command_name}-behavior.json"
    script_path = directory / f"{command_name}_fake.py"
    log_path.write_text("", encoding="utf-8")
    behavior_path.write_text(json.dumps({"stdout": "__OK__", "stderr": "", "exit_code": 0, "sequence": []}), encoding="utf-8")
    script_path.write_text(
        f"""
from __future__ import annotations

import json
import sys
from pathlib import Path

log_path = Path({str(log_path)!r})
behavior_path = Path({str(behavior_path)!r})
existing = [line for line in log_path.read_text(encoding='utf-8').splitlines() if line.strip()] if log_path.exists() else []
call_index = len(existing)
behavior = json.loads(behavior_path.read_text(encoding='utf-8'))
# TASK-1062: capture stdin (non-blocking via isatty check on Windows is
# unreliable; just read whatever is on stdin -- pytest pipes always pipe).
stdin_data = ''
try:
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()
except Exception:
    stdin_data = ''
record = {{
    'call_index': call_index,
    'args': sys.argv[1:],
    'stdin': stdin_data,
}}
with log_path.open('a', encoding='utf-8') as fh:
    fh.write(json.dumps(record) + '\\n')
sequence = behavior.get('sequence') or []
current = sequence[call_index] if call_index < len(sequence) else behavior
stdout = current.get('stdout', '')
stderr = current.get('stderr', '')
if stdout:
    print(stdout)
if stderr:
    print(stderr, file=sys.stderr)
raise SystemExit(int(current.get('exit_code', 0)))
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        exe_path = directory / f"{command_name}.cmd"
        exe_path.write_text(f'@echo off\r\n"{sys.executable}" "{script_path}" %*\r\nexit /b %ERRORLEVEL%\r\n', encoding="utf-8")
    else:
        exe_path = directory / command_name
        exe_path.write_text(f'#!/usr/bin/env sh\nexec "{sys.executable}" "{script_path}" "$@"\n', encoding="utf-8")
        exe_path.chmod(0o755)
    return FakeExe(path=exe_path, log_path=log_path, behavior_path=behavior_path, directory=directory)


@pytest.fixture
def fake_codex_exe(tmp_path: Path) -> FakeExe:
    return _write_fake_exe(tmp_path, "codex")


@pytest.fixture
def fake_gemini_exe(tmp_path: Path) -> FakeExe:
    return _write_fake_exe(tmp_path, "gemini")


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "task-1054@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "TASK-1054"], cwd=repo, check=True)
    wiki = repo / "wiki"
    wiki.mkdir()
    readme = wiki / "README.md"
    readme.write_text("# Baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True, text=True)
    readme.write_text("# Baseline\n\n" + ("Changed for review.\n" * 600), encoding="utf-8")
    return repo


@pytest.fixture
def run_wrapper(tmp_repo: Path):
    def _run(wrapper_path: Path, *args: object, cwd: Path | None = None, env: dict[str, str] | None = None) -> WrapperResult:
        ps = _powershell_exe()
        command = [ps, "-NoProfile"]
        if Path(ps).name.lower() == "powershell.exe":
            command += ["-ExecutionPolicy", "Bypass"]
        command += ["-File", str(wrapper_path), *[str(arg) for arg in args]]
        result = subprocess.run(
            command,
            cwd=cwd or tmp_repo,
            env=env or os.environ.copy(),
            capture_output=True,
            text=True,
        )
        return WrapperResult(result.returncode, result.stdout, result.stderr)

    return _run
