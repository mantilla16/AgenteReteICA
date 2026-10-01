"""Flujo completo de un cliente SAP Business One (Equinorte): balance completo de
la empresa con jerarquia y varios municipios, auxiliar SBO, y el cruce por
cuenta que exige la revision (credito del balance == suma del auxiliar).

Reproduce la estructura real en datos sinteticos para correr en CI sin la red
del cliente. Fija toda la logica que se endurecio con Equinorte: deteccion por
contenido, solo cuentas HOJA, fila resumen (sin tercero), filtro por municipio,
y el cruce por cuenta.
"""

from collections import defaultdict
from decimal import Decimal

import openpyxl
import pytest

from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.balance import leer_balance, leer_debitos

# Layout SBO de 21 columnas (mismas etiquetas que el export real).
_ENC = ["Cuenta contable", "Nombre cuenta contable", "Código SN", "Nombre SN",
        "NIT", "Nombre proyecto", "Nombre dimensión", "Dimensión", "Serie",
        "No. Transacción (Asiento)", "No. Línea (Asiento)",
        "No. Origen (Doc. Marketing)", "Tipo Origen (Documento)",
        "Referencia 1", "Referencia 2", "Saldo Inicial (Moneda Local)",
        "Débito Moneda Local", "Crédito Moneda Local",
        "Saldo Final (Moneda Local)", "Referencia 3", "Comentarios (Lineas)"]

_SM5 = "IMPUESTO DE IND Y CCIO RETENIDO SANTA M. 5x1000"
_SM10 = "IMPUESTO DE IND Y CCIO RETENIDO SANTA M. 10x1000"
_SM7 = "IMPUESTO DE IND Y CCIO RETENIDO SANTA M. 7x1000"
_GALAPA = "IMPUESTO DE IND Y CCIO RETENIDO GALAPA 5x1000"


def _fila(cuenta, nombre, nit="", saldo_ini=0, debito=0, credito=0, saldo_fin=0):
    f = [None] * 21
    f[0], f[1], f[4] = cuenta, nombre, nit
    f[15], f[16], f[17], f[18] = saldo_ini, debito, credito, saldo_fin
    return f


def _balance_completo():
    """Balance completo: cuentas de banco (ruido), jerarquia 2368 y 2 municipios.

    Las cuentas 2368 de Santa Marta (credito=debito, el caso real de Equinorte)
    y una de Galapa que NO debe entrar en una revision de Santa Marta.
    """
    return [
        _ENC,
        _fila("11100510", "Banco X", credito=999_999_999),      # ruido
        # Jerarquia Santa Marta: padres (subtotales) + hojas (resumen + tercero)
        _fila("2368", "IMPUESTO DE IND Y CCIO RETENIDO", debito=1_355_387, credito=1_355_387),
        _fila("236805", "IMPUESTO DE IND Y CCIO RETENIDO SM", debito=1_355_387, credito=1_355_387),
        _fila("23680503", "IMPUESTO DE IND Y CCIO RETENIDO SANTA MA", debito=1_355_387, credito=1_355_387),
        _fila("2368050301", _SM5, debito=957_200, credito=957_200),            # resumen (sin NIT)
        _fila("2368050301", _SM5, nit="891780009-4", saldo_ini=5_038_209),      # tercero
        _fila("2368050302", _SM10, debito=376_162, credito=376_162),
        _fila("2368050303", _SM7, debito=22_023, credito=22_023),
        # Otro municipio: NO debe entrar en la revision de Santa Marta.
        _fila("23680501", "IMPUESTO DE IND Y CCIO RETENIDO GALAPA", debito=500_000, credito=500_000),
        _fila("2368050101", _GALAPA, debito=500_000, credito=500_000),
    ]


def _auxiliar_sbo():
    """Auxiliar SBO de Santa Marta: movimientos por tercero cuyos creditos suman,
    por cuenta, lo mismo que el credito del balance."""
    return [
        _ENC,
        _fila("2368050301", _SM5, nit="45491406-6", credito=600_000),
        _fila("2368050301", _SM5, nit="901698542-4", credito=357_200),   # 600k+357.2k = 957.2k
        _fila("2368050302", _SM10, nit="802003363-1", credito=376_162),
        _fila("2368050303", _SM7, nit="901878575-1", credito=22_023),
    ]


def _guardar(tmp_path, filas, nombre):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    for f in filas:
        ws.append(f)
    ruta = tmp_path / nombre
    wb.save(ruta)
    return ruta


def test_balance_completo_solo_cuentas_hoja_de_santa_marta(tmp_path):
    ruta = _guardar(tmp_path, _balance_completo(), "Balance agosto.xlsx")
    saldos = leer_balance(ruta, municipio="Santa Marta")
    # Solo las 3 hojas de Santa Marta -- ni padres, ni banco, ni Galapa.
    assert set(saldos) == {"2368050301", "2368050302", "2368050303"}
    assert saldos["2368050301"] == Decimal("957200")
    assert sum(saldos.values()) == Decimal("1355385")   # 957200+376162+22023


def test_debito_por_cuenta(tmp_path):
    ruta = _guardar(tmp_path, _balance_completo(), "Balance agosto.xlsx")
    deb = leer_debitos(ruta, municipio="Santa Marta")
    assert deb["2368050302"] == Decimal("376162")


def test_cruce_por_cuenta_balance_vs_auxiliar(tmp_path):
    """El corazon de la revision: credito del balance por cuenta == suma de los
    movimientos del auxiliar de esa cuenta."""
    bal = _guardar(tmp_path, _balance_completo(), "Balance agosto.xlsx")
    aux = _guardar(tmp_path, _auxiliar_sbo(), "Auxiliar.xlsx")

    saldos = leer_balance(bal, municipio="Santa Marta")
    lineas = leer_auxiliar(aux)
    por_cuenta = defaultdict(lambda: Decimal(0))
    for l in lineas:
        por_cuenta[l.cuenta] += l.retencion

    for cuenta, credito_balance in saldos.items():
        assert por_cuenta[cuenta] == credito_balance, (
            "cuenta %s: balance %s vs auxiliar %s"
            % (cuenta, credito_balance, por_cuenta[cuenta]))


def test_auxiliar_sin_columna_de_retencion_avisa(tmp_path):
    """Si el auxiliar no trae Importe ML / credito, se avisa, no se inventa."""
    from motor_reteica.parametros.columnas import ColumnaNoIdentificada
    enc = ["Cuenta contable", "Nombre cuenta contable", "NIT", "Saldo Inicial"]
    filas = [enc, ["2368050301", _SM5, "45491406-6", 100]]
    ruta = _guardar(tmp_path, filas, "Auxiliar.xlsx")
    with pytest.raises(ColumnaNoIdentificada) as exc:
        leer_auxiliar(ruta)
    assert "retencion" in str(exc.value).lower()
