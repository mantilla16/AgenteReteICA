"""Ingesta del balance de prueba, limitada a las cuentas de ReteICA.

Trampa del formato: el movimiento del periodo esta en 'Saldo Haber per.inf.'.
'Saldo acumulado' trae el arrastre de todos los periodos anteriores; tomarlo
haria fallar C2 en todos los meses.
"""

from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import FIRMA_BALANCE, ROLES_BALANCE, localizar_columnas
from motor_reteica.parametros.puc import es_cuenta_reteica


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def leer_balance(ruta: Path) -> dict:
    filas = leer_filas(ruta, hoja="BALANCE")
    inicio, col = localizar_columnas(filas, ROLES_BALANCE, FIRMA_BALANCE)

    saldos = {}
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if es_cuenta_reteica(cuenta):
            saldos[cuenta] = Decimal(
                str(fila[col["movimiento_periodo"]] or 0)).copy_abs()
    return saldos
