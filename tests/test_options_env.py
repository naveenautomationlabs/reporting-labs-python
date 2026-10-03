import json

from reporting_labs.core import options as options_mod
from reporting_labs.core.envdetect import detect_env_name


def test_env_name_convention():
    assert detect_env_name({"ENV": "qa"}) == "qa"
    assert detect_env_name({"TEST_ENV": "uat", "STAGE": "prod"}) == "uat"
    assert detect_env_name({"OPENCART_ENV": "stage-2"}) == "stage-2"
    assert detect_env_name({"APP_ENV": "qa", "OPENCART_ENV": "stage"}) == "qa"


def test_env_name_rejects_junk_and_system():
    assert detect_env_name({"ENV": "/usr/local/bin", "OPENCART_ENV": "uat"}) == "uat"
    assert detect_env_name({"GITHUB_ENV": "/path", "NODE_ENV": "production", "VIRTUAL_ENV": "/x"}) is None
    assert detect_env_name({"ENV": "has space"}) is None


def test_env_var_option_named():
    assert detect_env_name({"TARGET": "uat", "ENV": "dev"}, "TARGET") == "uat"
    # when the named variable is missing, do not fall back to convention
    assert detect_env_name({"ENV": "dev"}, "TARGET") is None


def test_options_precedence(tmp_path):
    (tmp_path / "reporting-labs.config.json").write_text(json.dumps({"title": "From file", "metadata": {"env": "local"}}))
    opts = options_mod.load(tmp_path, environ={"ENV": "qa"})
    assert opts["title"] == "From file"
    assert opts["metadata"]["env"] == "qa"   # the runtime value wins over the file


def test_options_runtime_overrides(tmp_path):
    (tmp_path / "reporting-labs.config.json").write_text(json.dumps({"title": "From file", "metadata": {"env": "local"}}))
    env = {"ENV": "dev", "REPORTING_LABS_METADATA_ENV": "prod", "REPORTING_LABS_METADATA_BUILD": "1842", "REPORTING_LABS_TITLE": "Overridden"}
    opts = options_mod.load(tmp_path, environ=env)
    assert opts["metadata"]["env"] == "prod"      # explicit override beats convention
    assert opts["metadata"]["build"] == "1842"
    assert opts["title"] == "Overridden"


def test_pyproject_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.reporting-labs]\ntitle = "From pyproject"\npalette = "ocean"\n')
    opts = options_mod.load(tmp_path, environ={})
    assert opts["title"] == "From pyproject"
    assert opts["palette"] == "ocean"


def test_snake_case_keys(tmp_path):
    (tmp_path / "reporting-labs.config.json").write_text(json.dumps({"output_folder": "out", "mask_keys": ["pan"], "warn_missing_meta": False}))
    opts = options_mod.load(tmp_path, environ={})
    assert opts["outputFolder"] == "out"
    assert opts["maskKeys"] == ["pan"]
    assert opts["warnMissingMeta"] is False


def test_ci_metadata_no_build_chip(tmp_path):
    env = {"GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "main", "GITHUB_SHA": "0123456789abcdef", "GITHUB_RUN_NUMBER": "42"}
    opts = options_mod.load(tmp_path, environ=env)
    assert opts["metadata"]["branch"] == "main"
    assert opts["metadata"]["commit"] == "0123456"
    assert opts["metadata"]["ci"] == "github-actions"
    assert "build" not in opts["metadata"]   # the run number labels the trend, it is not a chip
