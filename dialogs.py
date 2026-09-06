"""Native Windows file dialogs — avoids CustomTkinter/Tcl crashes."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog

OFN_OVERWRITEPROMPT = 0x00000002
OFN_HIDEREADONLY = 0x00000004
OFN_PATHMUSTEXIST = 0x00000800
OFN_NOCHANGEDIR = 0x00000008
OFN_FILEMUSTEXIST = 0x00001000
OFN_EXPLORER = 0x00080000


class _OPENFILENAMEW(ctypes.Structure):
  _fields_ = [
    ("lStructSize", wintypes.DWORD),
    ("hwndOwner", wintypes.HWND),
    ("hInstance", wintypes.HINSTANCE),
    ("lpstrFilter", wintypes.LPCWSTR),
    ("lpstrCustomFilter", wintypes.LPWSTR),
    ("nMaxCustFilter", wintypes.DWORD),
    ("nFilterIndex", wintypes.DWORD),
    ("lpstrFile", wintypes.LPWSTR),
    ("nMaxFile", wintypes.DWORD),
    ("lpstrFileTitle", wintypes.LPWSTR),
    ("nMaxFileTitle", wintypes.DWORD),
    ("lpstrInitialDir", wintypes.LPCWSTR),
    ("lpstrTitle", wintypes.LPCWSTR),
    ("Flags", wintypes.DWORD),
    ("nFileOffset", wintypes.WORD),
    ("nFileExtension", wintypes.WORD),
    ("lpstrDefExt", wintypes.LPCWSTR),
    ("lCustData", wintypes.LPARAM),
    ("lpfnHook", ctypes.c_void_p),
    ("lpTemplateName", wintypes.LPCWSTR),
    ("pvReserved", ctypes.c_void_p),
    ("dwReserved", wintypes.DWORD),
    ("FlagsEx", wintypes.DWORD),
  ]


def default_export_dir() -> Path:
  docs = Path.home() / "Documents"
  return docs if docs.is_dir() else Path.home()


def _filter_buffer(filters: list[tuple[str, str]]) -> ctypes.Array:
  parts: list[str] = []
  for label, pattern in filters:
    parts.extend([label, pattern])
  text = "\0".join(parts) + "\0\0"
  return ctypes.create_unicode_buffer(text)


def _windows_file_dialog(
  *,
  save: bool,
  title: str,
  default_name: str,
  initialdir: str,
  filters: list[tuple[str, str]],
  defext: str,
) -> str:
  filt = _filter_buffer(filters)
  file_buf = ctypes.create_unicode_buffer(default_name, 1024)
  ofn = _OPENFILENAMEW()
  ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
  ofn.hwndOwner = 0
  ofn.lpstrFilter = ctypes.cast(filt, wintypes.LPCWSTR)
  ofn.nFilterIndex = 1
  ofn.lpstrFile = ctypes.cast(file_buf, wintypes.LPWSTR)
  ofn.nMaxFile = len(file_buf)
  ofn.lpstrInitialDir = initialdir
  ofn.lpstrTitle = title
  flags = OFN_EXPLORER | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_NOCHANGEDIR
  if save:
    flags |= OFN_OVERWRITEPROMPT
  else:
    flags |= OFN_FILEMUSTEXIST
  ofn.Flags = flags
  ofn.lpstrDefExt = defext
  fn = ctypes.windll.comdlg32.GetSaveFileNameW if save else ctypes.windll.comdlg32.GetOpenFileNameW
  if fn(ctypes.byref(ofn)):
    return file_buf.value
  return ""


def ask_save_path(
  title: str,
  default_name: str,
  filetypes: list[tuple[str, str]],
  defaultextension: str,
  parent=None,
) -> str:
  initialdir = str(default_export_dir())
  if os.name == "nt":
    try:
      return _windows_file_dialog(
        save=True,
        title=title,
        default_name=default_name,
        initialdir=initialdir,
        filters=filetypes,
        defext=defaultextension.lstrip("."),
      )
    except Exception:
      pass
  try:
    return (
      filedialog.asksaveasfilename(
        parent=parent,
        title=title,
        defaultextension=defaultextension,
        filetypes=filetypes,
        initialdir=initialdir,
        initialfile=default_name,
      )
      or ""
    )
  except Exception:
    return str(default_export_dir() / default_name)


def ask_open_path(
  title: str,
  filetypes: list[tuple[str, str]],
  parent=None,
) -> str:
  initialdir = str(default_export_dir())
  if os.name == "nt":
    try:
      return _windows_file_dialog(
        save=False,
        title=title,
        default_name="",
        initialdir=initialdir,
        filters=filetypes,
        defext=filetypes[0][1].lstrip("*."),
      )
    except Exception:
      pass
  try:
    return (
      filedialog.askopenfilename(
        parent=parent,
        title=title,
        filetypes=filetypes,
        initialdir=initialdir,
      )
      or ""
    )
  except Exception:
    return ""
