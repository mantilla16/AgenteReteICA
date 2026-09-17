"""Que el papel se VEA, no solo que se escriba.

Los tres defectos que Felipe encontro abriendo el archivo en Excel habian
pasado la suite entera. Los tres compartian forma: el dato estaba bien
escrito y era invisible al abrirlo. Una prueba que lea el valor con openpyxl
los declara correctos a todos.

  BALANCE .......... la plantilla trae 338 de sus 345 filas OCULTAS, porque
                     la firma las colapso al archivar. El motor escribia las
                     cuentas 2368 desde la fila 5, justo donde empieza lo
                     oculto: openpyxl las leia, Excel no las mostraba.

  BORRADOR ......... el borrado previo arrancaba en la columna D y se llevaba
                     por delante las formulas del formulario (BASE, IMPTO y
                     dos sumas cruzadas). Se reescribian solo en las filas
                     que el mes llenaba; las demas quedaban en blanco.

  TODO EL LIBRO .... openpyxl escribe formulas sin su resultado en cache, y
                     fidelidad.py descarta calcChain.xml. Excel abria el
                     papel y no recalculaba: REVISION ICA, que es casi toda
                     formulas, salia vacia.

Por eso estas pruebas miran la VISIBILIDAD y la marca de recalculo, no el
contenido de las celdas. El contenido ya lo cubren las otras.
"""

import re
import warnings
import zipfile
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.plantilla.deposito import depositar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def contexto():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


@pytest.fixture(scope="module")
def ruta(contexto, tmp_path_factory):
    salida = tmp_path_factory.mktemp("ver") / "papel.xlsx"
    depositar(contexto, salida)
    return salida


@pytest.fixture(scope="module")
def libro(ruta):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(ruta)


# ------------------------------------------------------------------ recalculo

def test_el_libro_pide_recalcularse_al_abrirlo(ruta):
    """Sin esto el papel se abre en blanco donde van las cifras.

    Es la peor forma de fallar que tiene: no da error, parece un papel
    vacio. Y no lo ve ninguna prueba que lea con openpyxl, porque openpyxl
    devuelve la formula tal cual, la calcule Excel o no.
    """
    xml = zipfile.ZipFile(ruta).read("xl/workbook.xml").decode("utf-8")
    calc = re.search(r"<calcPr[^>]*/?>", xml)
    assert calc, "el libro no declara calcPr"
    assert "fullCalcOnLoad" in calc.group(0), (
        "se descarta calcChain.xml y las formulas van sin valor en cache: "
        "sin fullCalcOnLoad, Excel puede abrir el papel sin calcular nada")


# -------------------------------------------------------------------- balance

def test_las_cuentas_del_balance_quedan_a_la_vista(libro):
    # Hasta max_row y no hasta 350: en openpyxl, LEER hoja.cell(row=f) crea
    # la celda, asi que recorrer de mas engorda la hoja y la prueba
    # siguiente --que comprueba donde termina-- veia 349 filas. Una prueba
    # contaminando a otra.
    hoja = libro["BALANCE"]
    con_dato = [f for f in range(5, hoja.max_row + 1)
                if hoja.cell(row=f, column=3).value]
    assert con_dato, "no se deposito ninguna cuenta"
    ocultas = [f for f in con_dato if hoja.row_dimensions[f].hidden]
    assert not ocultas, (
        "las cuentas %s se escribieron en filas ocultas de la plantilla; "
        "el papel se abre pareciendo vacio" % ocultas)


