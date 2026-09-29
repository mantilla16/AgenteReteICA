"""Bateria de cuadres deterministicos que VALIDA un mapeo detectado.

Es la pieza que convierte esto en automatizacion y no en un formulario: un
mapeo (Deteccion) no se cree porque un humano lo confirme, sino porque la
aritmetica no lo puede desmentir. Si un mapeo pasa todos los cuadres, las
columnas estan bien con certeza practica -- no hay forma de que la columna
equivocada cuadre a la vez el totalizador del propio archivo Y el cruce contra
el balance. Si un cuadre falla, el motor NO produce papel: devuelve que fallo y
sobre que rol, para que el wizard pregunte solo por eso.

Los cuadres trabajan sobre las filas CRUDAS + la Deteccion, ANTES de construir
el modelo canonico: primero se valida que el mapeo sea de fiar, despues se lee.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from motor_reteica.ingesta.deteccion import Deteccion, _a_decimal, _PUC_RETEICA

# Redondeo de SAP y del papel: hasta mil pesos de diferencia se tolera.
_TOLERANCIA = Decimal("1000")


@dataclass(frozen=True)
class Cuadre:
    nombre: str
    cuadra: bool
    esperado: Decimal | None
    obtenido: Decimal | None
    rol_implicado: str          # que rol revisar si NO cuadra (para el wizard)
    detalle: str

    @property
    def diferencia(self):
        if self.esperado is None or self.obtenido is None:
            return None
        return (self.obtenido - self.esperado).copy_abs()


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor)) if valor is not None else ""


def _es_fila_detalle(fila, d: Deteccion) -> bool:
    """Una transaccion real, no una fila de subtotal/padre/jerarquia."""
    col_cuenta = d.columnas.get("cuenta")
    if col_cuenta is None or col_cuenta >= len(fila):
        return False

    # Con jerarquia (SAP B1): la marca de Serie decide. Es lo mas fiable.
    if d.filtro_transaccion is not None:
        col, marca = d.filtro_transaccion
        return col < len(fila) and str(fila[col]).strip() == marca

    # Sin jerarquia: la cuenta tiene que ser una sub-cuenta ICA de detalle
    # (cuelga de 2368 y trae sufijo), no la fila padre "2368"/"23680503" ni un
    # subtotal de texto ("Cuenta 2368010005 - ...", "* Subtotal 2 236801").
    celda = fila[col_cuenta]
    if isinstance(celda, str) and not celda.strip().replace("-", "").isdigit():
        return False
    dig = _digitos(celda)
    return dig.startswith(_PUC_RETEICA) and len(dig) >= len(_PUC_RETEICA) + 4


def _columna_retencion(d: Deteccion) -> str | None:
    """El rol que carga la retencion practicada segun la convencion de signo."""
    if d.convencion_signo == "columnas_separadas":
        return "credito" if "credito" in d.columnas else None
    return "importe" if "importe" in d.columnas else None


def _suma_detalle(filas, d: Deteccion, rol: str) -> Decimal:
    col = d.columnas.get(rol)
    if col is None:
        return Decimal("0")
    total = Decimal("0")
    for fila in filas[d.fila_encabezado + 1:]:
        if not _es_fila_detalle(fila, d):
            continue
        if col < len(fila):
            v = _a_decimal(fila[col])
            if v is not None:
                total += v.copy_abs()
    return total


def _totalizador_del_archivo(filas, d: Deteccion, rol: str):
    """Busca la fila de total que el propio export trae y lee su columna `rol`.

    Estrategia: entre las filas que NO son detalle, la que trae el mayor valor
    absoluto en la columna del rol es el totalizador (la fila padre "23680503"
    en SBO, o "* Subtotal" en SAP GRC). Devuelve None si no hay ninguna.
    """
    col = d.columnas.get(rol)
    if col is None:
        return None
    candidatos = []
    for fila in filas[d.fila_encabezado + 1:]:
        if _es_fila_detalle(fila, d) or col >= len(fila):
            continue
        v = _a_decimal(fila[col])
        if v is not None and v != 0:
            candidatos.append(v.copy_abs())
    return max(candidatos) if candidatos else None


# --------------------------------------------------------------------------
# Cuadres
# --------------------------------------------------------------------------

def cuadre_totalizador(filas, d: Deteccion) -> Cuadre:
    """La suma del detalle == el totalizador que el archivo trae.

    Es el cuadre mas fuerte de un solo archivo: si la columna de retencion esta
    bien identificada, la suma de las transacciones da el total que SAP ya
    calculo en su fila de subtotal. Si se mapeo la columna equivocada, no da.
    """
    rol = _columna_retencion(d)
    if rol is None:
        return Cuadre("totalizador", False, None, None, "credito",
                      "no se identifico una columna de retencion")
    detalle_suma = _suma_detalle(filas, d, rol)
    total = _totalizador_del_archivo(filas, d, rol)
    if total is None:
        return Cuadre("totalizador", True, None, detalle_suma, rol,
                      "el archivo no trae fila de totales; cuadre omitido")
    cuadra = (detalle_suma - total).copy_abs() <= _TOLERANCIA
    return Cuadre("totalizador", cuadra, total, detalle_suma, rol,
                  "suma del detalle (%s) vs totalizador del archivo (%s)"
                  % (detalle_suma, total))


def cuadre_partida_doble(filas, d: Deteccion) -> Cuadre:
    """En un export con debito y credito separados, ambos totales de la fila
    padre deben coincidir: el saldo de la cuenta de retencion cierra el mes.

    Solo aplica a la convencion de columnas separadas Y cuando el archivo trae
    totalizador en ambas columnas (auxiliar del mes de SBO: padre Db==Cr).
    """
    if d.convencion_signo != "columnas_separadas":
        return Cuadre("partida_doble", True, None, None, "",
                      "convencion de columna unica; no aplica")
    tot_debito = _totalizador_del_archivo(filas, d, "debito")
    tot_credito = _totalizador_del_archivo(filas, d, "credito")
    if tot_debito is None or tot_credito is None:
        return Cuadre("partida_doble", True, tot_credito, tot_debito, "",
                      "sin totalizador en ambas columnas; cuadre omitido")
    cuadra = (tot_debito - tot_credito).copy_abs() <= _TOLERANCIA
    return Cuadre("partida_doble", cuadra, tot_credito, tot_debito, "credito",
                  "debito (%s) vs credito (%s) de la fila padre"
                  % (tot_debito, tot_credito))


def movimiento_periodo_balance(filas, d: Deteccion) -> Decimal:
    """El movimiento credito del periodo de las cuentas 2368 en un balance.

    Es la cifra que cruza contra el total del auxiliar (C2). Suma la columna de
    retencion (credito/importe) de las filas de cuentas ICA de detalle. No usa
    totalizador del archivo: el balance abarca toda la empresa, no solo 2368.
    """
    rol = _columna_retencion(d)
    if rol is None:
        return Decimal("0")
    col = d.columnas[rol]
    total = Decimal("0")
    for fila in filas[d.fila_encabezado + 1:]:
        if not _es_fila_detalle(fila, d) or col >= len(fila):
            continue
        v = _a_decimal(fila[col])
        if v is not None:
            total += v.copy_abs()
    return total


def cuadre_auxiliar_vs_balance(total_auxiliar: Decimal,
                               movimiento_balance: Decimal) -> Cuadre:
    """Cruce entre dos archivos con mapeos independientes.

    Si el total retenido del auxiliar (mapeado con SU deteccion) iguala el
    movimiento del periodo de la 2368 en el balance (mapeado con OTRA
    deteccion), es practicamente imposible que ambos mapeos esten mal a la vez
    de forma que coincidan. Es la confirmacion cruzada mas fuerte del sistema.
    """
    cuadra = (total_auxiliar - movimiento_balance).copy_abs() <= _TOLERANCIA
    return Cuadre("auxiliar_vs_balance", cuadra, movimiento_balance,
                  total_auxiliar, "credito",
                  "total auxiliar (%s) vs movimiento del balance (%s)"
                  % (total_auxiliar, movimiento_balance))


def validar_deteccion(filas, d: Deteccion) -> list:
    """Cuadres internos de un solo archivo, segun su tipo.

    - auxiliar: totalizador + partida doble. El auxiliar viene acotado a 2368,
      asi que la suma del detalle contra el totalizador del propio archivo es
      un cuadre valido y fuerte.
    - balance: NO tiene cuadre interno de este estilo. El balance abarca toda
      la empresa; su columna de retencion (movimiento del periodo de la 2368)
      se valida CRUZANDOLA contra el total del auxiliar
      (cuadre_auxiliar_vs_balance), no contra un totalizador propio. Los dos
      archivos se confirman mutuamente.

    Devuelve la lista de Cuadre. `es_confiable(...)` = mapeo de fiar.
    """
    if d.tipo == "balance":
        return [Cuadre("balance_sin_cuadre_interno", True, None,
                       movimiento_periodo_balance(filas, d), "credito",
                       "el balance se valida cruzado contra el auxiliar")]
    return [cuadre_totalizador(filas, d), cuadre_partida_doble(filas, d)]


def es_confiable(cuadres: list) -> bool:
    return all(c.cuadra for c in cuadres)
