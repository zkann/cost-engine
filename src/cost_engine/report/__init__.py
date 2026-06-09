"""Report layer: an optional LLM executive summary plus JSON/markdown output."""

from __future__ import annotations

from .render import render_json, render_markdown
from .summarize import summarize

__all__ = ["render_json", "render_markdown", "summarize"]
