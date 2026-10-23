"""Fyrqom palette — polished dashboard for TPMS Suite 6.0."""

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
UI_MONO = "SF Mono" if sys.platform == "darwin" else "Consolas"

# Brand
FYRQOM_BLACK = "#0E1116"
FYRQOM_TEAL = "#00C9B1"
FYRQOM_PAPER = "#FFFFFF"
FYRQOM_DARK = "#161A20"
FYRQOM_MID = "#3A424C"

# Sidebar
COLOR_SIDEBAR_BG = "#0A0E13"
COLOR_SIDEBAR_ACTIVE = "#00C9B1"
COLOR_SIDEBAR_HOVER = "#141A22"
COLOR_SIDEBAR_TEXT = "#C2CBD4"
COLOR_SIDEBAR_MUTED = "#6B7682"

# Header aliases
COLOR_HEADER_BG = COLOR_SIDEBAR_BG
COLOR_HEADER_TEXT = "#F5F7FA"
COLOR_HEADER_SUB = "#8A95A1"
COLOR_HEADER_ACCENT = FYRQOM_TEAL
COLOR_TAB_BAR = "#ECEFF2"
COLOR_TAB_IDLE = "#ECEFF2"
COLOR_TAB_IDLE_HOVER = "#DEE3E8"
COLOR_TAB_IDLE_TEXT = "#3A4548"
COLOR_TAB_ACTIVE = "#FFFFFF"
COLOR_TAB_ACTIVE_TEXT = "#007A6E"

# Surfaces
COLOR_BG = "#E6EAEF"
COLOR_BG_CARD = "#FFFFFF"
COLOR_BG_PANEL = "#F3F5F8"
COLOR_BORDER = "#D4DBE3"
COLOR_ROW_OK = "#E4F9F5"
COLOR_ROW_ALT = "#F5F7F7"

# Live dark panel
COLOR_LIVE_BG = "#12181F"
COLOR_LIVE_FG = "#F5F7FA"
COLOR_LIVE_MUTED = "#8B97A3"
COLOR_LIVE_CHIP = "#1A222C"
COLOR_LIVE_TEAL = FYRQOM_TEAL
COLOR_LIVE_BORDER = "#2A3440"

# Soft pills
COLOR_PILL_OK_BG = "#E5F7EE"
COLOR_PILL_OK_FG = "#0F7A4B"
COLOR_PILL_MUTED_BG = "#EEF1F4"
COLOR_PILL_MUTED_FG = "#5A6570"
COLOR_PILL_WARN_BG = "#FEF3E6"
COLOR_PILL_WARN_FG = "#C2410C"
COLOR_PILL_ERR_BG = "#FCECEC"
COLOR_PILL_ERR_FG = "#C53030"

# Text
COLOR_TEXT = "#0F1419"
COLOR_TEXT_DIM = "#55606B"
COLOR_TEXT_MUTED = "#7E8A95"

# Status
COLOR_CYAN = FYRQOM_TEAL
COLOR_CYAN_BG = "#E3F8F4"
COLOR_BLUE = "#2B7BBF"
COLOR_BLUE_BG = "#E8F2FB"
COLOR_GREEN = "#159A6C"
COLOR_GREEN_BG = "#E5F6EF"
COLOR_RED = "#D64545"
COLOR_RED_BG = "#FCECEC"
COLOR_ORANGE = "#D97706"
COLOR_ORANGE_BG = "#FEF3E6"
COLOR_PURPLE = COLOR_CYAN
COLOR_PURPLE_BG = COLOR_CYAN_BG

# Controls
COLOR_BTN_PRIMARY = FYRQOM_TEAL
COLOR_BTN_PRIMARY_HOVER = "#00B39E"
COLOR_BTN_PRIMARY_TEXT = "#FFFFFF"
COLOR_BTN_SECONDARY = "#4A5560"
COLOR_BTN_SECONDARY_HOVER = FYRQOM_DARK
COLOR_BTN_STOP = "#D64545"
COLOR_BTN_STOP_HOVER = "#B93A3A"
COLOR_BTN_STOP_BORDER = "#D64545"
COLOR_BTN_STOP_TEXT = "#D64545"
COLOR_BTN_STOP_OUTLINE = "#FFFFFF"
COLOR_BTN_STOP_OUTLINE_HOVER = "#FCECEC"
COLOR_BTN_PAUSE = FYRQOM_TEAL
COLOR_BTN_PAUSE_HOVER = "#00B39E"
COLOR_BTN_EXPORT = FYRQOM_DARK
COLOR_BTN_EXPORT_HOVER = "#000000"
COLOR_BTN_FULL = "#1A1D21"
COLOR_BTN_FULL_HOVER = "#000000"

COLOR_ACCENT = COLOR_HEADER_ACCENT
COLOR_OK = COLOR_GREEN
COLOR_DANGER = COLOR_RED
COLOR_WARN = COLOR_ORANGE
COLOR_BG_DARK = COLOR_SIDEBAR_BG

# Layout rhythm
SPACE_XS = 6
SPACE_SM = 10
SPACE_MD = 14
SPACE_LG = 18
RADIUS_CARD = 14
RADIUS_CTRL = 10


def ui_font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=UI_FONT, size=size, weight=weight)


def mono_font(size: int = 14, weight: str = "bold") -> ctk.CTkFont:
    return ctk.CTkFont(family=UI_MONO, size=size, weight=weight)


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
