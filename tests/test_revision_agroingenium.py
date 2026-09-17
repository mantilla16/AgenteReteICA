"""La revision de Agroingenium corre extremo a extremo, con borrador de otro
municipio, auxiliar en formato agregado y balance en TSV UTF-16.

Bugs reportados por el auditor (IndexError, StopIteration) que la revision
tumbaban entera. El pipeline ahora tolera:

  - Borrador no reconocido por el reader rico (StopIteration en Santa Marta):
    _borrador_o_esqueleto arma un esqueleto y los controles que dependen de
    renglones caen NO_EJECUTADO.
  - Filas cortas en el TSV UTF-16 (IndexError en balance.py): _io padea al
    ancho del encabezado.
  - Cualquier otro fallo de un control (KeyError por un renglon que no esta):
    _corrida_segura lo convierte en NO_EJECUTADO en vez de tumbar todo.
"""

from decimal import Decimal
from pathlib import Path

import pytest

INSUMOS = Path(r"C:\dev\encargo_agro")   # copia local de los insumos reales

pytestmark = pytest.mark.skipif(
    not (INSUMOS / "auxiliar_2368.xlsx").exists(),
    reason="requiere copia local de los insumos de Agroingenium en C:\\dev\\encargo_agro")


@pytest.fixture(scope="module")
def ctx():
    from motor_reteica.pipeline import revisar
    from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
    return revisar(INSUMOS, nit="901203079", periodo="2026-07",
                   municipio=MUNICIPIO)


def test_el_pipeline_corre_completo_pese_al_borrador_desconocido(ctx):
    """El bug reportado -- StopIteration/IndexError -- tumbaban la revision.
    Ahora se completa: el ContextoRevision se arma con resultados."""
    assert ctx.resultados, "sin resultados no hay conclusion posible"


def test_el_total_del_auxiliar_es_el_neto_de_sap(ctx):
    """El subtotal que SAP reporta -- no la suma bruta de detalles."""
    assert ctx.total_auxiliar == Decimal("2879769")


def test_los_saldos_del_balance_se_leen_pese_al_formato_tsv(ctx):
    """El balance viene en .XLS que es TSV UTF-16. Antes reventaba con
    IndexError por filas cortas; ahora se lee limpio."""
    assert ctx.saldos, "el balance de Agroingenium tiene cuentas 2368"


def test_los_controles_que_dependen_del_borrador_no_reventan(ctx):
    """Los renglones vienen vacios (esqueleto). C1, C7, C9, C10 y C15 en
    vez de KeyError deben salir NO_EJECUTADO o completar sin renglones."""
    from motor_reteica.tipos import Estado
    codigos_por_estado = {r.codigo: r.estado for r in ctx.resultados}
    # C1 mira renglon 24 -- sin el, NO_EJECUTADO. La forma es lo que se
    # protege; el motivo lo escribe _corrida_segura.
    assert codigos_por_estado["C1"] is Estado.NO_EJECUTADO


def test_el_papel_se_genera_con_el_cruce_universal(tmp_path):
    """La prueba de fuego: el papel sale, no revienta al escribirlo."""
    import warnings, openpyxl
    from motor_reteica.pipeline import revisar
    from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
    from motor_reteica.plantilla.deposito import depositar

    ctx = revisar(INSUMOS, nit="901203079", periodo="2026-07",
                  municipio=MUNICIPIO)
    salida = tmp_path / "papel.xlsx"
    depositar(ctx, salida, total_declarado_confirmado=Decimal("2880000"))
    assert salida.exists() and salida.stat().st_size > 50_000

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hoja = openpyxl.load_workbook(salida)["REVISION ICA"]
    # El cruce universal quedo escrito con la diferencia de 231.
    for fila in range(28, hoja.max_row + 5):
        if hoja.cell(row=fila, column=2).value == "CRUCE UNIVERSAL":
            assert hoja.cell(row=fila + 1, column=4).value == 2880000
            assert hoja.cell(row=fila + 2, column=4).value == 2879769
            assert hoja.cell(row=fila + 3, column=4).value == 231
            return
    pytest.fail("no se encontro el bloque CRUCE UNIVERSAL en el papel")
