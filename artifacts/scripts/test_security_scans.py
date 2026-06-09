"""Unit tests for repo-local security scanning rules."""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import repo_security_scan as rss


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestSecretHelpers:
    def test_placeholder_secret_is_ignored(self):
        assert rss.is_placeholder_secret("ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") is True

    def test_entropy_gate_for_generic_assignment(self):
        assert rss.generic_secret_is_actionable("AbCdEfGh1234567890") is True
        assert rss.generic_secret_is_actionable("xxxxxxxxxxxxxxxxxxxx") is False

    def test_placeholder_secret_extra_markers(self):
        assert rss.is_placeholder_secret("token-example") is True
        assert rss.is_placeholder_secret("XXXXXXXXXXXX") is True
        assert rss.is_placeholder_secret("aaaaaaaaaaaa") is True

    def test_empty_entropy(self):
        assert rss.shannon_entropy("") == 0.0

    def test_placeholder_secret_suffix_and_mask_branches(self, monkeypatch):
        monkeypatch.setattr(rss, "PLACEHOLDER_MARKERS", tuple(marker for marker in rss.PLACEHOLDER_MARKERS if marker != "example" and marker != "xxxx" and marker != "xxxxx"))
        assert rss.is_placeholder_secret("tokenexample") is True
        assert rss.is_placeholder_secret("XXXXXXXXXXXX") is True


class TestPathHelpers:
    def test_should_exclude_path_variants(self):
        assert rss.should_exclude_path(".git/config") is True
        assert rss.should_exclude_path(".github/skills/demo/SKILL.md") is True
        assert rss.should_exclude_path("notes/threat-model-20260417-124620/report.md") is True
        assert rss.should_exclude_path("docs/guide.md") is False

    def test_read_text_guards(self, tmp_path: Path, monkeypatch):
        binary = tmp_path / "binary.bin"
        binary.write_bytes(b"abc\x00def")
        assert rss.read_text(binary) is None                       # NUL/binary -> deliberate skip

        monkeypatch.setattr(rss, "MAX_FILE_BYTES", 4)
        oversize = tmp_path / "big.txt"
        oversize.write_bytes(b"abcdef")
        assert rss.read_text(oversize) is None                     # oversize -> deliberate skip

        def boom(self):
            raise OSError("boom")

        monkeypatch.setattr(Path, "read_bytes", boom)
        with pytest.raises(rss.ScanReadError):                     # OSError -> FAIL-CLOSED (TASK-1088)
            rss.read_text(tmp_path / "missing.txt")

    def test_iter_repo_files_excludes_non_text_and_skipped_paths(self, tmp_path: Path):
        _write(tmp_path / "docs" / "keep.md", "ok\n")
        _write(tmp_path / ".github" / "skills" / "demo" / "SKILL.md", "skip\n")
        (tmp_path / "image.png").write_bytes(b"png")
        files = list(rss.iter_repo_files(tmp_path))
        assert files == [("docs/keep.md", tmp_path / "docs" / "keep.md")]


