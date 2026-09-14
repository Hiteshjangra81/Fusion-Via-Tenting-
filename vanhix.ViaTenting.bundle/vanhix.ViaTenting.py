import os
import sys
import tempfile
import traceback
import importlib
import inspect

import adsk.core
import adsk

_contents_dir = os.path.dirname(os.path.realpath(__file__))
if _contents_dir not in sys.path:
    sys.path.insert(0, _contents_dir)

CMD_ID = 'vanhixViaTentingCmd'
CMD_NAME = 'Via Tenting'
CMD_DESC = 'List all PCB vias and bulk-set solder mask on the open Fusion Electronics board.'
OWNER_NAME = 'VanHix'
OWNER_EMAIL = 'support@vanhix.com'

SUPPORTED_WORKSPACES = frozenset({
    'ElectronPcbEnvironment',
    'BoardLayoutEnvironement',
})

BUTTON_TARGETS = (
    ('ElectronPcbEnvironment', 'PcbUtilTab', 'EaglePcbScriptsAddinsPanel', 'ScriptsManagerCommand'),
    ('ElectronPcbEnvironment', 'PcbDocTab', 'EaglePcbScriptsAddinsPanel', 'ScriptsManagerCommand'),
    ('ElectronPcbEnvironment', 'ToolsTab', 'EaglePcbScriptsAddinsPanel', 'ScriptsManagerCommand'),
    ('ElectronPcbEnvironment', 'UtilTab', 'EaglePcbScriptsAddinsPanel', 'ScriptsManagerCommand'),
    ('ElectronPcbEnvironment', 'UtilitiesTab', 'EaglePcbScriptsAddinsPanel', 'ScriptsManagerCommand'),
    ('ElectronPcbEnvironment', 'ElectronUtilTab', 'EaglePcbScriptsAddinsPanel', 'ScriptsManagerCommand'),
)

_PCB_WORKSPACE_IDS = (
    'ElectronPcbEnvironment',
    'BoardLayoutEnvironement',
)

_PCB_ADDINS_PANEL_IDS = (
    'EaglePcbScriptsAddinsPanel',
)

_handlers = []
_controls = []
_registered_targets = set()
_cmd_def = None
_palette = None

_app = adsk.core.Application.get()
_ui = _app.userInterface
_RESOURCES = os.path.join(_contents_dir, 'resources')
_ICON_FOLDER = os.path.join(_RESOURCES, 'icons')
_STARTUP_LOG = os.path.join(tempfile.gettempdir(), 'vanhix_via_tenting_startup.log')

_via_tenting_service = None
_palette_controller = None
_via_tenting_dock = None
_ulp_runner = None
_stage_and_run_ulp = None
_run_ecad_script = None
_ULP_FILE = os.path.join(_RESOURCES, 'ViaTenting.ulp')
_BUNDLE_MODULES = (
    'via_tenting_service',
    'via_tenting_dock',
    'via_tenting_palette',
    'ulp_runner',
    'via_tenting_palette_dock',
    'palette_dock',
    'palette_dock_ui',
)


def _import_bundle_module(name: str):
    module = sys.modules.get(name)
    if module is not None:
        return importlib.reload(module)
    return importlib.import_module(name)


def _ensure_ecad_runners(force: bool = False):
    global _ulp_runner, _stage_and_run_ulp, _run_ecad_script

    if not force and _stage_and_run_ulp is not None and _run_ecad_script is not None:
        return

    ur = _import_bundle_module('ulp_runner')
    vts = _import_bundle_module('via_tenting_service')

    runner_kwargs = {}
    if 'log_command' in inspect.signature(ur.make_ecad_runners).parameters:
        runner_kwargs['log_command'] = (
            lambda command: vts._append_log(f'ulp command={command}')
        )

    _ulp_runner = ur
    _stage_and_run_ulp, _run_ecad_script = ur.make_ecad_runners(
        lambda command: _app.executeTextCommand(command),
        **runner_kwargs,
    )


def _lazy_modules():
    global _via_tenting_service, _palette_controller, _via_tenting_dock

    if _via_tenting_dock is None or _palette_controller is None:
        _via_tenting_dock = _import_bundle_module('via_tenting_dock')
        _palette_controller = _import_bundle_module('via_tenting_palette')

    _via_tenting_service = _import_bundle_module('via_tenting_service')
    _ensure_ecad_runners(force=True)
    return _via_tenting_service, _palette_controller, _via_tenting_dock


