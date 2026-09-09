"""Resolucion de rutas a recursos NO-.py (el frontend web).

Corriendo como codigo normal, el frontend esta junto al codigo. Empaquetado
con PyInstaller (--onefile), se extrae a un directorio temporal cuya ruta
esta en sys._MEIPASS. Este helper devuelve la ruta correcta en ambos casos.
"""

import sys
from pathlib import Path


def _base() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def ruta_recurso(*partes: str) -> Path:
    return _base().joinpath(*partes)
