from app.services import test_runner


def test_detect_framework_returns_none_for_empty_directory(tmp_path):
    assert test_runner.detect_framework(str(tmp_path)) == "none"


def test_detect_framework_detects_pytest_via_test_file(tmp_path):
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    assert test_runner.detect_framework(str(tmp_path)) == "pytest"


def test_detect_framework_detects_npm_via_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x", "scripts": {"test": "echo ok"}}')
    assert test_runner.detect_framework(str(tmp_path)) == "npm"


def test_run_tests_reports_honestly_when_no_framework(tmp_path):
    result = test_runner.run_tests(str(tmp_path))
    assert result.framework == "none"
    assert result.ran is False
    assert result.error


def test_run_tests_runs_a_real_passing_pytest_suite(tmp_path):
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    result = test_runner.run_tests(str(tmp_path))
    assert result.framework == "pytest"
    assert result.ran is True
    assert result.passed == 1
    assert result.failed == 0
    assert result.total == 1


def test_run_tests_runs_a_real_failing_pytest_suite(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n\n\ndef test_broken():\n    assert False\n"
    )
    result = test_runner.run_tests(str(tmp_path))
    assert result.framework == "pytest"
    assert result.ran is True
    assert result.passed == 1
    assert result.failed == 1
    assert result.total == 2


def test_parse_pytest_summary_with_no_failures():
    passed, failed = test_runner._parse_pytest_summary("5 passed in 0.12s")
    assert passed == 5
    assert failed == 0
