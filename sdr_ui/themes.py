"""Fyrqom palette — from fyrqom.com: #101011 charcoal, #00d3bf teal, #fbfbfb paper."""

from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

_ASSETS = Path(__file__).resolve().parents[1] / "assets"
FYRQOM_LOGOTYPE = _ASSETS / "fyrqom_logotype_white.png"
FYRQOM_MARK = _ASSETS / "fyrqom_logo.png"

COMPANY_NAME = "Fyrqom"
PRODUCT_NAME = "Fyrqom TPMS Suite"
UI_FONT = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"

# Brand (fyrqom.com)
FYRQOM_BLACK = "#101011"
FYRQOM_TEAL = "#00d3bf"
FYRQOM_PAPER = "#FBFBFB"
FYRQOM_DARK = "#1F1F1F"
FYRQOM_MID = "#353535"

# Header
COLOR_HEADER_BG = FYRQOM_BLACK
COLOR_HEADER_TEXT = FYRQOM_PAPER
COLOR_HEADER_SUB = "#A8B5B3"
COLOR_HEADER_ACCENT = FYRQOM_TEAL
COLOR_TAB_BAR = "#ECEFEE"
COLOR_TAB_IDLE = "#ECEFEE"
COLOR_TAB_IDLE_HOVER = "#DDE6E4"
COLOR_TAB_IDLE_TEXT = "#3A4548"
COLOR_TAB_ACTIVE = "#FFFFFF"
COLOR_TAB_ACTIVE_TEXT = "#007A6E"

# Surfaces
COLOR_BG = "#F3F5F4"
COLOR_BG_CARD = FYRQOM_PAPER
COLOR_BG_PANEL = "#F7F9F8"
COLOR_BORDER = "#D0D9D7"
COLOR_ROW_OK = "#E4F9F5"
COLOR_ROW_ALT = "#F5F7F7"

# Text
COLOR_TEXT = FYRQOM_BLACK
COLOR_TEXT_DIM = "#4A5557"
COLOR_TEXT_MUTED = "#7A8785"

# Status
COLOR_CYAN = FYRQOM_TEAL
COLOR_CYAN_BG = "#E4F9F5"
COLOR_BLUE = "#1A8FA8"
COLOR_BLUE_BG = "#E7F3F7"
COLOR_GREEN = "#149A72"
COLOR_GREEN_BG = "#E6F6EF"
COLOR_RED = "#C24A44"
COLOR_RED_BG = "#FBECEC"
COLOR_ORANGE = "#C46A2B"
COLOR_ORANGE_BG = "#F8EFE6"
COLOR_PURPLE = COLOR_CYAN
COLOR_PURPLE_BG = COLOR_CYAN_BG

# Controls — brand teal primary (dark label for contrast on bright teal)
COLOR_BTN_PRIMARY = FYRQOM_TEAL
COLOR_BTN_PRIMARY_HOVER = "#00B8A8"
COLOR_BTN_PRIMARY_TEXT = "#FFFFFF"
COLOR_BTN_SECONDARY = FYRQOM_MID
COLOR_BTN_SECONDARY_HOVER = FYRQOM_DARK
COLOR_BTN_STOP = "#C24A44"
COLOR_BTN_STOP_HOVER = "#A33C37"
COLOR_BTN_PAUSE = "#C46A2B"
COLOR_BTN_PAUSE_HOVER = "#A35722"
COLOR_BTN_EXPORT = FYRQOM_DARK
COLOR_BTN_EXPORT_HOVER = FYRQOM_BLACK
COLOR_BTN_FULL = "#1E6F8A"
COLOR_BTN_FULL_HOVER = "#165A70"

COLOR_ACCENT = COLOR_HEADER_ACCENT
COLOR_OK = COLOR_GREEN
COLOR_DANGER = COLOR_RED
COLOR_WARN = COLOR_ORANGE
COLOR_BG_DARK = COLOR_HEADER_BG


def ui_font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=UI_FONT, size=size, weight=weight)


def combo_colors() -> dict:
    return {
        "fg_color": COLOR_BG_CARD,
        "border_color": COLOR_BORDER,
        "button_color": COLOR_BTN_PRIMARY,
        "button_hover_color": COLOR_BTN_PRIMARY_HOVER,
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