def _startup_log(message: str) -> None:
    try:
        with open(_STARTUP_LOG, 'a', encoding='utf-8') as handle:
            handle.write(message.rstrip() + '\n')
    except OSError:
        pass


def _icon_folder_for_command() -> str:
    if os.path.isdir(_ICON_FOLDER) and os.path.isfile(os.path.join(_ICON_FOLDER, '32x32.png')):
        return _ICON_FOLDER
    _startup_log(f'icon folder missing or incomplete: {_ICON_FOLDER}')
    return ''


def _safe_delete(obj):
    try:
        if obj and obj.isValid:
            obj.deleteMe()
    except Exception:
        pass


def _ensure_pcb_workspace():
    if _ui.activeWorkspace.id not in SUPPORTED_WORKSPACES:
        _ui.messageBox(
            'Open a 2D PCB board in Fusion Electronics before running Via Tenting.',
            CMD_NAME,
        )
        return False
    return True


def _on_scan():
    service, _, _ = _lazy_modules()
    if _stage_and_run_ulp is None:
        raise RuntimeError(
            'Via Tenting ECAD runner is not initialized. Stop and Run the add-in, then Refresh.'
        )
    return service.scan_vias(_ULP_FILE, _stage_and_run_ulp)


def _on_apply(mask_mode: str, selected_vias=None, is_all=False, total_count=None, visible_layers=None):
    service, _, _ = _lazy_modules()
    if _stage_and_run_ulp is None or _run_ecad_script is None:
        raise RuntimeError(
            'Via Tenting ECAD runner is not initialized. Stop and Run the add-in, then try again.'
        )
    return service.apply_soldermask(
        mask_mode,
        _run_ecad_script,
        selected_vias or [],
        is_all=is_all,
        total_count=total_count,
        visible_layers=visible_layers,
    )


def _on_error(details):
    _ui.messageBox(
        f'Failed to run {OWNER_NAME} Via Tenting:\n{details}',
        CMD_NAME,
    )


def _get_palette():
    global _palette
    _, palette_controller, _ = _lazy_modules()
    if _palette is None:
        _palette = palette_controller.PaletteController(
            app=_app,
            ui=_ui,
            resources_dir=_RESOURCES,
            handlers=_handlers,
            on_scan=_on_scan,
            on_apply=_on_apply,
            on_error=_on_error,
        )
    return _palette


def _show_palette():
    if not _ensure_pcb_workspace():
        return
    _get_palette().show()


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _lazy_modules()
            _show_palette()
        except Exception:
            _on_error(traceback.format_exc())


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        handler = CommandExecuteHandler()
        args.command.execute.add(handler)
        _handlers.append(handler)


def _resolve_panel(workspace, tab_id, panel_id):
    tab = workspace.toolbarTabs.itemById(tab_id)
    if tab:
        panel = tab.toolbarPanels.itemById(panel_id)
        if panel:
            return panel
    return workspace.toolbarPanels.itemById(panel_id)


def _ensure_command_definition():
    global _cmd_def

    if _cmd_def and _cmd_def.isValid:
        return _cmd_def

    existing = _ui.commandDefinitions.itemById(CMD_ID)
    if existing and existing.isValid:
        _cmd_def = existing
        return _cmd_def

    _cmd_def = _ui.commandDefinitions.addButtonDefinition(
        CMD_ID,
        CMD_NAME,
        f'{CMD_DESC} ({OWNER_NAME})',
        _icon_folder_for_command(),
    )

    created_handler = CommandCreatedHandler()
    _cmd_def.commandCreated.add(created_handler)
    _handlers.append(created_handler)
    return _cmd_def


def _add_command_to_panel(panel, position_after):
    if not panel:
        return False

    cmd_def = _ensure_command_definition()
    control = panel.controls.itemById(CMD_ID)
    created = False
    if not control:
        try:
            if position_after:
                control = panel.controls.addCommand(cmd_def, position_after, False)
            else:
                control = panel.controls.addCommand(cmd_def)
        except Exception:
            try:
                control = panel.controls.addCommand(cmd_def)
            except Exception:
                return False
        created = True

    control.isPromoted = True
    control.isPromotedByDefault = True
    if created:
        _controls.append(control)
    return True


def _register_button(workspace_id, tab_id, panel_id, position_after):
    target_key = (workspace_id, tab_id, panel_id)
    if target_key in _registered_targets:
        return True

    workspace = _ui.workspaces.itemById(workspace_id)
    if not workspace:
        return False

    panel = _resolve_panel(workspace, tab_id, panel_id)
    if not panel:
        return False

    if not _add_command_to_panel(panel, position_after):
        return False

    _registered_targets.add(target_key)
    return True


