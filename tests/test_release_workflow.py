"""Tests for .github/workflows/release.yml and .github/release-body.md.

GitHub Actions is the only thing that can actually run the workflow, so these
tests parse the checked-in files instead. They exist because every bug they
guard against has already been shipped once, in one of these four projects:

- a release published with no title, showing only the bare tag;
- notes produced by ``--generate-notes``, which dumps the commit log — for a
  first release, the entire project history — where a description of what is
  being downloaded should be;
- a release created through GitHub's own "Draft a new release" page, which
  makes ``gh release create`` fail, leaving the fallback path to publish a
  release with whatever title the web UI defaulted to;
- a download table promising macOS and Linux builds that the workflow never
  actually built.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO / ".github" / "workflows" / "release.yml"
BODY_PATH = REPO / ".github" / "release-body.md"

APP_NAME = "Orion"

#: Every platform the release promises. Each must be genuinely built, on its
#: own runner: PyInstaller does not cross-compile, so a missing runner means a
#: missing binary, not a slower one.
PLATFORMS = {
    "windows-latest": "windows-x64",
    "macos-latest": "macos-arm64",
    "ubuntu-latest": "linux-x64",
}


def load_workflow():
    yaml = pytest.importorskip("yaml", reason="pyyaml is needed to check workflow files")
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def triggers(workflow):
    # PyYAML's 1.1 reader parses the bare ``on:`` key as the boolean True.
    # That is a quirk of the library, not of the workflow file.
    return workflow.get("on") or workflow[True]


def build_steps(workflow):
    return workflow["jobs"]["build"]["steps"]


def step_named(steps, name):
    return next((step for step in steps if step.get("name") == name), None)


def test_the_workflow_is_valid_yaml_and_has_both_jobs():
    workflow = load_workflow()
    assert set(workflow["jobs"]) == {"release", "build"}


def test_every_workflow_file_in_the_repository_parses():
    """A broken workflow file fails silently: GitHub simply never shows the
    run. Catching the syntax error here is much cheaper than noticing its
    absence on the Actions tab.
    """
    yaml = pytest.importorskip("yaml")
    for path in (REPO / ".github" / "workflows").iterdir():
        if path.suffix in (".yml", ".yaml"):
            assert yaml.safe_load(path.read_text(encoding="utf-8")), path.name


def test_all_three_platforms_are_built_on_their_own_runner():
    matrix = load_workflow()["jobs"]["build"]["strategy"]["matrix"]["include"]
    built = {entry["os"]: entry["asset"] for entry in matrix}
    assert built == PLATFORMS


def test_one_platform_failing_does_not_cancel_the_others():
    """fail-fast would throw away a good Windows build because macOS broke."""
    assert load_workflow()["jobs"]["build"]["strategy"]["fail-fast"] is False


def test_the_workflow_can_be_triggered_by_hand_and_by_a_tag():
    on = triggers(load_workflow())
    assert "workflow_dispatch" in on
    assert on["push"]["tags"] == ["v*"]


def test_publishing_a_release_does_not_start_a_second_racing_run():
    """Regression, seen live on Proteus v1.3.0: with a "release: published"
    trigger alongside the tag's push trigger, publishing a release from
    GitHub's UI fires both — the UI creates the tag, which is itself a push.
    Two runs then built the same three archives at once and uploaded them over
    each other with --clobber. The tag's push event covers both routes, so it
    is the only one kept.
    """
    assert "release" not in triggers(load_workflow())


def test_the_workflow_can_write_repository_contents():
    """Without this, `gh release create` fails on any repo or organisation
    that has tightened the default GITHUB_TOKEN to read-only.
    """
    assert load_workflow()["permissions"]["contents"] == "write"


def test_the_app_name_matches_this_product():
    """The packaging and upload steps are driven entirely by APP_NAME; a stale
    one silently produces archives nobody is looking for.
    """
    assert load_workflow()["env"]["APP_NAME"] == APP_NAME


def test_every_bundle_is_smoke_tested_before_it_is_offered_for_download():
    """A bundle that cannot start is worse than no bundle."""
    step = step_named(build_steps(load_workflow()), "Smoke-test the bundle")
    assert step is not None, "no smoke-test step in the build job"
    assert "--version" in step["run"]


def test_the_smoke_test_runs_before_packaging():
    steps = [step.get("name") for step in build_steps(load_workflow())]
    assert steps.index("Smoke-test the bundle") < steps.index("Package")


def test_the_release_notes_come_from_the_repository_not_from_the_commit_log():
    step = step_named(
        load_workflow()["jobs"]["release"]["steps"], "Create or update the release"
    )
    assert step is not None
    assert "--generate-notes" not in step["run"]
    assert ".github/release-body.md" in step["run"]


def test_the_release_gets_a_title_on_both_paths():
    """`gh release create` fails outright when a release already exists for the
    tag — which is the normal case for the "release published" trigger, and for
    anything drafted through GitHub's own UI. The fallback has to set the title
    and notes too, or the run "succeeds" leaving a blank release behind.
    """
    step = step_named(
        load_workflow()["jobs"]["release"]["steps"], "Create or update the release"
    )
    run = step["run"]
    assert "gh release create" in run
    assert "gh release edit" in run
    assert "--draft=false" in run, "a draft release is invisible to anonymous visitors"
    assert run.count("--title") == 2 and run.count("--notes") == 2


def test_assets_from_a_previous_build_are_removed_first():
    """Moving a tag onto a new commit leaves the old release's assets in place.
    They are not overwritten by name — the archives are named after the
    platform and the version — so an abandoned file would sit under notes that
    no longer describe it, offering a download nobody built.
    """
    steps = load_workflow()["jobs"]["release"]["steps"]
    step = step_named(steps, "Remove assets left by a previous build")
    assert step is not None, "no stale-asset cleanup step in the release job"
    assert "gh release delete-asset" in step["run"]

    names = [s.get("name") for s in steps]
    assert names.index("Create or update the release") < names.index(
        "Remove assets left by a previous build"
    ), "the release has to exist before its assets can be listed"


def test_only_version_tags_are_accepted():
    step = step_named(load_workflow()["jobs"]["release"]["steps"], "Work out which tag to build")
    assert "v[0-9]*" in step["run"], "a non-version tag must not publish a release"


def test_the_download_table_lists_exactly_what_is_built():
    """Regression: the notes used to promise macOS and Linux downloads that no
    job ever produced.
    """
    body = BODY_PATH.read_text(encoding="utf-8")
    for asset in PLATFORMS.values():
        extension = "tar.gz" if asset.startswith("linux") else "zip"
        expected = APP_NAME + "-{{VERSION}}-" + asset + "." + extension
        assert expected in body, asset


def test_the_release_body_carries_the_version_and_tag_placeholders():
    """They are substituted by the workflow; a literal placeholder reaching the
    published notes means the substitution stopped matching.
    """
    body = BODY_PATH.read_text(encoding="utf-8")
    assert "{{VERSION}}" in body
    assert "{{TAG}}" in body


def test_the_release_body_points_at_the_licence_and_the_commercial_terms():
    body = BODY_PATH.read_text(encoding="utf-8")
    assert "AGPL-3.0" in body
    assert "COMMERCIAL-LICENSE.md" in body
