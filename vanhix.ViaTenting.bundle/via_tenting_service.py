"""
Via Tenting core bridge — scan vias via ULP and bulk-apply solder mask via ECAD script.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Callable, Mapping, Optional, Sequence

ULP_MODE_SCAN = 'SCAN'
SCAN_OUTPUT_FILENAME = 'vanhix_via_tenting_scan.json'
SCAN_OUTPUT_POLL_ATTEMPTS = 40
SCAN_OUTPUT_POLL_DELAY_SEC = 0.05
TARGET_MASK_LIMIT_MIL = 999

SUPPORTED_MASK_MODES = frozenset({'auto', 'off', 'offset', 'on'})

# Layer 23 (tOrigins) and Layer 24 (bOrigins) were deprecated/removed by Autodesk
# in Fusion 360 Electronics (Jan 2024 update). Passing them to DISPLAY triggers
# an 'unavailable layer' error popup in Fusion.
DEPRECATED_FUSION_LAYERS = frozenset({0, 23, 24})

# Eagle CHANGE STOP accepts only ON | OFF (no AUTO/OFFSET in syntax). Fusion requires vias to be
# grouped/selected before CHANGE STOP — per-coordinate clicks do not update Inspector.
_CHANGE_STOP_KEYWORDS = {
    'off': 'OFF',
    'auto': 'ON',
    'offset': 'ON',
    'on': 'ON',
}
# Keep batches small: each batch is GROUP + CHANGE + right-click apply.
_CHANGE_BATCH_SIZE = 30


def log_file_path() -> str:
    return os.path.join(tempfile.gettempdir(), 'vanhix_via_tenting.log')


def scan_output_path() -> str:
    return os.path.join(tempfile.gettempdir(), SCAN_OUTPUT_FILENAME)


def _append_log(message: str) -> None:
    try:
        with open(log_file_path(), 'a', encoding='utf-8') as handle:
            handle.write(message.rstrip() + '\n')
    except OSError:
        pass


def _remove_scan_output(path: str) -> None:
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _wait_for_scan_output(output_path: str) -> None:
    for _ in range(SCAN_OUTPUT_POLL_ATTEMPTS):
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            return
        time.sleep(SCAN_OUTPUT_POLL_DELAY_SEC)


class ViaList(list):
    """List of via dictionaries with attached visible board layers list."""
    def __init__(self, items=(), layers=()):
        super().__init__(items)
        self.layers = list(layers)


def _read_scan_results(output_path: str) -> ViaList:
    if not os.path.exists(output_path):
        raise ValueError(
            'Via scan did not run. Open the 2D PCB tab, then click Refresh again.'
        )

    file_size = os.path.getsize(output_path)
    _append_log(f'scan output bytes={file_size}')

    with open(output_path, 'r', encoding='utf-8') as handle:
        raw = handle.read().strip()

    if not raw:
        _append_log('scan output empty')
        raise ValueError(
            'Via scan returned an empty file. Open the 2D PCB tab, then click Refresh again.'
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        preview = raw[:160].replace('\n', '\\n')
        _append_log(f'scan output invalid json preview={preview!r}')
        raise ValueError(f'Via scan returned invalid JSON: {exc}') from exc

    layers = []
    if isinstance(payload, dict):
        if not payload.get('ok'):
            error = payload.get('error', 'unknown')
            if error == 'no_active_board':
                raise ValueError(
                    'No active PCB board for scan. Click the 2D PCB tab, then Refresh.'
                )
            raise ValueError(f'Via scan failed: {error}')
        layers = [int(l) for l in payload.get('layers', []) if isinstance(l, (int, float))]
        payload = payload.get('vias', [])

    if not isinstance(payload, list):
        raise ValueError('Via scan returned invalid data.')

    vias = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        vias.append({
            'index': index,
            'x': float(item.get('x', 0.0)),
            'y': float(item.get('y', 0.0)),
            'drill': float(item.get('drill', 0.0)),
            'net': str(item.get('net', '')),
            'start': int(item.get('start', 0)),
            'end': int(item.get('end', 0)),
            'flags': int(item.get('flags', 0)),
            'mask': str(item.get('mask', 'auto')),
        })
    return ViaList(vias, layers=layers)


def scan_vias(
    ulp_path: str,
    stage_and_run_ulp: Callable[[str, Sequence], None],
) -> list[dict]:
    if stage_and_run_ulp is None:
        raise ValueError(
            'Via scan runner is not available. Stop and Run the add-in, then Refresh.'
        )
    if not os.path.isfile(ulp_path):
        raise FileNotFoundError(f'Via Tenting ULP not found: {ulp_path}')

    json_path = scan_output_path()
    _remove_scan_output(json_path)

    try:
        output_arg = json_path.replace('\\', '/')
        _append_log(f'scan start output={output_arg}')
        stage_and_run_ulp(ulp_path, (ULP_MODE_SCAN, output_arg))
        _wait_for_scan_output(json_path)
        vias = _read_scan_results(json_path)
        _append_log(f'scan complete count={len(vias)}')
        _remove_scan_output(json_path)
        return vias
    except Exception:
        if os.path.exists(json_path):
            _append_log(
                f'scan failed output={json_path} bytes={os.path.getsize(json_path)}'
            )
        raise


def _format_single_via_change(keyword: str, x: float, y: float) -> list[str]:
    # Use a small closed 5-point bounding box (50 um around via center).
    # Center (x, y) is strictly inside. With Layer 18 isolated (DISPLAY NONE 18),
    # no other tracks/pads/polygons can be selected.
    d = 0.05
    x1, y1 = x - d, y - d
    x2, y2 = x + d, y + d
    return [
        f'GROUP ({x1:.6f} {y1:.6f}) ({x2:.6f} {y1:.6f}) ({x2:.6f} {y2:.6f}) ({x1:.6f} {y2:.6f}) ({x1:.6f} {y1:.6f});',
        f'CHANGE STOP {keyword} (C> {x:.6f} {y:.6f});',
        f'CHANGE STOP {keyword} ({x:.6f} {y:.6f});',
    ]


def is_mask_limit_target(val_str: str, target_mil: int) -> bool:
    cleaned = str(val_str or '').strip().lower()
    if not cleaned:
        return False
    if target_mil == 0:
        if cleaned in ('0', '0mil', '0.0', '0.0mil', '0mm', '0.0mm', '0inch', '0.0inch'):
            return True
    elif target_mil >= 999:
        if cleaned.startswith('999'):
            return True

    match = re.match(r'^([0-9.]+)\s*(mil|mm|inch)?$', cleaned)
    if match:
        try:
            num = float(match.group(1))
            unit = match.group(2) or 'mil'
            if target_mil == 0:
                return num == 0.0
            if unit == 'mil' and num >= target_mil:
                return True
            if unit == 'inch' and num >= (target_mil / 1000.0):
                return True
            if unit == 'mm' and num >= (target_mil * 0.0254):
                return True
        except ValueError:
            pass
    return False


def is_mask_limit_999(val_str: str) -> bool:
    return is_mask_limit_target(val_str, TARGET_MASK_LIMIT_MIL)


def update_dru_mask_limit(content: str, target_mil: int = TARGET_MASK_LIMIT_MIL) -> tuple[str, bool]:
    """
    Check and update mlViaStopLimit in .dru content.
    Returns (updated_content, was_modified).
    """
    plain_pattern = re.compile(r'^(mlViaStopLimit\s*=\s*)([^\r\n;]+)', re.MULTILINE)
    xml_pattern = re.compile(r'(<param\s+name="mlViaStopLimit"\s+value=")([^"]+)(")', re.IGNORECASE)

    plain_match = plain_pattern.search(content)
    if plain_match:
        current_val = plain_match.group(2).strip()
        if is_mask_limit_target(current_val, target_mil):
            return content, False
        updated = plain_pattern.sub(rf'\g<1>{target_mil}mil', content, count=1)
        return updated, True

    xml_match = xml_pattern.search(content)
    if xml_match:
        current_val = xml_match.group(2).strip()
        if is_mask_limit_target(current_val, target_mil):
            return content, False
        updated = xml_pattern.sub(rf'\g<1>{target_mil}mil\3', content, count=1)
        return updated, True

    # If mlViaStopLimit not found, append it
    separator = '\n' if content.endswith('\n') else '\n\n'
    return f'{content.rstrip()}{separator}mlViaStopLimit = {target_mil}mil\n', True


def prepare_mask_limit_update(
    run_ecad_script: Callable[[str], None],
    target_mil: int = TARGET_MASK_LIMIT_MIL,
) -> tuple[bool, Optional[str]]:
    temp_dir = tempfile.gettempdir()
    base_name = 'vanhix_via_tenting_rules'
    base_path = os.path.join(temp_dir, base_name)
    dru_path = base_path + '.dru'

    for p in (base_path, dru_path, dru_path + '.dru'):
        _remove_scan_output(p)

    # Use single quotes for EAGLE script parser (double quotes are treated as literal characters)
    normalized = base_path.replace('\\', '/')
    _append_log(f'drc save start file={normalized}')
    try:
        run_ecad_script(f"DRC SAVE '{normalized}';")
    except Exception as exc:
        _append_log(f'drc save script error: {exc!r}')
        return False, None

    actual_path = None
    for _ in range(30):
        if os.path.isfile(dru_path) and os.path.getsize(dru_path) > 0:
            actual_path = dru_path
            break
        if os.path.isfile(base_path) and os.path.getsize(base_path) > 0:
            actual_path = base_path
            break
        if os.path.isfile(dru_path + '.dru') and os.path.getsize(dru_path + '.dru') > 0:
            actual_path = dru_path + '.dru'
            break
        time.sleep(0.05)

    if not actual_path:
        _append_log('drc save output not generated')
        return False, None

    try:
        with open(actual_path, 'r', encoding='utf-8', errors='ignore') as handle:
            content = handle.read()

        new_content, modified = update_dru_mask_limit(content, target_mil)
        if not modified:
            _append_log(f'drc mask limit already >= {target_mil} mil')
            _remove_scan_output(actual_path)
            return False, None

        with open(actual_path, 'w', encoding='utf-8') as handle:
            handle.write(new_content)

        _append_log(f'drc mask limit updated to {target_mil} mil in {actual_path}')
        return True, actual_path
    except Exception as exc:
        _append_log(f'drc modify failed: {exc!r}')
        _remove_scan_output(actual_path)
        return False, None


def build_apply_script(
    mask_mode: str,
    vias: Sequence[Mapping],
    dru_path_to_load: Optional[str] = None,
    is_all: bool = False,
    visible_layers: Optional[Sequence[int]] = None,
) -> str:
    normalized = (mask_mode or 'off').strip().lower()
    if normalized not in SUPPORTED_MASK_MODES:
        raise ValueError(f'Unsupported solder mask mode: {mask_mode}')

    keyword = _CHANGE_STOP_KEYWORDS[normalized]
    lines = [
        'SET CONFIRM OFF;',
    ]
    if dru_path_to_load:
        dru_arg = dru_path_to_load.replace('\\', '/')
        lines.append(f"DRC LOAD '{dru_arg}';")

    lines.append('GRID mm;')
    # Isolate Layer 18 (Vias) so no wires, pads, or polygons on Layer 1/16 interfere with selection
    lines.append('DISPLAY NONE 18;')
    lines.append('GROUP;')

    # When all vias on the board are being changed, execute GROUP ALL for complete bulk coverage
    if is_all:
        lines.append('GROUP ALL;')
        lines.append(f'CHANGE STOP {keyword} (C> 0 0);')
        if vias:
            first_x = float(vias[0].get('x', 0.0))
            first_y = float(vias[0].get('y', 0.0))
            lines.append(f'CHANGE STOP {keyword} (C> {first_x:.6f} {first_y:.6f});')

    # Apply to each via individually using a tiny closed bounding box and direct click
    for via in vias:
        x = float(via.get('x', 0.0))
        y = float(via.get('y', 0.0))
        lines.extend(_format_single_via_change(keyword, x, y))

    lines.append('GROUP;')
    lines.append('DISPLAY LAST;')
    # Explicitly turn back on the recent visible layers (since DISPLAY LAST can be ignored in Fusion)
    if visible_layers:
        clean_layers = [
            int(l) for l in visible_layers
            if int(l) > 0 and int(l) not in DEPRECATED_FUSION_LAYERS
        ]
        if clean_layers:
            layers_str = ' '.join(str(l) for l in sorted(set(clean_layers)))
            lines.append(f'DISPLAY NONE {layers_str};')
    else:
        # Fallback to modern standard 2D PCB layers (excluding deprecated 23 tOrigins and 24 bOrigins)
        default_layers = '1 16 17 18 19 20 21 22 25 26 27 28 29 30 31 32 39 40 41 42 43 44 45 46 47 48 49 51 52'
        lines.append(f'DISPLAY NONE {default_layers};')

    lines.append('GRID LAST;')
    return '\n'.join(lines)


def apply_soldermask(
    mask_mode: str,
    run_ecad_script: Callable[[str], None],
    selected_vias: Sequence[Mapping],
    is_all: bool = False,
    total_count: Optional[int] = None,
    visible_layers: Optional[Sequence[int]] = None,
) -> dict:
    if run_ecad_script is None:
        raise ValueError(
            'Apply runner is not available. Stop and Run the add-in, then try again.'
        )

    normalized = (mask_mode or 'off').strip().lower()
    if normalized not in SUPPORTED_MASK_MODES:
        raise ValueError(f'Unsupported solder mask mode: {mask_mode}')

    if not selected_vias:
        raise ValueError('Select at least one via group before applying.')

    is_all_vias = bool(
        is_all or (total_count is not None and total_count > 0 and len(selected_vias) >= total_count)
    )
    _append_log(f'apply mode={normalized} selected={len(selected_vias)} is_all={is_all_vias}')

    target_mil = None
    if normalized in ('off', 'auto', 'on'):
        target_mil = TARGET_MASK_LIMIT_MIL

    mask_limit_updated = False
    dru_to_load = None
    if target_mil is not None:
        mask_limit_updated, dru_to_load = prepare_mask_limit_update(
            run_ecad_script,
            target_mil,
        )

    try:
        script = build_apply_script(
            normalized,
            selected_vias,
            dru_path_to_load=dru_to_load,
            is_all=is_all_vias,
            visible_layers=visible_layers,
        )
        _append_log(script)
        run_ecad_script(script)
        _append_log('apply complete')
    finally:
        if dru_to_load:
            _remove_scan_output(dru_to_load)

    return {
        'mask_limit_updated': mask_limit_updated,
        'target_limit_mil': target_mil,
    }


def summarize_vias(vias: Sequence[Mapping]) -> dict:
    counts = {'auto': 0, 'off': 0, 'offset': 0, 'other': 0}
    drills = set()

    for via in vias:
        mask = str(via.get('mask', 'auto')).lower()
        if mask == 'on':
            mask = 'auto'
        if mask in counts:
            counts[mask] += 1
        else:
            counts['other'] += 1
        drill = via.get('drill')
        if isinstance(drill, (int, float)):
            drills.add(round(float(drill), 4))

    return {
        'total': len(vias),
        'maskCounts': counts,
        'uniqueDrills': sorted(drills),
    }
