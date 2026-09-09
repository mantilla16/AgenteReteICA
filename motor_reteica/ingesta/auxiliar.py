"""Ingesta del libro auxiliar de la cuenta 2368.

Trampa del formato: la columna 'Asignacion' trae el NIT y 'Tercero' el nombre,
no al reves. Los importes vienen negativos (naturaleza credito) y se normalizan
a positivo. Las filas de totales ('*' y '**') no traen cuenta y se descartan.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import FIRMA_AUXILIAR, ROLES_AUXILIAR, localizar_columnas
from motor_reteica.parametros.puc import es_cuenta_reteica
from motor_reteica.tipos import LineaAuxiliar


def _a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.strptime(str(valor).strip(), "%d.%m.%Y").date()


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def leer_auxiliar(ruta: Path) -> list:
    filas = leer_filas(ruta)
    inicio, col = localizar_columnas(filas, ROLES_AUXILIAR, FIRMA_AUXILIAR)

    lineas = []
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if not es_cuenta_reteica(cuenta):
            continue
        lineas.append(LineaAuxiliar(
            cuenta=cuenta,
            nit=_texto(fila[col["nit"]]),
            tercero=_texto(fila[col["nombre"]]),
            fecha_documento=_a_fecha(fila[col["fecha_documento"]]),
            fecha_contabilizacion=_a_fecha(fila[col["fecha_contabilizacion"]]),
            referencia=_texto(fila[col["referencia"]]),
            documento=_texto(fila[col["documento"]]),
            concepto=_texto(fila[col["concepto"]]),
            retencion=Decimal(str(fila[col["importe"]])).copy_abs(),
        ))
    return lineas