def test_el_balance_termina_donde_termina_la_evidencia(libro):
    """Las filas sobrantes se BORRAN, no se ocultan.

    Ocultarlas quitaba las filas en blanco pero dejaba la numeracion saltando
    de la 9 a la 350, que se lee como una hoja rota. Borrarlas se puede
    porque ninguna formula apunta ya a esta hoja: lo que cruza de hoja lo
    deposita el motor como valor.
    """
    hoja = libro["BALANCE"]
    # Se mira si la fila trae ALGO, no si trae cuenta: el balance del cliente
    # termina en filas de total, que legitimamente no llevan numero de cuenta.
    # Exigir cuenta en la ultima fila recortaria los totales del documento.
    con_dato = [f for f in range(5, hoja.max_row + 1)
                if any(c.value is not None for c in hoja[f])]
    assert hoja.max_row == max(con_dato), (
        "la hoja llega hasta la fila %d y el ultimo dato esta en la %d"
        % (hoja.max_row, max(con_dato)))
    ocultas = [f for f in range(1, hoja.max_row + 1)
               if hoja.row_dimensions[f].hidden]
    assert not ocultas, "quedan filas ocultas: %s" % ocultas


def test_la_cuenta_excluida_se_ve_con_la_cifra_que_la_delata(libro, contexto):
    """El papel afirmaba una exclusion que el lector no podia verificar.

    C13 avisa que 2368010090 se trato como contrapartida de pago por su
    saldo, y esa cuenta no aparecia en ninguna hoja. Ahora va al final del
    extracto con su saldo acumulado, que es la cifra por la que el motor la
    senala: es la unica 2368 con saldo positivo.
    """
    if not contexto.candidatas_sin_declarar:
        pytest.skip("este mes no hay cuentas excluidas por naturaleza")

    hoja = libro["BALANCE"]
    filas = {str(hoja.cell(row=f, column=3).value): f
             for f in range(5, hoja.max_row + 1)
             if hoja.cell(row=f, column=3).value}
    for cuenta in contexto.candidatas_sin_declarar:
        assert cuenta in filas, "la cuenta excluida %s no esta en el papel" % cuenta
        fila = filas[cuenta]
        # La exclusion se declara en la columna del motor. La fila trae ahora
        # las cifras del balance del cliente, sin tocar: es la evidencia por
        # la que el motor la senala, y antes no se podia ver.
        assert "EXCLUIDA" in str(hoja.cell(row=fila, column=11).value)


def test_el_saldo_acumulado_llega_al_papel(libro, contexto):
    """Se lee para M11 y antes moria en el motor: la columna salia vacia."""
    hoja = libro["BALANCE"]
    for f in range(5, hoja.max_row + 1):
        cuenta = str(hoja.cell(row=f, column=3).value or "")
        if cuenta in contexto.acumulados:
            assert hoja.cell(row=f, column=10).value == int(contexto.acumulados[cuenta])


# ------------------------------------------------------------------- borrador

def test_el_formulario_conserva_sus_formulas_en_todas_las_filas(libro):
    """BASE e IMPTO RTE ICA son del formulario, no del mes.

    Se borraban enteras y se reescribian solo donde el mes ponia datos, asi
    que el formulario quedaba con las dos columnas en blanco en la mayoria
    de sus renglones.
    """
    hoja = libro["BORRADOR TERLICA"]
    # La 27 es "OTRAS" y la plantilla no le pone formula.
    sin_formula = [f for f in range(10, 27)
                   if not str(hoja.cell(row=f, column=4).value or "").startswith("=")
                   or not str(hoja.cell(row=f, column=5).value or "").startswith("=")]
    assert not sin_formula, (
        "los renglones %s perdieron BASE o IMPTO RTE ICA" % sin_formula)


def test_las_sumas_cruzadas_del_formulario_sobreviven(libro):
    """Dos celdas de la columna F suman renglones que no son contiguos.

    No son datos del mes y no las reescribe nadie: si el borrado se las
    lleva, se pierden para siempre.
    """
    hoja = libro["BORRADOR TERLICA"]
    assert hoja["F17"].value == "=+G17+G16"
    assert hoja["F21"].value == "=+G20+G21+G25"


def test_los_totales_del_formulario_siguen_sumando_el_rango_completo(libro):
    hoja = libro["BORRADOR TERLICA"]
    assert hoja["D28"].value == "=SUM(D10:D27)"
    assert hoja["E28"].value == "=SUM(E10:E27)"
