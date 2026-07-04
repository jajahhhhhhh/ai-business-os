"""Prompt loader: resolution order, file rendering, inline-fallback path."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure import prompts as prompts_module
from src.infrastructure.prompts import (
    clear_prompt_cache,
    get_prompt,
    render_prompt,
    resolve_prompts_dir,
)

FALLBACK = "fallback {{ name }}"


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    clear_prompt_cache()


def _write(root: Path, agent: str, task: str, source: str, locale: str = "th") -> Path:
    directory = root / agent
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task}.{locale}.j2"
    path.write_text(source, encoding="utf-8")
    return path


def test_explicit_prompts_dir_wins(tmp_path: Path) -> None:
    assert resolve_prompts_dir(str(tmp_path)) == tmp_path


def test_auto_resolution_finds_repo_packages_prompts() -> None:
    # The dev walk-up from src/infrastructure/ must land on packages/prompts.
    resolved = resolve_prompts_dir(None)
    assert resolved is not None
    assert resolved.name == "prompts" and resolved.parent.name == "packages"


def test_get_prompt_reads_template_file(tmp_path: Path) -> None:
    _write(tmp_path, "analytics", "daily_enhance", "สวัสดี {{ snapshot }}")
    source = get_prompt("analytics", "daily_enhance", prompts_dir=str(tmp_path))
    assert source == "สวัสดี {{ snapshot }}"


def test_get_prompt_missing_file_returns_none(tmp_path: Path) -> None:
    assert get_prompt("analytics", "missing", prompts_dir=str(tmp_path)) is None


def test_locale_is_part_of_the_filename(tmp_path: Path) -> None:
    _write(tmp_path, "planner", "weekly_plan", "EN {{ x }}", locale="en")
    assert get_prompt("planner", "weekly_plan", prompts_dir=str(tmp_path)) is None
    assert (
        get_prompt("planner", "weekly_plan", locale="en", prompts_dir=str(tmp_path)) == "EN {{ x }}"
    )


def test_render_prompt_uses_file_when_present(tmp_path: Path) -> None:
    _write(tmp_path, "qa", "evaluate", "file {{ name }}")
    rendered = render_prompt(
        "qa",
        "evaluate",
        fallback=FALLBACK,
        variables={"name": "X"},
        prompts_dir=str(tmp_path),
    )
    assert rendered == "file X"


def test_render_prompt_falls_back_and_warns_once(tmp_path: Path, monkeypatch) -> None:
    warnings: list[dict] = []

    class SpyLogger:
        def warning(self, event: str, **kw: object) -> None:
            warnings.append({"event": event, **kw})

    monkeypatch.setattr(prompts_module, "logger", SpyLogger())
    for _ in range(3):
        rendered = render_prompt(
            "qa",
            "evaluate",
            fallback=FALLBACK,
            variables={"name": "Y"},
            prompts_dir=str(tmp_path),
        )
        assert rendered == "fallback Y"
    # Warned exactly once despite three renders.
    assert len(warnings) == 1
    assert warnings[0]["event"] == "prompt_template_missing_using_fallback"
    assert warnings[0]["agent"] == "qa" and warnings[0]["task"] == "evaluate"


def test_render_passes_variables_through_jinja(tmp_path: Path) -> None:
    _write(tmp_path, "change-analyst", "classify", '"{{ competitor_name }}": {{ diff }}')
    rendered = render_prompt(
        "change-analyst",
        "classify",
        fallback=FALLBACK,
        variables={"competitor_name": "Villa {{ evil }}", "diff": "+ราคา"},
        prompts_dir=str(tmp_path),
    )
    # Variable VALUES are not re-interpreted as template syntax.
    assert rendered == '"Villa {{ evil }}": +ราคา'
