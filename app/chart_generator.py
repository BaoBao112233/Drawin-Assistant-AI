"""
chart_generator.py – Automatic Matplotlib chart generation.

Given a list-of-dicts result set (from SQL Agent), this module:
  1. Detects whether the data is chart-worthy.
  2. Chooses the appropriate chart type.
  3. Renders a Matplotlib figure using a dark theme matching the UI.
  4. Returns the figure as a base64-encoded PNG string.

Supported chart types
---------------------
  bar          – categorical label + single numeric value
  horizontal_bar – same but with many labels (> 8 rows)
  line         – time/ordinal column + one or more numeric values
  pie          – categorical + value, <= 8 distinct categories
  multi_bar    – categorical + multiple numeric columns (grouped bars)
"""
from __future__ import annotations

import base64
import io
import logging
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Colour palette (dark UI) ──────────────────────────────────────────────────
_PALETTE   = ["#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444",
              "#06b6d4", "#f97316", "#a78bfa", "#34d399", "#fbbf24"]
_BG        = "#1e293b"
_GRID      = "#334155"
_TEXT      = "#f1f5f9"
_TICK      = "#94a3b8"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def try_generate_chart(
    results: List[Dict[str, Any]],
    question: str = "",
    sql: str = "",
) -> Optional[Dict[str, str]]:
    """
    Attempt to generate a chart from *results*.

    Returns a dict ``{"chart_type": str, "chart_b64": str}`` on success,
    or ``None`` if the data is not chart-worthy.
    """
    if not results or len(results) < 1:
        return None

    try:
        detection = _detect(results, question, sql)
        if detection is None:
            return None

        chart_type, label_col, value_cols, trimmed_results = detection
        fig = _render(trimmed_results, chart_type, label_col, value_cols, question)
        if fig is None:
            return None

        b64 = _fig_to_b64(fig)
        return {"chart_type": chart_type, "chart_b64": b64}

    except Exception as exc:
        logger.warning(f"[ChartGenerator] Non-fatal error: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────# Chart-type intent parser
# ───────────────────────────────────────────────────────────────────────────────

_CHART_KEYWORDS: Dict[str, List[str]] = {
    "pie": [
        "biểu đồ tròn", "hình tròn", "biểu đồ donut", "tỷ lệ phần trăm",
        "pie chart", "pie graph", "donut chart", "pie",
    ],
    "line": [
        "biểu đồ đường", "xu hướng", "đường kẻ", "theo thời gian", "đồ thị đường",
        "line chart", "line graph", "trend chart", "time series",
    ],
    "horizontal_bar": [
        "biểu đồ cột ngang", "cột ngang", "thanh ngang",
        "horizontal bar", "bar horizontal",
    ],
    "bar": [
        "biểu đồ cột", "biểu đồ thanh", "cột dọc", "đồ thị cột",
        "bar chart", "bar graph", "column chart",
    ],
}

_PIE_MAX_SLICES = 8   # max categories for a readable pie chart


def _parse_requested_chart_type(question: str) -> Optional[str]:
    """Return explicit chart type requested by user, or None for auto-detect."""
    q = question.lower()
    # Check in priority order: horizontal_bar before bar to avoid false match
    for chart_type in ("pie", "line", "horizontal_bar", "bar"):
        if any(kw in q for kw in _CHART_KEYWORDS[chart_type]):
            return chart_type
    return None


# ───────────────────────────────────────────────────────────────────────────────# Detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect(
    results: List[Dict],
    question: str,
    sql: str,
) -> Optional[Tuple[str, Optional[str], List[str], List[Dict]]]:
    """
    Returns (chart_type, label_column, [value_columns], trimmed_results) or None.

    Priority:
    0. If user explicitly requested a chart type, honour it.
    Auto-detection rules (fallback):
    1. If only 1 row → not chart-worthy (single KPI, not a series).
    2. Classify each column as numeric, date, or categorical.
    3. If date column exists + numeric(s) → line.
    4. If categorical + multiple numerics → multi_bar.
    5. If categorical + 1 numeric, <= 8 rows → pie.
    6. If categorical + 1 numeric, 8 < rows <= 30 → bar or horizontal_bar.
    7. If all numeric columns (no category) + >= 2 rows → line (index as x).
    """
    if len(results) < 2:
        return None

    # ── Step 0: Detect explicit user request ─────────────────────────────
    requested_type = _parse_requested_chart_type(question)

    sample = results[0]
    cols   = list(sample.keys())

    numeric_cols  : List[str] = []
    date_cols     : List[str] = []
    category_cols : List[str] = []

    for col in cols:
        vals = [r.get(col) for r in results if r.get(col) is not None]
        if not vals:
            continue
        if _all_numeric(vals):
            numeric_cols.append(col)
        elif _all_date(vals):
            date_cols.append(col)
        else:
            category_cols.append(col)

    n_rows = len(results)

    # Need at least one numeric column to draw a chart
    if not numeric_cols:
        return None

    # ── Step 1: Honour explicit user chart-type request ───────────────────
    if requested_type and category_cols and numeric_cols:
        label_col    = category_cols[0]
        value_col    = numeric_cols[0]
        trimmed      = results   # default: use all rows

        if requested_type == "pie":
            # Limit to top-N slices sorted by value descending
            trimmed = sorted(results, key=lambda r: _to_float(r.get(value_col)), reverse=True)
            trimmed = trimmed[:_PIE_MAX_SLICES]
            return ("pie", label_col, [value_col], trimmed)

        if requested_type == "line":
            label_col = date_cols[0] if date_cols else category_cols[0]
            return ("line", label_col, numeric_cols[:4], results)

        if requested_type == "horizontal_bar":
            return ("horizontal_bar", label_col, [value_col], results)

        if requested_type == "bar":
            return ("bar", label_col, [value_col], results)

    # ── Step 2: Auto-detection fallback ───────────────────────────────

    # Prefer date axis → line chart
    if date_cols:
        label_col = date_cols[0]
        return ("line", label_col, numeric_cols[:4], results)

    # Categorical label + numerics
    if category_cols:
        label_col = category_cols[0]

        # Multiple numeric columns → grouped bar
        if len(numeric_cols) >= 2:
            return ("multi_bar", label_col, numeric_cols[:4], results)

        # Single numeric
        if n_rows <= 8:
            return ("pie", label_col, [numeric_cols[0]], results)

        if n_rows > 15:
            return ("horizontal_bar", label_col, [numeric_cols[0]], results)

        return ("bar", label_col, [numeric_cols[0]], results)

    # All numeric, no labels → line with numeric index
    if len(numeric_cols) >= 2:
        return ("line", None, numeric_cols[:4], results)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render(
    results: List[Dict],
    chart_type: str,
    label_col: Optional[str],
    value_cols: List[str],
    title: str,
) -> Optional[Any]:
    """Return a matplotlib Figure or None on import error."""
    try:
        import matplotlib
        matplotlib.use("Agg")           # non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        import numpy as np
    except ImportError:
        logger.warning("[ChartGenerator] matplotlib not installed; skipping chart.")
        return None

    labels = (
        [str(r.get(label_col, i)) for i, r in enumerate(results)]
        if label_col else
        [str(i + 1) for i in range(len(results))]
    )
    # Truncate long labels
    labels = [lb[:30] + "…" if len(lb) > 30 else lb for lb in labels]
    short_title = (title[:80] + "…") if len(title) > 80 else title

    # ── Figure setup ──────────────────────────────────────────────────────
    fig_w = max(8, min(14, len(labels) * 0.7 + 2))
    fig_h = 5 if chart_type != "horizontal_bar" else max(5, len(labels) * 0.4 + 1.5)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor=_BG)
    ax.set_facecolor(_BG)

    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.tick_params(colors=_TICK, labelsize=9)
    ax.xaxis.label.set_color(_TEXT)
    ax.yaxis.label.set_color(_TEXT)
    ax.title.set_color(_TEXT)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_number))

    # ── Draw ──────────────────────────────────────────────────────────────
    if chart_type == "bar":
        values = [_to_float(r.get(value_cols[0])) for r in results]
        x = np.arange(len(labels))
        bars = ax.bar(x, values, color=_PALETTE[0], width=0.6, zorder=2)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel(value_cols[0], color=_TICK)
        _add_bar_labels(ax, bars, values)

    elif chart_type == "horizontal_bar":
        values = [_to_float(r.get(value_cols[0])) for r in results]
        y = np.arange(len(labels))
        bars = ax.barh(y, values, color=_PALETTE[0], height=0.6, zorder=2)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel(value_cols[0], color=_TICK)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(_fmt_number))
        for i, (bar, val) in enumerate(zip(bars, values)):
            ax.text(val * 1.01, bar.get_y() + bar.get_height() / 2,
                    _fmt_number(val, None), va="center", ha="left",
                    color=_TEXT, fontsize=7.5)

    elif chart_type == "line":
        x = np.arange(len(labels))
        for i, vcol in enumerate(value_cols):
            values = [_to_float(r.get(vcol)) for r in results]
            ax.plot(x, values, color=_PALETTE[i % len(_PALETTE)],
                    marker="o", markersize=4, linewidth=2, label=vcol)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.legend(facecolor=_BG, labelcolor=_TEXT, fontsize=8, framealpha=0.7)

    elif chart_type == "pie":
        values = [max(0.0, _to_float(r.get(value_cols[0]))) for r in results]
        total  = sum(values) or 1
        # Filter zero slices
        pairs  = [(l, v) for l, v in zip(labels, values) if v > 0]
        if not pairs:
            plt.close(fig)
            return None
        lbls, vals = zip(*pairs)
        wedge_props = {"linewidth": 1.5, "edgecolor": _BG}
        ax.pie(
            vals, labels=lbls, colors=_PALETTE[:len(vals)],
            autopct=lambda p: f"{p:.1f}%\n({_fmt_number(p / 100 * total, None)})",
            wedgeprops=wedge_props, textprops={"color": _TEXT, "fontsize": 7.5},
            pctdistance=0.75, startangle=140,
        )
        fig.set_facecolor(_BG)

    elif chart_type == "multi_bar":
        x = np.arange(len(labels))
        n_groups = len(value_cols)
        w = 0.8 / n_groups
        for i, vcol in enumerate(value_cols):
            vals = [_to_float(r.get(vcol)) for r in results]
            offset = (i - n_groups / 2 + 0.5) * w
            ax.bar(x + offset, vals, width=w, color=_PALETTE[i % len(_PALETTE)],
                   label=vcol, zorder=2)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.legend(facecolor=_BG, labelcolor=_TEXT, fontsize=8, framealpha=0.7)

    # ── Grid and title ────────────────────────────────────────────────────
    if chart_type != "pie":
        ax.grid(axis="y" if chart_type != "horizontal_bar" else "x",
                color=_GRID, linestyle="--", linewidth=0.6, zorder=1)
    ax.set_title(short_title, color=_TEXT, fontsize=10, pad=10)
    fig.tight_layout(pad=1.5)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    import matplotlib.pyplot as plt
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _all_numeric(vals: List) -> bool:
    try:
        for v in vals[:20]:
            float(str(v).replace(",", ""))
        return True
    except (ValueError, TypeError):
        return False


def _all_date(vals: List) -> bool:
    date_patterns = [
        r"^\d{4}-\d{2}-\d{2}",
        r"^\d{2}/\d{2}/\d{4}",
        r"^\d{4}-\d{2}$",
    ]
    for v in vals[:10]:
        s = str(v)
        if not any(re.match(p, s) for p in date_patterns):
            try:
                datetime.fromisoformat(s[:10])
            except (ValueError, TypeError):
                return False
    return True


def _to_float(val: Any) -> float:
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _fmt_number(x: float, pos) -> str:
    """Human-readable number formatting (1 000 → 1K, 1 000 000 → 1M)."""
    try:
        if abs(x) >= 1_000_000:
            return f"{x / 1_000_000:.1f}M"
        if abs(x) >= 1_000:
            return f"{x / 1_000:.1f}K"
        if x == int(x):
            return str(int(x))
        return f"{x:.2f}"
    except (TypeError, ValueError):
        return str(x)


def _add_bar_labels(ax, bars, values):
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(abs(v) for v in values) * 0.01,
            _fmt_number(val, None),
            ha="center", va="bottom", color=_TEXT, fontsize=7.5,
        )
