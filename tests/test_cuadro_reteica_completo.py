"""El CUADRO RETEICA transcribe el reporte del ERP completo.

Sale de una reunion con el auditor: el papel es EVIDENCIA de la retencion
practicada. Sin la columna Impte.neto 2 MI (la base sujeta) el que revisa no
puede recalcular la tarifa efectiva ni confirmar que la retencion
corresponde al pago del tercero. El motor escribia solo 4 columnas -- las
que usan los cruces -- y el auditor pegaba las 8 a mano cada mes.
"""

import warnings
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.plantilla.deposito import depositar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def hoja(tmp_path_factory):
    ctx = revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    salida = tmp_path_factory.mktemp("erp") / "papel.xlsx"
    depositar(ctx, salida)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(salida)["CUADRO RETEICA"]


def test_las_ocho_columnas_del_export_estan(hoja):
    """El auditor las pega manual. Faltar UNA es faltar la evidencia."""
    encabezado = [c.value for c in hoja[4]]
    esperadas = ["Acreedor", "Tp.rete", "Ret", "Importe en MD",
                 "Impte.neto 2 MI", "Impte.base Qst en MI",
                 "Importe qst en MI", "Impte.sin Qst MI"]
    for etiqueta in esperadas:
        assert any(etiqueta in str(c or "") for c in encabezado), (
            "falta la columna %r en el CUADRO RETEICA" % etiqueta)


def test_la_base_sujeta_si_llega_esta_vez(hoja):
    """Impte.neto 2 MI (columna F) es lo que el auditor multiplica por la
    tarifa para verificar que la retencion practicada esta bien. Sin ese
    numero, ese cruce se hacia a mano contra otro archivo."""
    for fila in range(5, 10):
        base_sujeta = hoja.cell(row=fila, column=6).value  # F
        assert isinstance(base_sujeta, (int, float)), (
            "F%d trae %r, no un numero -- la base sujeta no llego" %
            (fila, base_sujeta))


def test_las_sumas_al_final_se_conservan(hoja):
    """El auditor lee ahi el total del mes. Ya estaban antes del cambio."""
    assert str(hoja["G10"].value).startswith("=SUM")
    assert str(hoja["H10"].value).startswith("=SUM")
