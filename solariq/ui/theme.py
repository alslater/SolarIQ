# Compli design system tokens — referenced as CSS variables set in assets/compli.css.
# Use these string constants for inline style= props throughout the UI.

BG = "var(--compli-bg)"
SIDEBAR_FG = "var(--compli-sidebar-fg)"
SIDEBAR_MUTED = "var(--compli-sidebar-muted)"
CARD = "var(--compli-card)"
CARD_ALT = "var(--compli-card-alt)"
SIDEBAR = "var(--compli-sidebar)"
SECONDARY = "var(--compli-secondary)"
BORDER = "var(--compli-border)"
FG = "var(--compli-fg)"
MUTED = "var(--compli-muted)"
PRIMARY = "var(--compli-primary)"
ACCENT = "var(--compli-accent)"
PASS = "var(--compli-pass)"
REVIEW = "var(--compli-review)"
FAIL = "var(--compli-fail)"

# Hard-coded hex equivalents used directly in recharts fill/stroke props
# (recharts doesn't resolve CSS variables on SVG attributes)
CHART_SOLAR   = "#f49e0a"   # amber — solar generation
CHART_IMPORT  = "#0da2e7"   # cyan  — grid import
CHART_EXPORT  = "#28a36a"   # green — grid export / battery SOC
CHART_PRICE   = "#0da2e7"   # cyan  — agile price bars
CHART_GRID    = "#20283b"   # dark border — cartesian grid lines
CHART_MUTED   = "#7b8fa8"   # muted — axis ticks / labels

CARD_STYLE = {
    "background": CARD,
    "border": f"1px solid {BORDER}",
    "border_radius": "8px",
    "box_shadow": "0 1px 3px rgba(0,0,0,0.25)",
}
