"""Isolated right-docking engine for the Via Tenting palette.

Uniquely named to prevent sys.modules collisions with other Fusion add-ins.
Docks directly via Fusion's internal panel text commands:
    Panels.List
    Panels.Dock "<Panel Title>" R
    Panels.ValidateDockArea "<Panel Title>" RIGHT

Contains 100% headless execution with zero mouse or cursor movement.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

try:
    import adsk.core
    import adsk
except Exception:
    adsk = None  # type: ignore

_DOCK_LOG_PATH = os.path.join(tempfile.gettempdir(), 'vanhix_via_tenting_dock_debug.log')
_DEBUG = os.environ.get('VANHIX_DEBUG_DOCK', '').strip().lower() in ('1', 'true', 'yes')

_deferred_pending = False
_custom_events = []


class DockConfig(object):
    """Configuration container for palette docking attributes."""

    __slots__ = (
        'palette_id',
        'palette_title',
        'legacy_palette_ids',
        'palette_width',
        'palette_height',
        'palette_max_height_ecad',
        'dock_event_id',
        'dock_ui_event_id',
    )

    def __init__(
        self,
        palette_id: str,
        palette_title: str,
        legacy_palette_ids=(),
        palette_width: int = 360,
        palette_height: int = 680,
        palette_max_height_ecad: int = 740,
        dock_event_id: str = 'vanhixViaTentingDockRight',
        dock_ui_event_id: str = 'vanhixViaTentingDockUi',
    ):
        self.palette_id = palette_id
        self.palette_title = palette_title
        self.legacy_palette_ids = tuple(legacy_palette_ids or ())
        self.palette_width = palette_width
        self.palette_height = palette_height
        self.palette_max_height_ecad = palette_max_height_ecad
        self.dock_event_id = dock_event_id
        self.dock_ui_event_id = dock_ui_event_id

    def fit_height(self) -> int:
        return min(self.palette_height, self.palette_max_height_ecad)


def _log(msg: str) -> None:
    try:
        with open(_DOCK_LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(msg.rstrip() + '\n')
    except Exception:
        pass


def _clear_log() -> None:
    try:
        with open(_DOCK_LOG_PATH, 'w', encoding='utf-8') as fh:
            fh.write('==== via_tenting_palette_dock session ====\n')
    except Exception:
        pass


def seed_layout(config: DockConfig) -> bool:
    """Idempotent no-op for backward compatibility."""
    return True


def _text_cmd(app, cmd: str, tag: str) -> Optional[str]:
    """Execute a Fusion internal text command and log result."""
    try:
        out = app.executeTextCommand(cmd)
        _log(f'[{tag}] {cmd} -> {out!r}')
        return out or ''
    except Exception as exc:
        _log(f'[{tag}] {cmd} FAILED: {exc!r}')
        return None


def is_docked_right(app, config: DockConfig) -> bool:
    """Check if Fusion's panel manager confirms the panel is docked to the right."""
    try:
        title = config.palette_title
        check = _text_cmd(app, f'Panels.ValidateDockArea "{title}" RIGHT', 'check')
        if check is not None and 'NOT' not in check.upper() and 'VERIFIED' in check.upper():
            return True
    except Exception:
        pass
    return False


def is_palette_open(palette) -> bool:
    """True when the palette exists and is currently visible."""
    try:
        return bool(palette and palette.isValid and palette.isVisible)
    except Exception:
        return False


def focus_palette(palette, config: DockConfig) -> bool:
    """Bring existing palette to front."""
    if not palette or not palette.isValid:
        return False
    try:
        if not palette.isVisible:
            palette.isVisible = True
        adsk.doEvents()
    except Exception:
        pass
    return True


