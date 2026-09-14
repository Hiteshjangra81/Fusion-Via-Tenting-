"""
Fusion palette UI for Via Tenting — HTML only, no ULP or board logic.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional, Set
from urllib.parse import quote

import adsk
import adsk.core

import via_tenting_dock

PALETTE_ID = via_tenting_dock.PALETTE_ID
PALETTE_TITLE = via_tenting_dock.PALETTE_TITLE
PALETTE_WIDTH = via_tenting_dock.PALETTE_WIDTH
PALETTE_HEIGHT = via_tenting_dock.PALETTE_HEIGHT

_HANDLER_PALETTES: Set[int] = set()


PALETTE_HTML_VERSION = '14'


def palette_url(resources_dir: str) -> str:
    html_path = os.path.abspath(os.path.join(resources_dir, 'palette.html'))
    normalized = html_path.replace('\\', '/')
    if len(normalized) > 1 and normalized[1] == ':':
        base = 'file:///' + quote(normalized, safe='/:/@')
    else:
        base = 'file://' + quote(normalized, safe='/:/@')
    return base + '?v=' + PALETTE_HTML_VERSION


class PaletteController:
    def __init__(
        self,
        app: adsk.core.Application,
        ui: adsk.core.UserInterface,
        resources_dir: str,
        handlers: list,
        on_scan: Callable[[], list],
        on_apply: Callable[..., None],
        on_error: Callable[[str], None],
    ) -> None:
        self._app = app
        self._ui = ui
        self._resources_dir = resources_dir
        self._handlers = handlers
        self._on_scan = on_scan
        self._on_apply = on_apply
        self._on_error = on_error
        self._palette: Optional[adsk.core.Palette] = None
        self._open_in_progress = False
        self._last_visible_layers: list[int] = []
        self._handlers_attached = False

    def notify(self, action: str, data: str = '') -> None:
        palette = self._ui.palettes.itemById(PALETTE_ID)
        if palette and palette.isValid:
            try:
                palette.sendInfoToHTML(action, data)
            except Exception:
                pass

    def close(self) -> None:
        existing = self._ui.palettes.itemById(PALETTE_ID)
        if existing and existing.isValid:
            try:
                existing.isVisible = False
            except Exception:
                pass
        self._palette = None

    def _attach_handlers(self, palette: adsk.core.Palette) -> None:
        # Guarantee handlers are attached only ONCE to prevent duplicate apply/scan triggers
        if self._handlers_attached:
            return

        try:
            html_handler = _PaletteHtmlHandler(self)
            palette.incomingFromHTML.add(html_handler)
            self._handlers.append(html_handler)
        except RuntimeError as exc:
            # Without this the HTML UI cannot call back into Python, so log loudly
            # rather than failing the whole open.
            via_tenting_dock.log('incomingFromHTML unavailable: %s' % exc)

        # A palette declared in the shell layout is a "native" palette, and Fusion
        # raises "No close event is fired for native palette." Missing this event
        # only means our cached reference outlives a manual close, which is
        # harmless because show() re-adopts by id.
        try:
            closed_handler = _PaletteClosedHandler(self)
            palette.closed.add(closed_handler)
            self._handlers.append(closed_handler)
        except RuntimeError as exc:
            via_tenting_dock.log('closed event unavailable (native palette): %s' % exc)

        self._handlers_attached = True

    def _palette_ids(self) -> list:
        try:
            palettes = self._ui.palettes
            return [palettes.item(i).id for i in range(palettes.count)]
        except Exception:
            return []

    def _try_add(self, url: str, new_browser: bool):
        args = [PALETTE_ID, PALETTE_TITLE, url, True, True, True,
                PALETTE_WIDTH, PALETTE_HEIGHT]
        if new_browser:
            args.append(True)
        try:
            return self._ui.palettes.add(*args)
        except RuntimeError as exc:
            # "Palette with same id has been existed" — the ECAD shell layout
            # declares this palette, so the shell already created it inside its
            # right-docked DockWidget host. Adopt that one; adding a duplicate is
            # impossible and deleting it would give up the dock.
            adopted = self._ui.palettes.itemById(PALETTE_ID)
            via_tenting_dock.log(
                'palettes.add rejected (%s) adopted=%s ids=%s'
                % (exc, adopted is not None, self._palette_ids()))
            if adopted is None:
                raise
            try:
                adopted.htmlFileURL = url
            except Exception:
                pass
            return adopted

    def _add_palette(self):
        url = palette_url(self._resources_dir)
        try:
            palette = self._try_add(url, new_browser=True)
        except TypeError:
            palette = self._try_add(url, new_browser=False)
        self._dock_right_on_create(palette)
        return palette

    def _dock_right_on_create(self, palette) -> None:
        """Dock to the right edge at creation time via the documented API.

        Centralized in via_tenting_dock/palette_dock so docking + logging are
        consistent across the create and reuse paths.
        """
        via_tenting_dock.dock_now(palette, tag='create-sync')

    def _create_palette(self) -> adsk.core.Palette:
        palette = self._add_palette()
        self._attach_handlers(palette)
        via_tenting_dock.on_palette_opened(palette, self._app, self._ui, path='create')
        return palette

    def _reuse_palette(self, palette: adsk.core.Palette) -> None:
        self._palette = palette
        self._attach_handlers(palette)
        # Refresh htmlFileURL so the newest cache-busted HTML/CSS/JS loads. We must
        # NOT delete/re-add the palette: that would surrender the docked host the
        # ECAD shell layout gave it.
        url = palette_url(self._resources_dir)
        try:
            palette.htmlFileURL = url
            via_tenting_dock.log('htmlFileURL wanted=%s readback=%s'
                                 % (url, palette.htmlFileURL))
        except Exception as exc:
            via_tenting_dock.log('htmlFileURL set FAILED: %r (wanted %s)' % (exc, url))
        via_tenting_dock.on_palette_opened(palette, self._app, self._ui, path='reuse')

    def _dispose_palette(self, palette: adsk.core.Palette) -> None:
        if palette and palette.isValid:
            try:
                palette.deleteMe()
            except Exception:
                pass

    def show(self) -> None:
        if self._open_in_progress:
            return

        self._open_in_progress = True
        try:
            via_tenting_dock.log('show: palette ids = %s' % (self._palette_ids(),))
            existing = self._ui.palettes.itemById(PALETTE_ID)
            if existing:
                # The ECAD shell layout declares this palette, so the shell creates
                # it inside its right-docked DockWidget host. Deleting and re-adding
                # would tear it out of that host and leave it floating, so always
                # adopt whatever already exists.
                self._reuse_palette(existing)
            else:
                self._palette = self._create_palette()
        finally:
            self._open_in_progress = False


class _PaletteClosedHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def __init__(self, controller: PaletteController) -> None:
        super().__init__()
        self._controller = controller

    def notify(self, args):
        self._controller._palette = None


class _PaletteHtmlHandler(adsk.core.HTMLEventHandler):
    def __init__(self, controller: PaletteController) -> None:
        super().__init__()
        self._controller = controller
        self._in_progress = False

    def notify(self, args):
        if self._in_progress:
            return
        self._in_progress = True
        controller = self._controller
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            action = html_args.action
            data = html_args.data or ''

            if action == 'cancel':
                controller.close()
                return

            if action == 'scan':
                controller.notify('busy', 'scan')
                adsk.doEvents()
                vias = controller._on_scan()
                layers = getattr(vias, 'layers', None) or []
                if layers:
                    controller._last_visible_layers = list(layers)
                else:
                    layers = controller._last_visible_layers
                summary = {
                    'vias': vias,
                    'layers': layers,
                    'summary': {
                        'total': len(vias),
                    },
                }
                controller.notify('scanResult', json.dumps(summary))
                controller.notify('busy', '')
                adsk.doEvents()
                return

            if action == 'apply':
                try:
                    payload = json.loads(data) if data else {}
                except json.JSONDecodeError:
                    controller.notify('error', 'Invalid apply payload.')
                    return

                mask_mode = str(payload.get('maskMode', 'off')).lower()
                selected_vias = payload.get('vias') or []
                if not isinstance(selected_vias, list):
                    controller.notify('error', 'Invalid via selection payload.')
                    return

                is_all = bool(payload.get('isAll'))
                total_count = payload.get('totalCount')
                visible_layers = payload.get('visibleLayers') or controller._last_visible_layers

                controller.notify('busy', 'apply')
                adsk.doEvents()
                apply_result = controller._on_apply(
                    mask_mode,
                    selected_vias,
                    is_all=is_all,
                    total_count=total_count,
                    visible_layers=visible_layers,
                )
                adsk.doEvents()
                vias = controller._on_scan()
                layers = getattr(vias, 'layers', None) or []
                if layers:
                    controller._last_visible_layers = list(layers)
                else:
                    layers = controller._last_visible_layers
                summary = {
                    'vias': vias,
                    'layers': layers,
                    'summary': {
                        'total': len(vias),
                    },
                }
                limit_updated = bool(
                    isinstance(apply_result, dict) and apply_result.get('mask_limit_updated')
                )
                target_limit = (
                    apply_result.get('target_limit_mil')
                    if isinstance(apply_result, dict)
                    else None
                )
                controller.notify('applyDone', json.dumps({
                    **summary,
                    'appliedCount': len(selected_vias),
                    'maskMode': mask_mode,
                    'maskLimitUpdated': limit_updated,
                    'targetLimitMil': target_limit,
                }))
                controller.notify('busy', '')
                adsk.doEvents()
                return

        except Exception as exc:
            friendly = str(exc).strip()
            if not friendly:
                friendly = 'Via Tenting failed. Open the 2D PCB tab and try again.'
            controller.notify('error', friendly)
            controller.notify('busy', '')
            try:
                import via_tenting_service as vts
                vts._append_log(f'scan/apply error: {friendly}')
            except Exception:
                pass
        finally:
            self._in_progress = False
