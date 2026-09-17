"""Reglas nuevas del papel, decididas por el auditor al depurar TERLICA:

  1. La hoja BORRADOR TERLICA no es necesaria -- queda oculta.
  2. BALANCE pega el archivo del cliente TAL CUAL, no un extracto.
  3. AUX FISCAL pega el auxiliar TAL CUAL, no una version reordenada.

Estas pruebas fijan las tres. Su docstring dice PORQUE cambio la regla, no
lo que hacia antes -- para que quien las lea entienda la decision del
auditor, no la historia del codigo.
"""

import warnings
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.plantilla.deposito import depositar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def papel(tmp_path_factory):
    ctx = revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    salida = tmp_path_factory.mktemp("pulido") / "papel.xlsx"
    depositar(ctx, salida, total_declarado_confirmado=Decimal("474000"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(salida)


def test_borrador_terlica_queda_oculta(papel):
    """Robinson: 'esa hoja no seria necesaria'. La hoja NO se borra porque
    fidelidad.py restaura el paquete desde la plantilla y borrar altera los
    ids de las demas hojas -- se oculta."""
    assert "BORRADOR TERLICA" in papel.sheetnames, "la hoja sigue existiendo"
    assert papel["BORRADOR TERLICA"].sheet_state == "hidden", (
        "la hoja tiene que quedar oculta, no visible ni removida")


def test_balance_pega_el_archivo_completo(papel):
    """El balance del cliente tiene ~349 filas. El motor solo verifica las
    2368 (via C2), pero el papel es EVIDENCIA: se pega tal cual para que el
    lector pueda comprobar cualquier saldo sin salir del papel."""
    hoja = papel["BALANCE"]
    assert hoja.max_row > 300, (
        "esperado el balance completo (>300 filas), llego con %d" % hoja.max_row)


def test_balance_conserva_los_encabezados_de_la_fuente(papel):
    """No se normalizan las columnas: el encabezado que aparece es el que
    trae el archivo del cliente."""
    hoja = papel["BALANCE"]
    encabezados = [str(c.value) for f in range(1, 8)
                   for c in hoja[f] if c.value]
    assert any("Cta.mayor" in e for e in encabezados)
    assert any("Saldo Haber per.inf." in e for e in encabezados)


def test_aux_fiscal_pega_el_auxiliar_completo(papel):
    """El auxiliar de TERLICA trae 12 movimientos + 1 fila de TOTAL. Todos
    tienen que aparecer sin depender de que el motor los haya podido leer."""
    hoja = papel["AUX FISCAL"]
    cuentas = [str(c.value) for c in hoja["D"]
               if c.value and str(c.value).startswith("2368")]
    assert len(cuentas) == 12, "esperado 12 lineas del auxiliar TERLICA"


def test_aux_fiscal_conserva_los_encabezados_de_la_fuente(papel):
    """Como con el balance: el encabezado es el del archivo, no una version
    normalizada por el motor."""
    hoja = papel["AUX FISCAL"]
    textos = [str(c.value) for f in range(1, 10)
              for c in hoja[f] if c.value]
    assert any("Cuenta" in t for t in textos)
    assert any("Asignaci" in t for t in textos)   # Asignacion, con o sin tilde


def test_las_demas_hojas_no_desaparecieron(papel):
    """Ocultar BORRADOR TERLICA no puede haber tumbado a nadie mas."""
    esperadas = {"Check List", "DECLARACION", "Pago", "REVISION ICA",
                 "BALANCE", "AUX FISCAL", "Validación de facturas",
                 "CUADRO RETEICA"}
    faltan = esperadas - set(papel.sheetnames)
    assert not faltan, "se perdieron hojas: %s" % faltan
