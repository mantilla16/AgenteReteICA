"""1.1/1.5/1.6 - pipeline.revisar() a traves del manifiesto (no del modo
legado de nombres literales).

Copia las fixtures de julio 2026 a nombres AL ESTILO del cliente real (con
espacios y guiones, distintos de auxiliar_2368.xlsx/balance.xlsx/etc.) y
declara un manifiesto.json apuntando a esos nombres. No se toca
tests/fixtures/**: se copia a tmp_path.
"""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.identidad import IdentidadIncompatible
from motor_reteica.manifiesto import ManifiestoIncompleto, NOMBRE_ARCHIVO
from motor_reteica.papel_excel import generar_papel
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"

NOMBRES_ESTILO_CLIENTE = {
    "borrador": "BORRADOR RTE ICA JULIO 2026.pdf",
    "auxiliar": "Auxiliar 2368 Julio 2026 - TERLICA SAS - DEF.xlsx",
    "balance": "PT Revision Industria y Comercio Julio-Terlica 2026.xlsx",
    "erp": "base_S_P00_07000134_ICA V1.xlsx",
}


@pytest.fixture
def carpeta_estilo_cliente(tmp_path):
    """Fixtures de julio 2026, renombradas como las entregaria el cliente,
    mas un manifiesto.json que declara el mapeo."""
    destino = tmp_path / "carpeta_cliente"
    destino.mkdir()
    shutil.copy(BASE / "borrador.pdf", destino / NOMBRES_ESTILO_CLIENTE["borrador"])
    shutil.copy(BASE / "auxiliar_2368.xlsx", destino / NOMBRES_ESTILO_CLIENTE["auxiliar"])
    shutil.copy(BASE / "balance.xlsx", destino / NOMBRES_ESTILO_CLIENTE["balance"])
    shutil.copy(BASE / "sap_retenciones.xlsx", destino / NOMBRES_ESTILO_CLIENTE["erp"])
    shutil.copytree(BASE / "facturas", destino / "facturas")

    manifiesto = {
        "nit": "819002433",
        "periodo": "2026-07",
        "municipio": "Santa Marta",
        "declarado_por": "prueba automatizada",
        "fecha": "2026-09-09",
        "archivos": dict(NOMBRES_ESTILO_CLIENTE, facturas="facturas",
                         pago_anterior=None),
    }
    (destino / NOMBRE_ARCHIVO).write_text(
        json.dumps(manifiesto, ensure_ascii=False), encoding="utf-8")
    return destino


def test_revisar_via_manifiesto_reproduce_las_anclas(carpeta_estilo_cliente):
    """1.1 END CONDITION 5: corre sin renombrar a la convencion legado."""
    ctx = revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
                  municipio=MUNICIPIO)
    assert ctx.total_auxiliar == Decimal("474561")
    assert ctx.total_erp == Decimal("474561")
    assert ctx.reconstruccion.total_base == Decimal("49012569")
    assert ctx.reconstruccion.total_impuesto_declarable == Decimal("474000")
    assert ctx.manifiesto is not None
    assert ctx.manifiesto.declarado_por == "prueba automatizada"


def test_revisar_via_manifiesto_registra_huellas_con_nombres_reales(carpeta_estilo_cliente):
    ctx = revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
                  municipio=MUNICIPIO)
    assert set(ctx.huellas) >= {"auxiliar", "balance", "borrador", "erp"}


def test_manifiesto_incompleto_detiene_con_mensaje_util(carpeta_estilo_cliente):
    datos = json.loads((carpeta_estilo_cliente / NOMBRE_ARCHIVO).read_text(encoding="utf-8"))
    datos["archivos"]["erp"] = "PENDIENTE_DE_DECLARAR"
    (carpeta_estilo_cliente / NOMBRE_ARCHIVO).write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ManifiestoIncompleto, match="erp"):
        revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
               municipio=MUNICIPIO)


def test_manifiesto_con_nit_distinto_al_invocado_se_detiene(carpeta_estilo_cliente):
    datos = json.loads((carpeta_estilo_cliente / NOMBRE_ARCHIVO).read_text(encoding="utf-8"))
    datos["nit"] = "900000000"
    (carpeta_estilo_cliente / NOMBRE_ARCHIVO).write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(IdentidadIncompatible):
        revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
               municipio=MUNICIPIO)


def test_manifiesto_con_municipio_distinto_al_invocado_se_detiene(carpeta_estilo_cliente):
    datos = json.loads((carpeta_estilo_cliente / NOMBRE_ARCHIVO).read_text(encoding="utf-8"))
    datos["municipio"] = "Barranquilla"
    (carpeta_estilo_cliente / NOMBRE_ARCHIVO).write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(IdentidadIncompatible):
        revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
               municipio=MUNICIPIO)


def test_archivo_del_tipo_equivocado_en_un_rol_se_detiene(carpeta_estilo_cliente):
    """1.5/1.6: el auditor declara el balance donde iba el auxiliar."""
    datos = json.loads((carpeta_estilo_cliente / NOMBRE_ARCHIVO).read_text(encoding="utf-8"))
    datos["archivos"]["auxiliar"] = NOMBRES_ESTILO_CLIENTE["balance"]
    (carpeta_estilo_cliente / NOMBRE_ARCHIVO).write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(IdentidadIncompatible, match="balance"):
        revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
               municipio=MUNICIPIO)


def test_facturas_como_lista_de_archivos_sueltos(tmp_path):
    """La carpeta real del cliente trae las facturas sueltas junto con los
    demas insumos, sin subcarpeta; el manifiesto las declara como lista."""
    destino = tmp_path / "carpeta_facturas_sueltas"
    destino.mkdir()
    shutil.copy(BASE / "borrador.pdf", destino / NOMBRES_ESTILO_CLIENTE["borrador"])
    shutil.copy(BASE / "auxiliar_2368.xlsx", destino / NOMBRES_ESTILO_CLIENTE["auxiliar"])
    for factura in ("FE10.pdf", "250530.pdf", "FE338057.pdf"):
        shutil.copy(BASE / "facturas" / factura, destino / factura)

    manifiesto = {
        "nit": "819002433", "periodo": "2026-07", "municipio": "Santa Marta",
        "declarado_por": "prueba automatizada", "fecha": "2026-09-09",
        "archivos": {
            "borrador": NOMBRES_ESTILO_CLIENTE["borrador"],
            "auxiliar": NOMBRES_ESTILO_CLIENTE["auxiliar"],
            "balance": None, "erp": None, "pago_anterior": None,
            "facturas": ["FE10.pdf", "250530.pdf", "FE338057.pdf"],
        },
    }
    (destino / NOMBRE_ARCHIVO).write_text(
        json.dumps(manifiesto, ensure_ascii=False), encoding="utf-8")

    ctx = revisar(destino, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)
    assert len(ctx.facturas) == 3
    assert "facturas" in ctx.insumos_obtenidos

    # El papel debe poder generarse: la lista de facturas no es un tipo
    # que openpyxl acepte escribir directo en una celda.
    salida = generar_papel(destino / "papel.xlsx", ctx)
    assert salida.exists()


def test_manifiesto_ausente_usa_el_modo_legado(carpeta_estilo_cliente):
    """1.6: sin manifiesto.json en la carpeta, se resuelve por convencion
    literal -- las fixtures de prueba dependen de este comportamiento."""
    (carpeta_estilo_cliente / NOMBRE_ARCHIVO).unlink()
    with pytest.raises(FileNotFoundError):
        revisar(carpeta_estilo_cliente, nit="819002433", periodo="2026-07",
               municipio=MUNICIPIO)  # nombres estilo cliente, no literal
