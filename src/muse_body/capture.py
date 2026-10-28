"""Grab frames of the VRChat desktop window (Windows), or a whole monitor elsewhere."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import mss
from PIL import Image


def _window_rect(title: str) -> dict[str, int] | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    # Client area in screen coordinates, so the title bar is not in the frame.
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return {"left": origin.x, "top": origin.y, "width": w, "height": h}


def is_foreground(title: str = "VRChat") -> bool | None:
    """Whether the window has focus. VRChat ignores gamepad input while unfocused
    (10-28: inputs sent while tabbed out were lost). None off Windows."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


class Camera:
    def __init__(self, window_title: str = "VRChat", monitor: int = 1, max_width: int = 1280):
        self.window_title = window_title
        self.monitor = monitor
        self.max_width = max_width
        self._sct = mss.mss()

    def grab(self) -> Image.Image:
        region = _window_rect(self.window_title) or self._sct.monitors[self.monitor]
        shot = self._sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > self.max_width:
            scale = self.max_width / img.width
            img = img.resize((self.max_width, round(img.height * scale)))
        return img
