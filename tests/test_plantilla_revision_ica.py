"""Etapa 6, fase 5: REVISION ICA. Aqui vive D11 y se corrige D12.

D11, version final: lo que cruza de una hoja a otra lo RESUELVE EL MOTOR y
se deposita como numero. La plantilla traia =+BALANCE!I157 -- una fila fija,
que miente el mes que el balance trae una cuenta mas. La primera solucion
fue anclar al SIGNIFICADO con VLOOKUP por numero de cuenta, manteniendo el
papel "vivo", y costo dos defectos seguidos ajenos a ReteICA: el libro se
abria sin recalcular y la hoja salia en blanco, y al recalcular devolvio
#N/D porque la cuenta se escribe como texto y el VLOOKUP buscaba un numero.

Se paso a valor. Razones, en orden de peso:

  - El motor es la unica fuente de verdad. Si la formula y el motor algun
    dia discrepan, el papel no sabe cual manda.
  - openpyxl NO evalua formulas: con formulas, lo unico que una prueba podia
    verificar era que la CADENA estuviera bien escrita. Por eso la suite
    entera pasaba con el papel en blanco. Con valores, las pruebas comparan
    la cifra del papel contra la del motor -- que es lo que importa.
  - Un papel de trabajo es evidencia archivada en PDF. No deberia cambiar
    segun quien lo abra.

Lo que NO cambia: la aritmetica de la firma (D20 =+M21, E20 =+O12+O13, los
=SUM de la fila 26, los =ROUND) sigue siendo formula. Ese es su papel y la
derivacion tiene que verse.

D12: la plantilla que la firma entrego tiene un bug real. G28 apunta a
DECLARACION!J21, que esta VACIA, y F28 esta fija en 0, asi que la fila
TOTAL A PAGAR muestra una diferencia de 474.000 -- el impuesto completo --
dos filas encima de una conclusion que dice que todo es integro. Se corrige,
no se reproduce.
"""

import re
import warnings
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.plantilla.deposito import depositar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
PLANTILLA = (Path(__file__).parent.parent / "motor_reteica" / "plantilla"
             / "PT_ReteICA_plantilla.xlsx")


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


@pytest.fixture(scope="module")
def papel(ctx, tmp_path_factory):
    salida = tmp_path_factory.mktemp("p") / "papel.xlsx"
    depositar(ctx, salida)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(salida)


def _formulas_que_cruzan_hojas(libro):
    """Toda formula que nombre otra hoja."""
    hojas = set(libro.sheetnames)
    encontradas = []
    for nombre in libro.sheetnames:
        for fila in libro[nombre].iter_rows():
            for celda in fila:
                if not isinstance(celda.value, str) or not celda.value.startswith("="):
                    continue
                if any(h in celda.value for h in hojas):
                    encontradas.append((nombre, celda.coordinate, celda.value))
    return encontradas


# --------------------------------------------------------------------------
# D11: ninguna referencia entre hojas puede depender de una fila fija
# --------------------------------------------------------------------------

