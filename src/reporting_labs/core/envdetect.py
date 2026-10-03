"""Environment card rows, CI detection and the environment name.

A port of ciRunLabel, ciLink, gitInfo and detectEnvName in src/reporter.ts (0.6.9). Reads the same variables.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from .._version import __version__

# System variables that end in _ENV but never name a test environment.
NOT_AN_ENV_VAR = {
    "GITHUB_ENV", "NODE_ENV", "BASH_ENV", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "RUNNER_ENVIRONMENT", "PIPENV_ACTIVE",
    "ZSH_ENV", "JAVA_ENV", "DOTNET_ENVIRONMENT", "ASPNETCORE_ENVIRONMENT", "HOSTING_ENVIRONMENT", "PYTHONENV", "PYTEST_CURRENT_TEST",
}
# The usual names, in order of preference.
ENV_VAR_NAMES = ["ENV", "TEST_ENV", "ENVIRONMENT", "APP_ENV", "TARGET_ENV", "RUN_ENV", "DEPLOY_ENV", "ENV_NAME",
                 "TEST_ENVIRONMENT", "TARGET_ENVIRONMENT", "CI_ENVIRONMENT_NAME", "DEPLOYMENT_ENVIRONMENT", "STAGE"]
_ENV_NAME = re.compile(r"^[A-Za-z][\w.-]{0,31}$")
_WILD = re.compile(r"_(ENV|ENVIRONMENT|ENV_NAME)$", re.I)


def looks_like_env_name(v: Optional[str]) -> bool:
    return bool(v) and bool(_ENV_NAME.match(v.strip()))


def detect_env_name(env: Mapping[str, str], env_var: Optional[str] = None) -> Optional[str]:
    """The environment this run was pointed at, by convention. Precedence: the variable `env_var` names;
    the usual names (ENV, TEST_ENV, APP_ENV, TARGET_ENV, CI_ENVIRONMENT_NAME, STAGE...); any variable ending
    in _ENV / _ENVIRONMENT. System variables are never used, and a value only counts when it looks like a name."""
    def get(name: str) -> Optional[str]:
        v = env.get(name)
        if v is None:
            v = env.get(name.lower())
        return v.strip() if looks_like_env_name(v) else None

    if env_var:
        return get(env_var)
    for n in ENV_VAR_NAMES:
        v = get(n)
        if v:
            return v
    for k in sorted(env):
        if _WILD.search(k) and k.upper() not in NOT_AN_ENV_VAR and looks_like_env_name(env[k]):
            return env[k].strip()
    return None


def ci_run_label(env: Mapping[str, str]) -> Optional[str]:
    """Run number from the CI system, used to label history entries when metadata.build is not set."""
    for k in ("GITHUB_RUN_NUMBER", "BUILD_NUMBER", "CI_PIPELINE_IID", "CIRCLE_BUILD_NUM", "BUILD_BUILDNUMBER", "BITBUCKET_BUILD_NUMBER"):
        if env.get(k):
            return "#" + env[k]
    return None


def ci_link(env: Mapping[str, str]) -> Optional[Dict[str, str]]:
    g = env.get
    if g("GITHUB_ACTIONS") and g("GITHUB_SERVER_URL") and g("GITHUB_REPOSITORY") and g("GITHUB_RUN_ID"):
        return {"name": "GitHub Actions #" + (g("GITHUB_RUN_NUMBER") or g("GITHUB_RUN_ID")),
                "url": f"{g('GITHUB_SERVER_URL')}/{g('GITHUB_REPOSITORY')}/actions/runs/{g('GITHUB_RUN_ID')}"}
    if g("GITLAB_CI") and g("CI_JOB_URL"):
        return {"name": "GitLab CI #" + (g("CI_PIPELINE_IID") or g("CI_JOB_ID") or ""), "url": g("CI_JOB_URL")}
    if g("JENKINS_URL") and g("BUILD_URL"):
        return {"name": f"Jenkins {g('JOB_NAME') or ''} #{g('BUILD_NUMBER') or ''}".strip(), "url": g("BUILD_URL")}
    if g("CIRCLECI") and g("CIRCLE_BUILD_URL"):
        return {"name": f"CircleCI #{g('CIRCLE_BUILD_NUM') or ''}".strip(), "url": g("CIRCLE_BUILD_URL")}
    if g("TF_BUILD") and g("SYSTEM_TEAMFOUNDATIONCOLLECTIONURI") and g("SYSTEM_TEAMPROJECT") and g("BUILD_BUILDID"):
        return {"name": "Azure Pipelines #" + (g("BUILD_BUILDNUMBER") or g("BUILD_BUILDID")),
                "url": f"{g('SYSTEM_TEAMFOUNDATIONCOLLECTIONURI')}{g('SYSTEM_TEAMPROJECT')}/_build/results?buildId={g('BUILD_BUILDID')}"}
    if g("BITBUCKET_BUILD_NUMBER") and g("BITBUCKET_GIT_HTTP_ORIGIN"):
        return {"name": "Bitbucket Pipelines #" + g("BITBUCKET_BUILD_NUMBER"),
                "url": f"{g('BITBUCKET_GIT_HTTP_ORIGIN')}/addon/pipelines/home#!/results/{g('BITBUCKET_BUILD_NUMBER')}"}
    if g("CI"):
        return {"name": "CI"}
    return None


def ci_metadata(env: Mapping[str, str]) -> Dict[str, str]:
    """branch / commit / ci chips from the CI system. The build number is not a chip; it labels the trend."""
    g = env.get
    out: Dict[str, str] = {}

    def put(k: str, v: Optional[str]) -> None:
        if v:
            out[k] = v

    def sha(s: Optional[str]) -> Optional[str]:
        return s[:7] if s and len(s) >= 7 else s

    if g("GITHUB_ACTIONS"):
        put("branch", g("GITHUB_REF_NAME")); put("commit", sha(g("GITHUB_SHA"))); put("ci", "github-actions")
    elif g("JENKINS_URL"):
        put("branch", g("GIT_BRANCH")); put("commit", sha(g("GIT_COMMIT"))); put("ci", "jenkins")
    elif g("GITLAB_CI"):
        put("branch", g("CI_COMMIT_REF_NAME")); put("commit", sha(g("CI_COMMIT_SHA"))); put("ci", "gitlab-ci")
    elif g("CIRCLECI"):
        put("branch", g("CIRCLE_BRANCH")); put("commit", sha(g("CIRCLE_SHA1"))); put("ci", "circleci")
    elif g("TRAVIS"):
        put("branch", g("TRAVIS_BRANCH")); put("commit", sha(g("TRAVIS_COMMIT"))); put("ci", "travis")
    elif g("BUILDKITE"):
        put("branch", g("BUILDKITE_BRANCH")); put("commit", sha(g("BUILDKITE_COMMIT"))); put("ci", "buildkite")
    elif g("TEAMCITY_VERSION"):
        put("ci", "teamcity")
    elif g("TF_BUILD"):
        put("branch", g("BUILD_SOURCEBRANCHNAME")); put("commit", sha(g("BUILD_SOURCEVERSION"))); put("ci", "azure-pipelines")
    return out


def _run(cmd: List[str], cwd: Path) -> str:
    try:
        return subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2,
                              check=False).stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def git_info(cwd: Path, env: Mapping[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    line = _run(["git", "log", "-1", "--format=%H%x1f%an%x1f%s"], cwd)
    if line:
        parts = (line.split("\x1f") + ["", "", ""])[:3]
        out["sha"], out["author"], out["subject"] = parts
    sha = out.get("sha") or env.get("GITHUB_SHA") or env.get("CI_COMMIT_SHA") or env.get("GIT_COMMIT") or env.get("CIRCLE_SHA1") or env.get("BUILD_SOURCEVERSION")
    author = out.get("author") or env.get("GITHUB_ACTOR") or env.get("CI_COMMIT_AUTHOR")
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    branch = (branch if branch and branch != "HEAD" else "") or env.get("GITHUB_REF_NAME") or env.get("CI_COMMIT_REF_NAME") or env.get("GIT_BRANCH") or env.get("BUILD_SOURCEBRANCHNAME") or ""
    result: Dict[str, str] = {}
    if sha:
        result["sha"] = sha
    if author:
        result["author"] = author
    if out.get("subject"):
        result["subject"] = out["subject"]
    if branch:
        result["branch"] = branch
    if sha:
        if env.get("GITHUB_SERVER_URL") and env.get("GITHUB_REPOSITORY"):
            result["url"] = f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/commit/{sha}"
        elif env.get("CI_PROJECT_URL"):
            result["url"] = f"{env['CI_PROJECT_URL']}/-/commit/{sha}"
        else:
            remote = _run(["git", "config", "--get", "remote.origin.url"], cwd)
            m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", remote)
            if m:
                result["url"] = f"https://github.com/{m.group(1)}/commit/{sha}"
    return result


def package_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version(name)
    except Exception:
        return None


def collect_env(base: Path, framework_rows: List[Dict[str, str]], extra_env: Mapping[str, str], metadata: Mapping[str, str],
                workers: int, env: Optional[Mapping[str, str]] = None) -> List[Dict[str, str]]:
    """Rows for the Environment card, in the same order as reporter.ts collectEnv. `framework_rows` come first
    (pytest / Robot Framework, Playwright / Selenium versions, browsers)."""
    env = os.environ if env is None else env
    rows: List[Dict[str, str]] = list(framework_rows)
    rows.append({"k": "Python", "v": f"{platform.python_version()} ({platform.python_implementation()})"})
    rows.append({"k": "reportingLabs", "v": f"reporting-labs {__version__}"})
    rows.append({"k": "OS", "v": f"{platform.system()} {platform.release()} ({platform.machine()})"})
    if workers > 1:
        rows.append({"k": "Workers", "v": str(workers)})
    ci = ci_link(env)
    if ci:
        row = {"k": "CI", "v": ci["name"]}
        if ci.get("url"):
            row["href"] = ci["url"]
        rows.append(row)
    git = git_info(base, env)
    if git.get("sha"):
        v = git["sha"][:7] + (" · " + git["author"] if git.get("author") else "") + (" · " + git["subject"] if git.get("subject") else "")
        row = {"k": "Commit", "v": v}
        if git.get("url"):
            row["href"] = git["url"]
        rows.append(row)
    if git.get("branch") and not metadata.get("branch"):
        rows.append({"k": "Branch", "v": git["branch"]})
    for k, v in extra_env.items():
        row = {"k": str(k), "v": str(v)}
        if re.match(r"^https?://", str(v)):
            row["href"] = str(v)
        rows.append(row)
    return rows
