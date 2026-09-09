"""Lectura cruda de filas de un XLSX. Sin parametrizacion ni tipos: eso lo
resuelve parametros/columnas.py sobre el resultado de aqui.
"""

from pathlib import Path

import openpyxl


def leer_filas(ruta: Path, hoja: str = None) -> list:
    libro = openpyxl.load_workbook(ruta, data_only=True)
    pagina = libro[hoja] if hoja and hoja in libro.sheetnames else libro.worksheets[0]
    return list(pagina.iter_rows(values_only=True))
