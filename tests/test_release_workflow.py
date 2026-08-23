# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

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


def test_the_smoke_test_actually_starts_qt():
    """--version on its own proves nothing about Qt.

    argparse's version action prints and exits inside argument parsing, before
    PySide6 is imported at all. A bundle missing its Qt platform plugin passes
    ``--version`` and then fails the moment a user double-clicks it. The smoke
    test has to construct a QApplication, which is what makes Qt go looking for
    a plugin, and it has to check which one it found.
    """
    step = step_named(build_steps(load_workflow()), "Smoke-test the bundle")
    assert "--self-check" in step["run"], (
        "the smoke test never starts Qt, so it cannot detect a broken bundle"
    )
    assert "platform plugin" in step["run"], (
        "the smoke test does not check which platform plugin was loaded"
    )


def test_the_linux_smoke_test_uses_a_real_display_not_offscreen():
    """offscreen loads none of the X libraries.

    A Linux bundle with a broken or unshippable xcb plugin comes up perfectly
    under QT_QPA_PLATFORM=offscreen — which is precisely the failure the smoke
    test exists to catch. It has to run against a virtual X server and the
    real backend.
    """
    step = step_named(build_steps(load_workflow()), "Smoke-test the bundle")
    assert "xvfb-run" in step["run"]
    assert "QT_QPA_PLATFORM=xcb" in step["run"]
    assert "Linux:xcb" in step["run"], "no assertion that xcb is what came up"


def test_the_virtual_x_server_is_installed_on_the_linux_runner():
    """A smoke test that calls xvfb-run without xvfb fails the release."""
    step = step_named(
        build_steps(load_workflow()), "Install the platform's system libraries"
    )
    assert step is not None
    assert "xvfb" in step["run"]


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


class TestSelfCheck:
    """The flag the smoke test relies on.

    Tested here rather than in the UI suite because its whole purpose is the
    release: if ``--self-check`` stops reporting the platform plugin, the
    workflow's ``case`` statement stops matching and every release fails, which
    is a confusing way to find out.
    """

    def test_it_is_a_real_flag(self):
        from orion.main import _parse_args

        assert _parse_args(["--self-check"]).self_check is True
        assert _parse_args([]).self_check is False

    def test_it_reports_the_platform_plugin_and_succeeds(self, qapp, capsys):
        from orion.main import _self_check

        assert _self_check(qapp) == 0
        printed = capsys.readouterr().out
        assert "platform plugin:" in printed
        # The workflow parses exactly this line; a reformat breaks the release.
        plugin = [
            line.split(": ", 1)[1]
            for line in printed.splitlines()
            if line.startswith("platform plugin: ")
        ]
        assert plugin and plugin[0], "the plugin name is missing or empty"

    def test_it_fails_when_qt_has_no_platform(self, capsys):
        """Qt normally aborts before this, but a silent empty platform name
        would otherwise be reported as a healthy bundle."""
        from orion.main import _self_check

        class NoPlatform:
            def platformName(self):
                return ""

        assert _self_check(NoPlatform()) == 1
