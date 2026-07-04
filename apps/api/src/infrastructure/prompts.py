"""Prompt-template loading + rendering (M4).

Templates live in packages/prompts as {agent}/{task}.{locale}.j2 and are
rendered with Jinja2 (a core dependency). Resolution order for the root:

1. settings.prompts_dir (env PROMPTS_DIR) when set,
2. /app/prompts when it exists (the container copies packages/prompts there),
3. walk-up search from this file for a packages/prompts directory (dev).

Every call site ships an INLINE fallback template constant: when the file is
missing (or no root can be resolved) `render_prompt` logs a structlog warning
once per template and renders the fallback instead — the API never crashes on
a missing template. The .j2 files themselves are owned by the integrator
(packages/prompts); the required variables per template are documented there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from jinja2 import BaseLoader, Environment

logger = structlog.get_logger("infrastructure.prompts")

CONTAINER_PROMPTS_DIR = Path("/app/prompts")

# Template-source cache: (root, agent, task, locale) -> source | None.
_source_cache: dict[tuple[str, str, str, str], str | None] = {}
_warned: set[tuple[str, str, str]] = set()

_env = Environment(loader=BaseLoader(), autoescape=False, keep_trailing_newline=True)


def resolve_prompts_dir(prompts_dir: str | None = None) -> Path | None:
    """Resolve the prompt root; None when nothing exists (fallbacks kick in)."""
    if prompts_dir:
        return Path(prompts_dir)
    if CONTAINER_PROMPTS_DIR.is_dir():
        return CONTAINER_PROMPTS_DIR
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "prompts"
        if candidate.is_dir():
            return candidate
    return None


def get_prompt(
    agent: str, task: str, locale: str = "th", *, prompts_dir: str | None = None
) -> str | None:
    """Load {root}/{agent}/{task}.{locale}.j2; None when missing/unreadable."""
    root = resolve_prompts_dir(prompts_dir)
    if root is None:
        return None
    key = (str(root), agent, task, locale)
    if key in _source_cache:
        return _source_cache[key]
    path = root / agent / f"{task}.{locale}.j2"
    source: str | None
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        source = None
    _source_cache[key] = source
    return source


def render_prompt(
    agent: str,
    task: str,
    *,
    fallback: str,
    variables: dict[str, Any],
    locale: str = "th",
    prompts_dir: str | None = None,
) -> str:
    """Render the template file, or the inline fallback when it is missing.

    The fallback path logs a warning once per (agent, task, locale) so a
    missing template is visible without flooding worker logs.
    """
    source = get_prompt(agent, task, locale, prompts_dir=prompts_dir)
    if source is None:
        warn_key = (agent, task, locale)
        if warn_key not in _warned:
            _warned.add(warn_key)
            logger.warning(
                "prompt_template_missing_using_fallback",
                agent=agent,
                task=task,
                locale=locale,
            )
        source = fallback
    return _env.from_string(source).render(**variables)


def clear_prompt_cache() -> None:
    """Test hook: forget cached sources and warning bookkeeping."""
    _source_cache.clear()
    _warned.clear()
