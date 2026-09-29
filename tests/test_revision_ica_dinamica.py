"""La cedula de REVISION ICA se arma segun las cuentas del balance, no fija.

TERLICA (2 cuentas) se cubre en test_plantilla_revision_ica; aqui se verifica
el caso de 3 cuentas con 3 tarifas distintas (ZFT/Equinorte), que la version
cableada no soportaba.
"""

import warnings
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from motor_reteica.plantilla.deposito import _depositar_cedula_cuentas

PLANTILLA = (Path(__file__).parent.parent / "motor_reteica" / "plantilla"
             / "PT_ReteICA_plantilla.xlsx")


@pytest.fixture
def hoja():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        libro = openpyxl.load_workbook(PLANTILLA)
    return libro["REVISION ICA"]


def _ctx(saldos, tarifas):
    return SimpleNamespace(
        saldos={k: Decimal(str(v)) for k, v in saldos.items()},
        municipio=SimpleNamespace(
            tarifa_por_cuenta={k: Decimal(str(v)) for k, v in tarifas.items()}))


def test_tres_cuentas_tres_filas(hoja):
    ctx = _ctx(
        {"2368050301": 1270907, "2368050302": 320263, "2368050303": 41169},
        {"2368050301": "0.005", "2368050302": "0.010", "2368050303": "0.007"})
    _depositar_cedula_cuentas(hoja, ctx)

    # Tres filas de cuenta (12,13,14), ordenadas por numero de cuenta.
    assert hoja["K12"].value == 2368050301
    assert hoja["K13"].value == 2368050302
    assert hoja["K14"].value == 2368050303
    assert hoja["N12"].value == 1270907
    assert hoja["N13"].value == 320263
    assert hoja["N14"].value == 41169
    # Suma en la fila siguiente (15), no en la 14 cableada.
    assert hoja["N15"].value == "=SUM(N12:N14)"
    assert hoja["O15"].value == "=SUM(O12:O14)"
    # Saldo por fila sigue siendo la formula de la firma.
    assert hoja["O12"].value == "=ROUND(+N12-M12,-3)"


def test_bloque_retencion_una_fila_por_tarifa(hoja):
    ctx = _ctx(
        {"2368050301": 1270907, "2368050302": 320263, "2368050303": 41169},
        {"2368050301": "0.005", "2368050302": "0.010", "2368050303": "0.007"})
    _depositar_cedula_cuentas(hoja, ctx)

    # Tarifas de mayor a menor: 0.010, 0.007, 0.005 en filas 17,18,19.
    assert hoja["K17"].value == 0.010
    assert hoja["K18"].value == 0.007
    assert hoja["K19"].value == 0.005
    # L referencia el N de la cuenta con esa tarifa; M = base = ROUND(L/K,-3).
    assert hoja["L17"].value == "=+N13"   # 0.010 -> cuenta 050302 (fila 13)
    assert hoja["L18"].value == "=+N14"   # 0.007 -> cuenta 050303 (fila 14)
    assert hoja["L19"].value == "=+N12"   # 0.005 -> cuenta 050301 (fila 12)
    assert hoja["M17"].value == "=ROUND(+L17/K17,-3)"


def test_cuentas_en_cero_no_entran(hoja):
    ctx = _ctx(
        {"2368010005": 0, "2368010007": 36318, "2368010010": 438243},
        {"2368010005": "0.005", "2368010007": "0.007", "2368010010": "0.010"})
    _depositar_cedula_cuentas(hoja, ctx)

    # La cuenta en cero no ocupa fila; solo 007 y 010.
    assert hoja["K12"].value == 2368010007
    assert hoja["K13"].value == 2368010010
    assert hoja["K14"].value is None
    assert hoja["N12"].value == 36318
    assert hoja["N13"].value == 438243


def test_sin_balance_lo_dice(hoja):
    ctx = SimpleNamespace(saldos=None,
                          municipio=SimpleNamespace(tarifa_por_cuenta={}))
    _depositar_cedula_cuentas(hoja, ctx)
    assert "SIN BALANCE" in str(hoja["P12"].value)
    assert hoja["N12"].value is None
