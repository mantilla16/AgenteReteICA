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
    tienen que aparecer sin depender de que el motor los haya podido leer.

    La cuenta va en B, que es donde la plantilla la espera (ver encabezado
    'Cuenta' en la fila 6 de la plantilla)."""
    hoja = papel["AUX FISCAL"]
    cuentas = [str(c.value) for c in hoja["B"]
               if c.value and str(c.value).startswith("2368")]
    assert len(cuentas) == 12, "esperado 12 lineas del auxiliar TERLICA"


def test_aux_fiscal_pega_datos_en_las_columnas_correctas(papel):
    """Como el balance: si la fuente trae la Cuenta en una columna que no
    coincide con la de la plantilla, hay que ALINEAR por etiqueta. Cuenta
    en B, Asignacion en D, Soc. en O -- lo que la plantilla tiene fijado."""
    hoja = papel["AUX FISCAL"]
    fila_enc = 6
    encabezados = {}
    for c in range(1, 16):
        v = hoja.cell(row=fila_enc, column=c).value
        if v:
            encabezados[str(v).strip()] = c
    assert encabezados.get("Cuenta") == 2, (
        "Cuenta debe ir en B, quedo en %s" % encabezados.get("Cuenta"))
    for etiqueta in ("Asignación", "Asignacion"):
        if etiqueta in encabezados:
            assert encabezados[etiqueta] == 4, (
                "%s debe ir en D, quedo en %s"
                % (etiqueta, encabezados[etiqueta]))
            break
    for etiqueta in ("Soc.", "Sociedad"):
        if etiqueta in encabezados:
            assert encabezados[etiqueta] == 15, (
                "%s debe ir en O, quedo en %s"
                % (etiqueta, encabezados[etiqueta]))
            break


def test_aux_fiscal_conserva_los_encabezados_de_la_fuente(papel):
    """Como con el balance: el encabezado es el del archivo, no una version
    normalizada por el motor."""
    hoja = papel["AUX FISCAL"]
    textos = [str(c.value) for f in range(1, 10)
              for c in hoja[f] if c.value]
    assert any("Cuenta" in t for t in textos)
    assert any("Asignaci" in t for t in textos)   # Asignacion, con o sin tilde


# --------------------------------------------------------------------------
# Reglas de la guia del auditor sobre BALANCE (docx del 17-sep):
#   - Autofiltro por Cta.mayor.
#   - Fila de subtotal con SUBTOTAL(9,...) sobre el bloque de retenciones.
# --------------------------------------------------------------------------

def test_balance_trae_autofiltro_para_filtrar_por_2368(papel):
    """El auditor filtra por 'CTA mayor que empieza por 2368' para dejar
    solo las cuentas de ReteICA. Sin autofiltro tiene que activarlo a mano."""
    hoja = papel["BALANCE"]
    assert hoja.auto_filter.ref, "no hay autofiltro en la hoja BALANCE"


def test_balance_agrega_subtotal_con_funcion_subtotal(papel):
    """SUBTOTAL(9,...) suma SOLO filas visibles: con el filtro por 2368,
    el subtotal se ajusta solo. Un SUM(...) sumaria las ocultas tambien y
    daria el gran total en vez del subtotal ICA."""
    hoja = papel["BALANCE"]
    fila_sub = hoja.max_row
    for columna in ("H", "I"):
        formula = str(hoja["%s%d" % (columna, fila_sub)].value or "")
        assert formula.upper().startswith("=SUBTOTAL(9,"), (
            "columna %s: %r no es SUBTOTAL" % (columna, formula))
    # J = I - H (neto del periodo)
    j = str(hoja["J%d" % fila_sub].value or "")
    assert j == "=I%d-H%d" % (fila_sub, fila_sub), j


def test_balance_acota_el_rango_al_bloque_de_retenciones(papel):
    """El subtotal apunta al bloque 236x, no al balance entero. Motivo: el
    balance trae una fila de total general de SAP (H = 51 mil millones en
    TERLICA); incluirla sin filtro duplicaria el total del papel."""
    hoja = papel["BALANCE"]
    formula = str(hoja["H%d" % hoja.max_row].value or "")
    import re
    m = re.match(r"=SUBTOTAL\(9,H(\d+):H(\d+)\)", formula)
    assert m, "no encontre el rango en %r" % formula
    inicio, fin = int(m.group(1)), int(m.group(2))
    # La cuenta en cada fila del rango debe empezar por 236.
    for f in range(inicio, fin + 1):
        cuenta = str(hoja.cell(row=f, column=3).value or "")
        assert cuenta.startswith("236"), (
            "fila %d dentro del rango del subtotal trae cuenta %r "
            "-- deberia ser 236x" % (f, cuenta))


def test_las_demas_hojas_no_desaparecieron(papel):
    """Ocultar BORRADOR TERLICA no puede haber tumbado a nadie mas."""
    esperadas = {"Check List", "DECLARACION", "REVISION ICA",
                 "BALANCE", "AUX FISCAL", "Validación de facturas",
                 "CUADRO RETEICA"}
    faltan = esperadas - set(papel.sheetnames)
    assert not faltan, "se perdieron hojas: %s" % faltan


def test_pago_queda_oculta(papel):
    """El auditor confirmo que la hoja 'Pago' no la usa. Se oculta por el
    mismo motivo que BORRADOR TERLICA: fidelidad.py restaura las hojas
    desde el paquete original, borrar desordena los ids de las demas."""
    assert "Pago" in papel.sheetnames, "la hoja sigue existiendo"
    assert papel["Pago"].sheet_state == "hidden", (
        "la hoja Pago tiene que quedar oculta, no visible")


def test_balance_pega_datos_en_las_columnas_correctas(papel):
    """Los saldos no pueden caer fuera de sus columnas: si el balance
    real trae separadores intercalados, hay que ALINEAR por etiqueta, no
    copiar posicion por posicion. La cuenta debe quedar en C, el saldo
    del periodo en H."""
    hoja = papel["BALANCE"]
    # Encabezado en la fila justo antes del area de datos.
    encabezado_fila = 4
    encabezados = {}
    for c in range(1, 12):
        v = hoja.cell(row=encabezado_fila, column=c).value
        if v:
            encabezados[str(v).strip()] = c
    assert encabezados.get("Cta.mayor") == 3, (
        "Cta.mayor debe quedar en columna C, quedo en %s"
        % encabezados.get("Cta.mayor"))
    assert encabezados.get("Saldo Haber per.inf.") == 9, (
        "Saldo Haber per.inf. debe quedar en columna I, quedo en %s"
        % encabezados.get("Saldo Haber per.inf."))
