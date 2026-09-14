"""
Isolated right-dock behavior for the Via Tenting palette.
"""

from __future__ import annotations

import os
import tempfile
import traceback
from typing import Optional

PALETTE_ID = 'vanhixViaTentingPalette'
PALETTE_TITLE = 'Via Tenting'
PALETTE_WIDTH = 360
PALETTE_HEIGHT = 680
PALETTE_MAX_HEIGHT_ECAD = 740
DOCK_EVENT_ID = 'vanhixViaTentingDockRight'
DOCK_UI_EVENT_ID = 'vanhixViaTentingDockUi'

_LOG_PATH = os.path.join(tempfile.gettempdir(), 'vanhix_via_tenting_dock.log')

_config = None
_installed = False


def _log(message: str) -> None:
    try:
        with open(_LOG_PATH, 'a', encoding='utf-8') as handle:
            handle.write(message.rstrip() + '\n')
    except OSError:
        pass


def log(message: str) -> None:
    """Public log hook so the palette controller can record dock diagnostics."""
    _log(message)


def is_available() -> bool:
    try:
        import via_tenting_palette_dock as palette_dock  # noqa: F401
        return True
    except Exception as exc:
        _log(f'dock unavailable: {exc!r}')
        return False


def _build_config():
    import via_tenting_palette_dock as palette_dock

    return palette_dock.DockConfig(
        palette_id=PALETTE_ID,
        palette_title=PALETTE_TITLE,
        palette_width=PALETTE_WIDTH,
        palette_height=PALETTE_HEIGHT,
        palette_max_height_ecad=PALETTE_MAX_HEIGHT_ECAD,
        dock_event_id=DOCK_EVENT_ID,
        dock_ui_event_id=DOCK_UI_EVENT_ID,
    )


def install(app, ui, handlers) -> bool:
    global _config, _installed

    if _installed:
        return _config is not None

    try:
        import via_tenting_palette_dock as palette_dock

        _config = _build_config()
        palette_dock.register(app, ui, _config, handlers)
        _installed = True
        _log('install ok')
        return True
    except Exception:
        _config = None
        _installed = False
        _log(traceback.format_exc())
        return False


def uninstall(app) -> None:
    global _config, _installed

    if not _installed or _config is None:
        _config = None
        _installed = False
        return

    try:
        import via_tenting_palette_dock as palette_dock

        palette_dock.unregister(app, _config)
        _log('uninstall ok')
    except Exception:
        _log(traceback.format_exc())
    finally:
        _config = None
        _installed = False


def dock_now(palette, tag: str = 'create-sync') -> None:
    if palette is None:
        return
    try:
        import via_tenting_palette_dock as palette_dock

        palette_dock.dock_immediate(palette, tag)
    except Exception:
        _log(traceback.format_exc())


def on_palette_opened(palette, app, ui, path: str = 'open') -> None:
    if palette is None:
        return

    if _config is not None:
        try:
            import via_tenting_palette_dock as palette_dock

            palette_dock.on_palette_opened(palette, app, ui, _config, path=path)
            return
        except Exception:
            _log(traceback.format_exc())

    _show_floating(palette)


def is_palette_open(palette) -> bool:
    if _config is not None:
        try:
            import via_tenting_palette_dock as palette_dock

            return palette_dock.is_palette_open(palette)
        except Exception:
            pass
    try:
        return bool(palette and palette.isValid and palette.isVisible)
    except Exception:
        return False


def _show_floating(palette) -> None:
    try:
        import adsk.core

        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating
        palette.isVisible = True
    except Exception:
        _log(traceback.format_exc())