class TestSecretScan:
    def test_detects_github_pat(self, tmp_path: Path):
        sample_secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        _write(tmp_path / "artifacts" / "scripts" / "sample.py", f'token = "{sample_secret}"\n')
        findings = rss.scan_secrets(tmp_path)
        assert any(f.rule_id == "github-pat-classic" for f in findings)

    def test_ignores_placeholder_pat(self, tmp_path: Path):
        _write(tmp_path / "README.md", 'token = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"\n')
        findings = rss.scan_secrets(tmp_path)
        assert findings == []

    def test_detects_generic_secret_assignment(self, tmp_path: Path):
        secret_value = "AbCdEfGh" + "1234567890ZyXwVu"
        _write(tmp_path / "artifacts" / "scripts" / "config.py", f'client_secret = "{secret_value}"\n')
        findings = rss.scan_secrets(tmp_path)
        assert any(f.rule_id == "generic-secret-assignment" for f in findings)

    def test_ignores_aws_example_token(self, tmp_path: Path):
        _write(tmp_path / "artifacts" / "scripts" / "config.py", 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
        findings = rss.scan_secrets(tmp_path)
        assert findings == []

    def test_detects_private_key_block(self, tmp_path: Path):
        private_key_block = "-----BEGIN " + "PRIVATE KEY-----\nabc\n"
        _write(tmp_path / "artifacts" / "scripts" / "key.txt", private_key_block)
        findings = rss.scan_secrets(tmp_path)
        assert len(findings) == 1
        assert any(f.rule_id == "private-key-block" for f in findings)

    def test_skips_when_read_text_returns_none(self, tmp_path: Path, monkeypatch):
        sample_path = tmp_path / "artifacts" / "scripts" / "sample.py"
        _write(sample_path, 'token = "ignored"\n')
        monkeypatch.setattr(rss, "iter_repo_files", lambda root: [("artifacts/scripts/sample.py", sample_path)])
        monkeypatch.setattr(rss, "read_text", lambda path: None)
        assert rss.scan_secrets(tmp_path) == []

    def test_ignores_non_actionable_generic_secret(self, tmp_path: Path):
        _write(tmp_path / "artifacts" / "scripts" / "config.py", 'client_secret = "xxxxxxxxxxxxxxxxxxxx"\n')
        findings = rss.scan_secrets(tmp_path)
        assert findings == []

    def test_excludes_skill_reference_tree(self, tmp_path: Path):
        sample_secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        _write(tmp_path / ".github" / "skills" / "demo" / "reference.md", f'token = "{sample_secret}"\n')
        findings = rss.scan_secrets(tmp_path)
        assert findings == []


class TestStaticScan:
    def test_detects_unpinned_action(self, tmp_path: Path):
        _write(
            tmp_path / ".github" / "workflows" / "bad.yml",
            "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n",
        )
        findings = rss.scan_static(tmp_path)
        assert any(f.rule_id == "workflow-unpinned-action" for f in findings)

    def test_detects_python_shell_true(self, tmp_path: Path):
        shell_line = "subprocess.run('echo hi', shell" + "=True)"
        _write(
            tmp_path / "artifacts" / "scripts" / "bad.py",
            f"import subprocess\n{shell_line}\n",
        )
        findings = rss.scan_static(tmp_path)
        assert any(f.rule_id == "python-shell-true" for f in findings)

    def test_detects_powershell_invoke_expression(self, tmp_path: Path):
        _write(tmp_path / "artifacts" / "scripts" / "bad.ps1", "Invoke-Expression $Command\n")
        findings = rss.scan_static(tmp_path)
        assert any(f.rule_id == "powershell-invoke-expression" for f in findings)

    def test_scans_template_workflows_too(self, tmp_path: Path):
        _write(
            tmp_path / "template" / ".github" / "workflows" / "bad.yml",
            "jobs:\n  test:\n    steps:\n      - uses: actions/setup-python@v5\n",
        )
        findings = rss.scan_static(tmp_path)
        assert any(f.path.startswith("template/.github/workflows/") for f in findings)

    def test_reports_clean_repo(self, tmp_path: Path):
        _write(
            tmp_path / ".github" / "workflows" / "ok.yml",
            "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2\n        with:\n          persist-credentials: false\n",
        )
        _write(tmp_path / "artifacts" / "scripts" / "ok.py", "print('safe')\n")
        assert rss.scan_static(tmp_path) == []

    def test_detect_static_target_none(self):
        assert rss.detect_static_target("docs/readme.md") is None

    def test_scan_static_skips_non_target_paths(self, tmp_path: Path, monkeypatch):
        sample_path = tmp_path / "docs" / "note.md"
        _write(sample_path, "safe\n")
        monkeypatch.setattr(rss, "iter_repo_files", lambda root: [("docs/note.md", sample_path)])
        assert rss.scan_static(tmp_path) == []

    def test_scan_static_skips_when_read_text_returns_none(self, tmp_path: Path, monkeypatch):
        sample_path = tmp_path / "artifacts" / "scripts" / "bad.py"
        _write(sample_path, "print('x')\n")
        monkeypatch.setattr(rss, "iter_repo_files", lambda root: [("artifacts/scripts/bad.py", sample_path)])
        monkeypatch.setattr(rss, "read_text", lambda path: None)
        assert rss.scan_static(tmp_path) == []


class TestRenderAndMain:
    def test_dedupe_findings(self):
        finding = rss.Finding("r1", "high", "a.py", 1, "m", "x")
        deduped = rss.dedupe_findings([finding, finding])
        assert deduped == [finding]

    def test_render_findings_variants(self):
        finding = rss.Finding("r1", "high", "a.py", 1, "m", "x")
        assert rss.render_findings([], as_json=False) == "[OK] No findings detected"
        assert '"rule_id": "r1"' in rss.render_findings([finding], as_json=True)
        assert "[FAIL] Detected 1 finding(s):" in rss.render_findings([finding], as_json=False)

    def test_main_static_clean_repo(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        _write(
            tmp_path / ".github" / "workflows" / "ok.yml",
            "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2\n        with:\n          persist-credentials: false\n",
        )
        exit_code = rss.main(["--root", str(tmp_path), "static"])
        captured = capsys.readouterr().out
        assert exit_code == 0
        assert "[OK] No findings detected" in captured


class TestFailClosed:
    """TASK-1088: a scan-coverage failure fails CLOSED (exit 2 / raise), never a silent exit 0.

    Deliberate non-text skips (oversize/binary) stay skips but are surfaced (auditability).
    """

    def test_raise_walk_error(self):
        with pytest.raises(rss.ScanReadError):
            rss._raise_walk_error(OSError("scandir denied"))

    def test_iter_repo_files_traversal_error_fails_closed(self, tmp_path: Path, monkeypatch):
        # patch the module-local _walk_repo seam (NOT the global os.walk, which pytest itself uses)
        def boom(root):
            raise rss.ScanReadError("traversal failed")

        monkeypatch.setattr(rss, "_walk_repo", boom)
        with pytest.raises(rss.ScanReadError):
            list(rss.iter_repo_files(tmp_path))

    def test_iter_repo_files_stat_error_fails_closed(self, tmp_path: Path, monkeypatch):
        # Path.is_file() SWALLOWS OSError; iter_repo_files uses path.stat() which RAISES -> fail-closed
        _write(tmp_path / "a.py", "x\n")

        def boom(self):
            raise OSError("stat denied")

        monkeypatch.setattr(Path, "stat", boom)
        with pytest.raises(rss.ScanReadError):
            list(rss.iter_repo_files(tmp_path))

    def test_iter_repo_files_skips_non_regular(self, tmp_path: Path, monkeypatch):
        _write(tmp_path / "a.py", "x\n")

        class _DirStat:
            st_mode = stat.S_IFDIR

        monkeypatch.setattr(Path, "stat", lambda self: _DirStat())
        assert list(rss.iter_repo_files(tmp_path)) == []           # non-regular entry skipped

    def test_main_bad_root_fails_closed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        assert rss.main(["--root", str(tmp_path / "nope"), "secrets"]) == 2
        assert "does not exist or is not a directory" in capsys.readouterr().err

    def test_main_resolve_error_fails_closed(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        def boom(self, *a, **k):
            raise OSError("resolve loop")

        monkeypatch.setattr(Path, "resolve", boom)
        assert rss.main(["--root", "whatever", "secrets"]) == 2
        assert "cannot resolve scan root" in capsys.readouterr().err

    def test_main_reports_skips_on_abort(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        f_skip = tmp_path / "artifacts" / "scripts" / "skip.py"
        _write(f_skip, "x\n")
        f_err = tmp_path / "artifacts" / "scripts" / "err.py"
        _write(f_err, "y\n")
        monkeypatch.setattr(
            rss, "iter_repo_files",
            lambda root: [("artifacts/scripts/skip.py", f_skip), ("artifacts/scripts/err.py", f_err)],
        )

        def rt(path):
            if path == f_skip:
                return None                          # deliberate skip recorded first
            raise rss.ScanReadError("read denied")    # then a hard error aborts

        monkeypatch.setattr(rss, "read_text", rt)
        assert rss.main(["--root", str(tmp_path), "secrets"]) == 2
        err = capsys.readouterr().err
        assert "skip.py" in err and "skipped (oversize/binary" in err  # skip surfaced despite abort
        assert "scan aborted" in err

    def test_main_read_error_fails_closed_all_commands(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        _write(tmp_path / "artifacts" / "scripts" / "a.py", "x\n")

        def boom(path):
            raise rss.ScanReadError("read denied")

        monkeypatch.setattr(rss, "read_text", boom)
        for cmd in (["secrets"], ["static"], ["sast", "--format", "sarif"]):
            assert rss.main(["--root", str(tmp_path), *cmd]) == 2
        assert "scan aborted" in capsys.readouterr().err

    def test_main_surfaces_deliberate_skips(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]):
        sample = tmp_path / "artifacts" / "scripts" / "big.py"
        _write(sample, "x\n")
        monkeypatch.setattr(rss, "iter_repo_files", lambda root: [("artifacts/scripts/big.py", sample)])
        monkeypatch.setattr(rss, "read_text", lambda path: None)    # deliberate non-text skip
        for cmd in (["secrets"], ["static"], ["sast", "--format", "text"]):
            assert rss.main(["--root", str(tmp_path), *cmd]) == 0
        err = capsys.readouterr().err
        assert "skipped (oversize/binary" in err
        assert "artifacts/scripts/big.py" in err

    def test_scan_helpers_record_skips(self, tmp_path: Path, monkeypatch):
        sample = tmp_path / "artifacts" / "scripts" / "big.py"
        _write(sample, "x\n")
        monkeypatch.setattr(rss, "iter_repo_files", lambda root: [("artifacts/scripts/big.py", sample)])
        monkeypatch.setattr(rss, "read_text", lambda path: None)
        for fn in (rss.scan_secrets, rss.scan_static, rss.scan_sast):
            sk: list[str] = []
            assert fn(tmp_path, skipped=sk) == []
            assert sk == ["artifacts/scripts/big.py"]


def test_cli_json_output_for_secrets(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    sample_secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    _write(tmp_path / "artifacts" / "scripts" / "sample.py", f'token = "{sample_secret}"\n')
    exit_code = rss.main(["--root", str(tmp_path), "--json", "secrets"])
    captured = capsys.readouterr().out
    assert exit_code == 1
    assert "github-pat-classic" in captured