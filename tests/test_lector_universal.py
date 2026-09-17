"""El motor lee CUALQUIER estructura de insumo, no solo la de TERLICA.

Bug reportado por el auditor: 'El motor no reconocio: Auxiliar 2368
Agroingenium agosto-sep.XLSX, Balance Agroingenium jul agost.XLS. No se
usaran.' Dos causas distintas:

  1. El balance venia como .XLS de SAP -- TSV UTF-16 con extension .xls,
     ni openpyxl ni xlrd lo entienden.
  2. El auxiliar venia de otra transaccion (FAGLL03H) con etiquetas
     distintas (Asignacion / Importe en moneda local) en vez de las de
     FBL3N (Cuenta / Importe en ML).

Y la exigencia era clara: 'debe procesar cualquier documento (No
negociable)'. Estas pruebas fijan que los formatos reales de dos clientes
distintos se aceptan sin tocar el codigo.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.parametros.columnas import detectar_tipo_documento

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
INSUMOS = Path(r"Z:\EMPRESAS\DSAB\1_Auditoria\NIAS\GRUPO DAABON\AGROINGENIUM"
               r"\60. Impuesto\2. Reteica\8. Agosto\PT")
AUX_AGRO = INSUMOS / "Auxiliar 2368 Agroingenium agosto-sep.XLSX"
BAL_AGRO = INSUMOS / "Balance Agroingenium jul agost.XLS"


# --------------------------------------------------------------------------
# Formatos de contenedor
# --------------------------------------------------------------------------

def test_xlsx_moderno_se_lee():
    """La ruta que ya andaba: openpyxl sobre .xlsx."""
    filas = leer_filas(BASE / "auxiliar_2368.xlsx")
    assert filas, "un xlsx no puede salir vacio"


@pytest.mark.skipif(not BAL_AGRO.exists(),
                    reason="requiere el balance real de Agroingenium")
def test_xls_de_sap_es_tsv_utf16_y_se_lee():
    """SAP exporta 'Saldos de cuentas de mayor' con extension .xls pero es
    texto tabulado UTF-16 LE. Antes fallaba con InvalidFileException; ahora
    se detecta por firma de bytes."""
    filas = leer_filas(BAL_AGRO)
    assert len(filas) > 100, "un balance real trae cientos de filas"


# --------------------------------------------------------------------------
# Deteccion del tipo de documento
# --------------------------------------------------------------------------

@pytest.mark.parametrize("nombre,tipo_esperado", [
    ("auxiliar_2368.xlsx", "auxiliar"),
    ("balance.xlsx",       "balance"),
    ("sap_retenciones.xlsx", "erp"),
])
def test_terlica_se_clasifica_bien(nombre, tipo_esperado):
    """Regresion: la ruta de siempre no se puede haber roto."""
    assert detectar_tipo_documento(leer_filas(BASE / nombre)) == tipo_esperado


@pytest.mark.skipif(not AUX_AGRO.exists(),
                    reason="requiere el auxiliar real de Agroingenium")
def test_auxiliar_agroingenium_se_reconoce():
    """Etiquetas distintas (Asignacion, Importe en moneda local) que
    fallaban con la firma unica de TERLICA."""
    assert detectar_tipo_documento(leer_filas(AUX_AGRO)) == "auxiliar"


@pytest.mark.skipif(not BAL_AGRO.exists(),
                    reason="requiere el balance real de Agroingenium")
def test_balance_agroingenium_se_reconoce():
    """El balance de Agroingenium usa las MISMAS etiquetas que TERLICA
    (Cta.mayor, Saldo Haber per.inf.); el problema era el contenedor."""
    assert detectar_tipo_documento(leer_filas(BAL_AGRO)) == "balance"


# --------------------------------------------------------------------------
# Lectura del auxiliar en los dos formatos vivos
# --------------------------------------------------------------------------

def test_auxiliar_de_terlica_da_el_total_conocido():
    """Regresion: el reader rico sigue funcionando."""
    lineas = leer_auxiliar(BASE / "auxiliar_2368.xlsx")
    assert sum(l.retencion for l in lineas) == Decimal("474561")


@pytest.mark.skipif(not AUX_AGRO.exists(),
                    reason="requiere el auxiliar real de Agroingenium")
def test_auxiliar_de_agroingenium_da_el_total_correcto():
    """El reader agregado suma el subtotal que SAP reporta -- no cada
    detalle. Los detalles traen contra-abonos legitimos y sumarlos con
    .copy_abs() los duplicaba. El total tiene que ser el neto."""
    lineas = leer_auxiliar(AUX_AGRO)
    total = sum(l.retencion for l in lineas)
    assert total == Decimal("2879769"), (
        "esperado 2.879.769 (grand total del auxiliar); dio %s" % total)


@pytest.mark.skipif(not AUX_AGRO.exists(),
                    reason="requiere el auxiliar real de Agroingenium")
def test_auxiliar_de_agroingenium_emite_una_linea_por_cuenta():
    """El modo agregado NO da detalle por linea -- solo el subtotal por
    cuenta. Cinco lineas de detalle por cada cuenta 2368 serian menos que
    lo que hay, y decenas por cuenta serian erroneas."""
    lineas = leer_auxiliar(AUX_AGRO)
    cuentas = {l.cuenta for l in lineas}
    assert cuentas == {"2368010005", "2368010008", "2368010010"}
    assert len(lineas) == 3, "una linea agregada por cuenta"
