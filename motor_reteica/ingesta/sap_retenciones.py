"""Ingesta del reporte de retenciones del ERP (S_P00_07000134).

El reporte se titula 'RETENCION IVA COLOMBIA' aunque el extracto sea de ICA:
el titulo es de la transaccion, no del impuesto. La base sujeta es
'Impte.base Qst en MI', no 'Importe en MD', que viene con IVA incluido.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import FIRMA_ERP, ROLES_ERP, localizar_columnas


@dataclass(frozen=True)
class RetencionERP:
    nit: str
    codigo_ret: str
    base: Decimal
    retencion: Decimal


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def leer_sap_retenciones(ruta: Path) -> list:
    filas = leer_filas(ruta)
    inicio, col = localizar_columnas(filas, ROLES_ERP, FIRMA_ERP)

    resultado = []
    for fila in filas[inicio + 1:]:
        nit = _texto(fila[col["nit"]])
        codigo = _texto(fila[col["codigo_ret"]])
        if not nit or not codigo:
            continue  # fila de totales
        resultado.append(RetencionERP(
            nit=nit,
            codigo_ret=codigo,
            base=Decimal(str(fila[col["base"]])).copy_abs(),
            retencion=Decimal(str(fila[col["retencion"]])).copy_abs(),
        ))
    return resultado