def dock_via_text_command(app, config: DockConfig, tag: str = 'textcmd') -> bool:
    """Dock the palette to the right using Fusion's internal panel command."""
    title = config.palette_title
    
    # 1. Force panel manager to refresh its window registry
    _text_cmd(app, 'Panels.List', tag)

    # 2. Issue dock command
    res = _text_cmd(app, f'Panels.Dock "{title}" R', tag)
    if res is None:
        return False

    # 3. Validate dock state
    check = _text_cmd(app, f'Panels.ValidateDockArea "{title}" RIGHT', tag)
    if check is not None and 'NOT' not in check.upper():
        _log(f'[{tag}] docked right via Panels.Dock')
        return True

    _log(f'[{tag}] Panels.Dock did not verify: {check!r}')
    return False


def dock_immediate(palette, tag: str = '') -> None:
    """Set docking permissions on initial creation without forcing floating state."""
    try:
        vert_and_horiz = adsk.core.PaletteDockingOptions.PaletteDockOptionsToVerticalAndHorizontal
        palette.dockingOption = vert_and_horiz
        palette.isVisible = True
        adsk.doEvents()
        _log(f'[{tag}] granted dockingOption vertical/horizontal')
    except Exception as exc:
        _log(f'[{tag}] dock_immediate error: {exc!r}')


def request_deferred_dock(app, config: DockConfig) -> None:
    """Queue docking on the next main-thread idle cycle after execute returns."""
    global _deferred_pending
    if _deferred_pending:
        _log('deferred dock skipped — already pending')
        return
    _deferred_pending = True
    try:
        app.fireCustomEvent(config.dock_event_id)
        _log(f'fired custom event {config.dock_event_id}')
    except Exception as exc:
        _deferred_pending = False
        _log(f'fireCustomEvent failed: {exc!r}')


def on_palette_opened(palette, app, ui, config: DockConfig, path: str = 'open') -> None:
    """Initiate right-docking sequence when a palette is shown."""
    try:
        # Ensure docking permissions and visibility
        vert_and_horiz = adsk.core.PaletteDockingOptions.PaletteDockOptionsToVerticalAndHorizontal
        palette.dockingOption = vert_and_horiz
        palette.isVisible = True
        adsk.doEvents()
    except Exception as exc:
        _log(f'{path} path: isVisible failed: {exc!r}')

    _log(f'{path} path: show + Panels.Dock')
    if dock_via_text_command(app, config, f'{path}.textcmd'):
        return

    # Retry deferred on next idle cycle when Qt window realization completes
    request_deferred_dock(app, config)


class _PaletteDockApiHandler(adsk.core.CustomEventHandler):
    """Completes docking after the command handler returns and UI is idle."""

    def __init__(self, config: DockConfig, app, ui):
        super().__init__()
        self._config = config
        self._app = app
        self._ui = ui

    def notify(self, args):
        global _deferred_pending
        try:
            palette = self._ui.palettes.itemById(self._config.palette_id)
            if not palette or not palette.isValid:
                return

            try:
                palette.isVisible = True
                adsk.doEvents()
            except Exception:
                pass

            dock_via_text_command(self._app, self._config, 'deferred.textcmd')
        except Exception as exc:
            _log(f'[deferred.textcmd] handler FAILED: {exc!r}')
        finally:
            _deferred_pending = False


def register(app, ui, config: DockConfig, handlers: list) -> None:
    """Register custom event for deferred docking and retain strong references."""
    global _custom_events
    try:
        app.unregisterCustomEvent(config.dock_event_id)
    except Exception:
        pass

    dock_event = app.registerCustomEvent(config.dock_event_id)
    api_handler = _PaletteDockApiHandler(config, app, ui)
    dock_event.add(api_handler)
    
    # Store in both global list and caller's handlers list to prevent garbage collection
    _custom_events.append(dock_event)
    handlers.append(dock_event)
    handlers.append(api_handler)
    _log(f'registered dock event {config.dock_event_id}')


def unregister(app, config: DockConfig) -> None:
    """Unregister custom events on add-in stop."""
    global _custom_events
    try:
        app.unregisterCustomEvent(config.dock_event_id)
    except Exception:
        pass
    _custom_events.clear()
    _log('unregistered dock events')
