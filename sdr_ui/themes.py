"""Shared suite colour palette (navy / teal / cyan)."""

# Header
COLOR_HEADER_BG = "#0B1C2C"
COLOR_HEADER_TEXT = "#ffffff"
COLOR_HEADER_SUB = "#7DD3FC"
COLOR_HEADER_ACCENT = "#22B8E6"
COLOR_TAB_IDLE = "#334155"
COLOR_TAB_IDLE_HOVER = "#1E293B"

# Surfaces
COLOR_BG = "#F4F7FB"
COLOR_BG_CARD = "#ffffff"
COLOR_BG_PANEL = "#F8FAFC"
COLOR_BORDER = "#E2E8F0"
COLOR_ROW_OK = "#ECFDF5"
COLOR_ROW_ALT = "#F8FAFC"

# Text
COLOR_TEXT = "#1E293B"
COLOR_TEXT_DIM = "#64748B"
COLOR_TEXT_MUTED = "#94A3B8"

# Status accents
COLOR_CYAN = "#0891B2"
COLOR_CYAN_BG = "#E0F2FE"
COLOR_BLUE = COLOR_HEADER_ACCENT
COLOR_BLUE_BG = COLOR_CYAN_BG
COLOR_GREEN = "#0F9F6E"
COLOR_GREEN_BG = "#ECFDF5"
COLOR_RED = "#DC2626"
COLOR_RED_BG = "#FEF2F2"
COLOR_ORANGE = "#EA580C"
COLOR_ORANGE_BG = "#FFF7ED"
# Hamaton suite uses navy / teal / cyan — keep these aliases so leftover
# "purple" tokens still land on-brand instead of the old violet.
COLOR_PURPLE = COLOR_CYAN
COLOR_PURPLE_BG = COLOR_CYAN_BG

# Controls
COLOR_BTN_PRIMARY = "#0D9B7A"
COLOR_BTN_PRIMARY_HOVER = "#0B7F64"
COLOR_BTN_SECONDARY = "#334155"
COLOR_BTN_SECONDARY_HOVER = "#1E293B"
COLOR_BTN_STOP = "#DC2626"
COLOR_BTN_STOP_HOVER = "#B91C1C"
COLOR_BTN_PAUSE = "#EA580C"
COLOR_BTN_PAUSE_HOVER = "#C2410C"
COLOR_BTN_EXPORT = "#1A365D"
COLOR_BTN_EXPORT_HOVER = "#12263A"

# Legacy aliases used by pressure helpers
COLOR_ACCENT = COLOR_HEADER_ACCENT
COLOR_OK = COLOR_GREEN
COLOR_DANGER = COLOR_RED
COLOR_WARN = COLOR_ORANGE
COLOR_BG_DARK = COLOR_BG


def combo_colors() -> dict:
  # Light field + bright cyan arrow button so the chevron stays readable
  return {
    "fg_color": COLOR_BG_CARD,
    "border_color": COLOR_BORDER,
    "button_color": COLOR_HEADER_ACCENT,
    "button_hover_color": "#0891B2",
    "dropdown_fg_color": COLOR_BG_CARD,
    "dropdown_hover_color": COLOR_CYAN_BG,
    "dropdown_text_color": COLOR_TEXT,
    "text_color": COLOR_TEXT,
  }


def entry_colors() -> dict:
  return {
    "fg_color": COLOR_BG_CARD,
    "border_color": COLOR_BORDER,
    "text_color": COLOR_TEXT,
    "placeholder_text_color": COLOR_TEXT_MUTED,
  }


def switch_colors() -> dict:
  return {
    "fg_color": COLOR_BORDER,
    "progress_color": COLOR_BTN_PRIMARY,
    "button_color": COLOR_BG_CARD,
    "button_hover_color": COLOR_CYAN_BG,
  }
