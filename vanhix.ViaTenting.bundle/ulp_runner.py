"""
Fusion ECAD ULP runner — shared execution path for Via Tenting add-in.

Quoting matches Fusion_PCB_Panelization_Addin and Drill Legend: only quote
paths/args that contain spaces; never wrap every Windows ``C:`` path in quotes.
"""

from __future__ import annotations

import os
import tempfile
from typing import Callable, Sequence


def _write_temp_file(suffix: str, content: str, prefix: str = 'vanhix_viatenting_') -> str:
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix=suffix,
        prefix=prefix,
        delete=False,
        encoding='utf-8',
    ) as temp_file:
        temp_file.write(content)
        return temp_file.name


def _remove_temp_file(path: str) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _quote_eagle_path(path: str) -> str:
    normalized = path.replace('\\', '/')
    return f'"{normalized}"' if ' ' in normalized else normalized


def _format_ulp_arg(value) -> str:
    text = str(value)
    if any(character in text for character in (' ', '\t', "'", '"')):
        return "'" + text.replace("'", "\\'") + "'"
    return text


def make_ecad_runners(
    run_script: Callable[[str], None],
    log_command: Callable[[str], None] | None = None,
):
    """Return (stage_and_run_ulp, run_ecad_script)."""

    def _log_command(command: str) -> None:
        if log_command:
            try:
                log_command(command)
            except Exception:
                pass

    def _run_eagle_script(script: str) -> None:
        wrapped = 'SET CONFIRM OFF;\nSET UNDO_LOG OFF;\n' + script.strip() + '\n'
        temp_path = _write_temp_file('.scr', wrapped)
        try:
            run_script(f'Electron.runScript "{temp_path.replace(chr(92), "/")}"')
        finally:
            _remove_temp_file(temp_path)

    def stage_and_run_ulp(source_ulp: str, args: Sequence) -> None:
        with open(source_ulp, 'r', encoding='utf-8') as handle:
            ulp_content = handle.read()

        temp_path = _write_temp_file('.ulp', ulp_content)
        try:
            arg_string = ' '.join(_format_ulp_arg(arg) for arg in args)
            command = f'RUN {_quote_eagle_path(temp_path)}'
            if arg_string:
                command += f' {arg_string}'
            command += ';'
            _log_command(command)
            _run_eagle_script(command)
        finally:
            _remove_temp_file(temp_path)

    def run_ecad_script(commands: str) -> None:
        _run_eagle_script(commands)

    return stage_and_run_ulp, run_ecad_script
