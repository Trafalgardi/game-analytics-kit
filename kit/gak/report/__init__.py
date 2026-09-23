"""Versioned, self-contained HTML reports (DESIGN.md section 6).

builder  new_version / build / build_index — folders, placeholders, report.html + artifact.html
charts   SVG chart helpers whose colours come from theme.css classes (light and dark)
"""
from . import charts
from .builder import ReportError, build, build_index, new_version

__all__ = ["ReportError", "build", "build_index", "new_version", "charts"]
