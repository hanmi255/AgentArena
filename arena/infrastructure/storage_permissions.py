"""Repair Windows read-only flags on this application's SQLite runtime files."""

import logging
import os
import stat
from pathlib import Path

LOGGER = logging.getLogger(__name__)
SQLITE_FILES = tuple(
    database + suffix
    for database in ("arena.sqlite", "checkpoints.sqlite")
    for suffix in ("", "-wal", "-shm")
)


def prepare_sqlite_files(directory: Path) -> list[Path]:
    """Only clear the Windows file attribute; never change ACLs or POSIX modes."""
    repaired = []
    if os.name != "nt":
        return repaired
    for name in SQLITE_FILES:
        path = directory / name
        try:
            info = path.stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY:
            try:
                path.chmod(info.st_mode | stat.S_IWRITE)
            except PermissionError as error:
                raise PermissionError(
                    f"无法解除 SQLite 文件只读属性：{path}。请检查当前账号对此文件的写入权限。"
                ) from error
            repaired.append(path)
            LOGGER.warning("已解除 SQLite 运行文件的只读属性：%s", path)
    return repaired
