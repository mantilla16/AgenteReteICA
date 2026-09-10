"""Loop de validacion, hallazgo V3: las conclusiones del papel.

La plantilla trae conclusiones ESTATICAS escritas a mano:

  Validacion de facturas B33: "...no se presentan diferencias en las facturas."
  REVISION ICA A30:           "...los valores... son integros..."

Depositar los datos y dejar esos textos intactos hace que el papel afirme que
todo esta bien PASE LO QUE PASE. Es exactamente la queja con la que nacio este
proyecto -- el papel manual de julio concluyo "no se presentan diferencias"
con controles en falla -- solo que automatizada.

La conclusion NO se redacta: se DERIVA del estado de los controles. Es el
mismo principio que ya gobierna hallazgos.consolidar().
"""

import warnings
from dataclasses import replace
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.plantilla.deposito import depositar
from motor_reteica.tipos import Estado, Excepcion, Severidad

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


def _papel(ctx, ruta):
    depositar(ctx, ruta)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(ruta)


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


def test_la_plantilla_de_origen_si_trae_la_conclusion_estatica():
    """La premisa del hallazgo."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plantilla = openpyxl.load_workbook(
            Path(__file__).parent.parent / "motor_reteica" / "plantilla"
            / "PT_ReteICA_plantilla.xlsx")
    assert "no se presentan diferencias" in \
        str(plantilla["Validación de facturas"]["B33"].value)


def test_la_conclusion_no_afirma_limpio_cuando_la_revision_no_lo_esta(ctx, tmp_path):
    """Julio esta en ROJO: C7 y C12 sin ejecutar. El papel no puede decir
    que los valores son integros."""
    assert not ctx.informe.puede_concluir_limpio      # premisa
    papel = _papel(ctx, tmp_path / "p.xlsx")
    conclusion = str(papel["REVISION ICA"]["A30"].value).lower()
    assert "integros" not in conclusion or "no " in conclusion
    assert "no es concluyente" in conclusion or "no concluyente" in conclusion


def test_la_conclusion_nombra_los_controles_que_no_se_ejecutaron(ctx, tmp_path):
    papel = _papel(ctx, tmp_path / "p.xlsx")
    conclusion = str(papel["REVISION ICA"]["A30"].value)
    assert "C7" in conclusion and "C12" in conclusion


def test_la_conclusion_de_facturas_refleja_el_estado_de_c11(ctx, tmp_path):
    """C11 en julio esta en FALLA: hay un aviso por el NIT de FE338057 y una
    observacion por la fecha de FE10."""
    c11 = next(r for r in ctx.resultados if r.codigo == "C11")
    assert c11.estado is Estado.FALLA                 # premisa
    papel = _papel(ctx, tmp_path / "p.xlsx")
    texto = str(papel["Validación de facturas"]["B33"].value).lower()
    assert "no se presentan diferencias" not in texto


def test_si_todo_cuadra_si_puede_decir_que_no_hay_diferencias(ctx, tmp_path):
    """Lo contrario tambien tiene que valer: si C11 pasa, el papel lo dice."""
    limpio = []
    for resultado in ctx.resultados:
        if resultado.codigo == "C11":
            limpio.append(replace(resultado, estado=Estado.OK, excepciones=()))
        else:
            limpio.append(resultado)
    papel = _papel(replace(ctx, resultados=limpio), tmp_path / "p.xlsx")
    texto = str(papel["Validación de facturas"]["B33"].value).lower()
    assert "no se presentan diferencias" in texto


def test_si_c11_no_se_ejecuto_el_papel_no_finge_que_si(ctx, tmp_path):
    sin_c11 = [replace(r, estado=Estado.NO_EJECUTADO, excepciones=())
               if r.codigo == "C11" else r for r in ctx.resultados]
    papel = _papel(replace(ctx, resultados=sin_c11), tmp_path / "p.xlsx")
    texto = str(papel["Validación de facturas"]["B33"].value).lower()
    assert "no se ejecut" in texto
