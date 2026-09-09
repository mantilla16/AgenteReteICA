"""Prueba de mutacion.

Un motor probado solo con datos correctos no esta probado. Cada mutacion
altera un dato y verifica que dispare el control esperado, que los demas
sigan en OK, y que el caso limpio no dispare nada.
"""

import shutil
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.identidad import IdentidadIncompatible
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.tipos import Estado

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture
def carpeta(tmp_path):
    destino = tmp_path / "caso"
    shutil.copytree(BASE, destino)
    return destino


def _revisar(carpeta):
    return revisar(carpeta, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


def _estado(ctx, codigo):
    return next(r for r in ctx.resultados if r.codigo == codigo).estado


def _mutar_celda(ruta, hoja, marcador, columna, valor):
    libro = openpyxl.load_workbook(ruta)
    pagina = libro[hoja] if hoja else libro.worksheets[0]
    for fila in pagina.iter_rows():
        if any(str(c.value).strip() == marcador for c in fila):
            fila[columna].value = valor
    libro.save(ruta)


# --------------------------------------------------------------------------
# Guardia contra falsos positivos
# --------------------------------------------------------------------------

def test_el_caso_limpio_no_dispara_nada_grave(carpeta):
    """Julio 2026 solo debe producir observaciones sin impacto.

    C6 y C11 marcan clasificacion y cotejo documental; C13 marca que no se
    obtuvo la declaracion y el pago del mes anterior. Ninguna cuesta pesos.
    """
    ctx = _revisar(carpeta)
    en_falla = sorted(r.codigo for r in ctx.resultados if r.estado is Estado.FALLA)
    assert en_falla == ["C11", "C13", "C6"]
    assert ctx.informe.impacto_total == Decimal("0")


def test_c13_senala_el_pago_anterior_no_obtenido(carpeta):
    """El papel manual de julio concluyo limpio sin este insumo."""
    ctx = _revisar(carpeta)
    c13 = next(r for r in ctx.resultados if r.codigo == "C13")
    assert any("mes anterior" in e.descripcion for e in c13.excepciones)


def test_un_tercero_sin_renglon_no_revienta_el_motor(carpeta):
    """Antes lanzaba KeyError; ahora debe clasificarse y reportarse."""
    _mutar_celda(carpeta / "sap_retenciones.xlsx", None, "830028245", 6, 9999999)
    ctx = _revisar(carpeta)
    assert "SIN_CLASIFICAR" in ctx.reconstruccion.por_actividad
    assert _estado(ctx, "C9") is Estado.FALLA


# --------------------------------------------------------------------------
# Identidad: detiene el proceso
# --------------------------------------------------------------------------

def test_periodo_equivocado_detiene_el_proceso(carpeta):
    with pytest.raises(IdentidadIncompatible):
        revisar(carpeta, nit="819002433", periodo="2026-06", municipio=MUNICIPIO)


def test_nit_equivocado_detiene_el_proceso(carpeta):
    with pytest.raises(IdentidadIncompatible):
        revisar(carpeta, nit="900000000", periodo="2026-07", municipio=MUNICIPIO)


# --------------------------------------------------------------------------
# Mutaciones dirigidas
# --------------------------------------------------------------------------

def test_mutar_un_saldo_del_balance_dispara_c2(carpeta):
    _mutar_celda(carpeta / "balance.xlsx", "BALANCE", "2368010010", 8, 400000)
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C2") is Estado.FALLA
    assert _estado(ctx, "C3") is Estado.OK
    assert _estado(ctx, "C9") is Estado.OK


def test_mutar_una_retencion_del_erp_dispara_c3(carpeta):
    _mutar_celda(carpeta / "sap_retenciones.xlsx", None, "830028245", 7, 99999)
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C3") is Estado.FALLA
    assert _estado(ctx, "C2") is Estado.OK


def test_mutar_una_base_del_erp_dispara_c4(carpeta):
    _mutar_celda(carpeta / "sap_retenciones.xlsx", None, "830028245", 6, 9999999)
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C4") is Estado.FALLA


def test_mutar_una_retencion_del_auxiliar_dispara_c2_y_c3(carpeta):
    _mutar_celda(carpeta / "auxiliar_2368.xlsx", None, "FE338057", 11, -50000)
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C2") is Estado.FALLA
    assert _estado(ctx, "C3") is Estado.FALLA


def test_mover_una_linea_a_otra_cuenta_dispara_c5(carpeta):
    _mutar_celda(carpeta / "auxiliar_2368.xlsx", None, "250530", 3, "2368010007")
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C5") is Estado.FALLA


# --------------------------------------------------------------------------
# Insumos ausentes: NO_EJECUTADO, nunca OK
# --------------------------------------------------------------------------

def test_retirar_el_balance_deja_c2_no_ejecutado(carpeta):
    (carpeta / "balance.xlsx").unlink()
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C2") is Estado.NO_EJECUTADO
    assert ctx.informe.puede_concluir_limpio is False


def test_retirar_el_erp_deja_c3_c4_y_c5_no_ejecutados(carpeta):
    (carpeta / "sap_retenciones.xlsx").unlink()
    ctx = _revisar(carpeta)
    for codigo in ("C3", "C4", "C5"):
        assert _estado(ctx, codigo) is Estado.NO_EJECUTADO, codigo


def test_sin_erp_el_recalculo_no_finge_estar_bien(carpeta):
    """Sin base del ERP el recalculo seria circular; debe declararse."""
    (carpeta / "sap_retenciones.xlsx").unlink()
    ctx = _revisar(carpeta)
    assert ctx.reconstruccion.base_es_derivada is True
    c4 = next(r for r in ctx.resultados if r.codigo == "C4")
    assert "circular" in c4.detalle


def test_retirar_las_facturas_deja_c11_no_ejecutado(carpeta):
    shutil.rmtree(carpeta / "facturas")
    ctx = _revisar(carpeta)
    assert _estado(ctx, "C11") is Estado.NO_EJECUTADO
    assert "facturas" not in ctx.insumos_obtenidos


def test_los_insumos_faltantes_aparecen_en_c13(carpeta):
    (carpeta / "balance.xlsx").unlink()
    ctx = _revisar(carpeta)
    c13 = next(r for r in ctx.resultados if r.codigo == "C13")
    assert any("balance" in e.descripcion for e in c13.excepciones)
