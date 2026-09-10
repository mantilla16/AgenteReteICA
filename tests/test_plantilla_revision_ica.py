"""Etapa 6, fase 5: REVISION ICA. Aqui vive D11 y se corrige D12.

D11: las referencias que cruzan de una hoja a otra se anclan al SIGNIFICADO
(numero de cuenta, codigo de actividad), no a la POSICION de la fila. El
papel sigue VIVO -- las formulas siguen siendo formulas -- pero dejan de
romperse cuando el balance del mes trae una fila de mas.

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
def papel(tmp_path_factory):
    ctx = revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
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


def test_el_saldo_del_balance_se_busca_por_numero_de_cuenta(papel):
    hoja = papel["REVISION ICA"]
    assert "2368010007" in str(hoja["N12"].value)
    assert "VLOOKUP" in str(hoja["N12"].value).upper()
    assert "2368010010" in str(hoja["N13"].value)


def test_los_totales_de_la_declaracion_se_suman_por_codigo_de_actividad(papel):
    """No se apunta a la fila del total: se suman las filas que tienen
    codigo de actividad. Si el borrador trae 7 actividades, sigue sirviendo."""
    hoja = papel["REVISION ICA"]
    assert "SUMIF" in str(hoja["F20"].value).upper()
    assert "SUMIF" in str(hoja["G20"].value).upper()


def test_las_referencias_siguen_siendo_formulas_vivas(papel):
    """D11 revisada: NO se congelan a valor. El papel se mantiene vivo."""
    hoja = papel["REVISION ICA"]
    for celda in ("N12", "N13", "F20", "G20"):
        assert str(hoja[celda].value).startswith("="), celda


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