def test_la_plantilla_de_origen_si_tiene_el_defecto(papel=None):
    """La premisa de D11, medida sobre la plantilla."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        original = openpyxl.load_workbook(PLANTILLA)
    crudas = [f for _, _, f in _formulas_que_cruzan_hojas(original)]
    assert any(re.search(r"BALANCE!\$?[A-Z]+\$?\d+", f) for f in crudas), \
        "la plantilla ya no trae referencias por posicion: D11 sobraria"


def test_ninguna_referencia_entre_hojas_apunta_a_una_celda_fija(papel):
    """El corazon de D11.

    =+BALANCE!I157 sigue dando un numero si el export trae una fila de mas:
    el de la cuenta equivocada, sin ningun error visible.
    """
    # Lo prohibido es traer un valor de una CELDA SUELTA de otra hoja
    # (BALANCE!I157). Un RANGO de otra hoja (BALANCE!$C$5:$I$349) es
    # legitimo: es la tabla donde el VLOOKUP busca por numero de cuenta, y
    # no depende de que la cuenta caiga en una fila concreta.
    celda_suelta = re.compile(r"[A-Za-zÁÉÍÓÚÑ ]+!\$?[A-Z]{1,3}\$?\d+(?!\s*:)")

    posicionales = []
    for hoja, celda, formula in _formulas_que_cruzan_hojas(papel):
        for referencia in celda_suelta.finditer(formula):
            # descartar la segunda mitad de un rango (…:$I$349)
            if formula[:referencia.start()].rstrip().endswith(":"):
                continue
            posicionales.append("%s!%s -> %s" % (hoja, celda, formula))
            break
    assert posicionales == [], \
        "referencias por posicion que sobreviven:\n  " + "\n  ".join(posicionales)


def test_el_saldo_del_balance_lo_deposita_el_motor(papel):
    """La cifra, no la instruccion para buscarla.

    Y es la MISMA que el motor leyo del balance: esto no se podia comprobar
    con una formula, porque openpyxl no la evalua.
    """
    hoja = papel["REVISION ICA"]
    assert hoja["N12"].value == 36318      # cuenta 2368010007, al 7 por mil
    assert hoja["N13"].value == 438243     # cuenta 2368010010, al 10 por mil
    assert hoja["N12"].value + hoja["N13"].value == 474561, \
        "los dos saldos tienen que dar el impuesto contable del motor"


def test_los_totales_declarados_los_deposita_el_motor(papel, ctx):
    """Suma TODAS las actividades del borrador, no una celda de total.

    Es lo que buscaba D11: si el borrador trae siete actividades en vez de
    cinco, la cifra sigue siendo la correcta.
    """
    hoja = papel["REVISION ICA"]
    assert hoja["F20"].value == sum(int(a.base) for a in ctx.borrador.actividades)
    assert hoja["G20"].value == sum(int(a.impuesto) for a in ctx.borrador.actividades)


def test_lo_que_cruza_de_hoja_va_como_numero_no_como_formula(papel):
    """El reves de la prueba anterior de D11.

    Una formula entre hojas vuelve a traer los dos defectos que costaron
    esta decision: depende de que Excel recalcule al abrir, y de que los
    tipos de las dos hojas coincidan.
    """
    hoja = papel["REVISION ICA"]
    for celda in ("N12", "N13", "F20", "G20"):
        assert isinstance(hoja[celda].value, (int, float)), \
            "%s volvio a ser formula: %r" % (celda, hoja[celda].value)


def test_la_aritmetica_de_la_firma_sigue_siendo_formula(papel):
    """El motor deposita las ENTRADAS; la derivacion es del papel.

    Congelar tambien estas dejaria una cedula sin mostrar de donde sale
    cada cifra, que es justo lo que un papel de trabajo tiene que mostrar.
    """
    hoja = papel["REVISION ICA"]
    for celda in ("D20", "E20", "H20", "O12", "M17", "F26", "D28"):
        assert str(hoja[celda].value).startswith("="), \
            "%s dejo de ser formula de la plantilla" % celda


# --------------------------------------------------------------------------
# D12: el bug de la plantilla se corrige
# --------------------------------------------------------------------------

def test_la_fila_total_a_pagar_ya_no_apunta_a_una_celda_vacia(papel):
    """G28 apuntaba a DECLARACION!J21, vacia, y mostraba 474.000 de
    diferencia donde no hay ninguna."""
    hoja = papel["REVISION ICA"]
    assert "J21" not in str(hoja["G28"].value)
    assert str(hoja["G28"].value).startswith("=")


def test_la_base_declarada_del_total_ya_no_esta_fija_en_cero(papel):
    assert papel["REVISION ICA"]["F28"].value != 0


# --------------------------------------------------------------------------
# Trazabilidad: la cifra que la formula lee tiene que estar a la vista
# --------------------------------------------------------------------------

def test_la_cifra_que_busca_la_formula_esta_visible_en_el_papel(papel):
    """Se penso dejar la cifra del motor en el COMENTARIO de la celda, y se
    descarto: openpyxl crea partes nuevas que la estrategia de fidelidad no
    arrastra y el archivo queda corrupto.

    No hace falta: el VLOOKUP lee la hoja BALANCE, que el propio motor
    deposito, asi que la cifra ya esta a la vista en el papel. La
    trazabilidad existe sin inventar nada.
    """
    balance = papel["BALANCE"]
    saldos = {}
    for f in range(5, balance.max_row + 1):
        cuenta = balance.cell(row=f, column=3).value
        if cuenta:
            saldos[str(cuenta)] = balance.cell(row=f, column=9).value
    assert saldos.get("2368010007") == 36318
    assert saldos.get("2368010010") == 438243