def _discover_and_register_pcb_buttons():
    registered = 0

    for target in BUTTON_TARGETS:
        if _register_button(*target):
            registered += 1

    for workspace_id in _PCB_WORKSPACE_IDS:
        workspace = _ui.workspaces.itemById(workspace_id)
        if not workspace:
            continue
        for tab_index in range(workspace.toolbarTabs.count):
            tab = workspace.toolbarTabs.item(tab_index)
            for panel_id in _PCB_ADDINS_PANEL_IDS:
                panel = tab.toolbarPanels.itemById(panel_id)
                if panel and _add_command_to_panel(panel, 'ScriptsManagerCommand'):
                    target_key = (workspace_id, tab.id, panel_id)
                    if target_key not in _registered_targets:
                        _registered_targets.add(target_key)
                        registered += 1

    try:
        for panel_index in range(_ui.allToolbarPanels.count):
            panel = _ui.allToolbarPanels.item(panel_index)
            if panel.id not in _PCB_ADDINS_PANEL_IDS:
                continue
            if _add_command_to_panel(panel, 'ScriptsManagerCommand'):
                target_key = ('allToolbarPanels', panel.id, str(panel_index))
                if target_key not in _registered_targets:
                    _registered_targets.add(target_key)
                    registered += 1
    except Exception:
        pass

    return registered


def _on_ui_context_changed():
    _discover_and_register_pcb_buttons()


class WorkspaceActivatedHandler(adsk.core.WorkspaceEventHandler):
    def notify(self, args):
        _on_ui_context_changed()


class DocumentActivatedHandler(adsk.core.DocumentEventHandler):
    def notify(self, args):
        _on_ui_context_changed()


def _cleanup_controls():
    global _cmd_def, _controls, _registered_targets

    for control in _controls:
        _safe_delete(control)

    _controls = []
    _registered_targets = set()
    _safe_delete(_cmd_def)
    _cmd_def = None


def _purge_stale_palette():
    for palette_id in ('vanhixViaTentingPalette',):
        existing = _ui.palettes.itemById(palette_id)
        if existing and existing.isValid:
            try:
                existing.deleteMe()
            except Exception:
                pass


def run(context):
    try:
        with open(_STARTUP_LOG, 'w', encoding='utf-8') as handle:
            handle.write('==== VanHix Via Tenting startup ====\n')

        _startup_log(f'contents_dir={_contents_dir}')
        _startup_log(f'icon_folder={_icon_folder_for_command()}')

        # Do not purge existing palette on startup — preserves right-docked layout in Fusion.
        _ensure_command_definition()
        _startup_log('command definition ok')

        try:
            _, _, via_tenting_dock = _lazy_modules()
            if via_tenting_dock.install(_app, _ui, _handlers):
                _startup_log('dock install ok')
            else:
                _startup_log('dock install skipped (palette will float)')
        except Exception as exc:
            _startup_log(f'dock install failed: {exc!r}')

        workspace_handler = WorkspaceActivatedHandler()
        document_handler = DocumentActivatedHandler()
        _ui.workspaceActivated.add(workspace_handler)
        _app.documentActivated.add(document_handler)
        _handlers.extend([workspace_handler, document_handler])

        registered = _discover_and_register_pcb_buttons()
        _startup_log(f'toolbar buttons registered={registered}')
    except Exception:
        _startup_log(traceback.format_exc())
        _ui.messageBox(
            f'{OWNER_NAME} {CMD_NAME} failed to start:\n{traceback.format_exc()}\n\n'
            f'Support: {OWNER_EMAIL}',
            CMD_NAME,
        )


def stop(context):
    global _handlers, _palette, _stage_and_run_ulp, _run_ecad_script, _ulp_runner
    global _via_tenting_service, _palette_controller, _via_tenting_dock

    if _palette is not None:
        _palette.close()
        _palette = None

    try:
        if _via_tenting_dock is not None:
            _via_tenting_dock.uninstall(_app)
    except Exception:
        pass

    _stage_and_run_ulp = None
    _run_ecad_script = None
    _ulp_runner = None
    _via_tenting_service = None
    _palette_controller = None
    _via_tenting_dock = None
    for module_name in _BUNDLE_MODULES:
        sys.modules.pop(module_name, None)

    _cleanup_controls()
    _handlers = []
