"""1.1 - manifiesto de fuentes."""

import json

import pytest

from motor_reteica.manifiesto import (NOMBRE_ARCHIVO, ManifiestoIncompleto,
                                      ROLES, leer_manifiesto)

MANIFIESTO_COMPLETO = {
    "nit": "819002433",
    "periodo": "2026-07",
    "municipio": "Santa Marta",
    "declarado_por": "Felipe Rios",
    "fecha": "2026-09-09",
    "archivos": {
        "borrador": "BORRADOR RTE ICA JULIO 2026.pdf",
        "auxiliar": "Auxiliar 2368 Julio 2026 - TERLICA SAS - DEF.xlsx",
        "balance": "PT Revision Industria y Comercio Julio-Terlica 2026.xlsx",
        "erp": "base_S_P00_07000134_ICA_11ICADA0920260811090007_ICA V1.xlsx",
        "facturas": "facturas",
        "pago_anterior": None,
    },
}


def _escribir(carpeta, datos):
    (carpeta / NOMBRE_ARCHIVO).write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def test_manifiesto_ausente_escribe_plantilla_y_detiene(tmp_path):
    with pytest.raises(ManifiestoIncompleto):
        leer_manifiesto(tmp_path)

    plantilla = json.loads((tmp_path / NOMBRE_ARCHIVO).read_text(encoding="utf-8"))
    assert set(plantilla["archivos"]) == set(ROLES)
    assert all(v == "PENDIENTE_DE_DECLARAR" for v in plantilla["archivos"].values())
    assert plantilla["nit"] is None


def test_manifiesto_no_reescribe_una_plantilla_ya_editada(tmp_path):
    """D2: si el auditor ya empezo a llenarla, no se pisa lo que escribio."""
    with pytest.raises(ManifiestoIncompleto):
        leer_manifiesto(tmp_path)
    ruta = tmp_path / NOMBRE_ARCHIVO
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["nit"] = "819002433"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ManifiestoIncompleto):
        leer_manifiesto(tmp_path)
    assert json.loads(ruta.read_text(encoding="utf-8"))["nit"] == "819002433"


def test_rol_pendiente_de_declarar_bloquea(tmp_path):
    datos = dict(MANIFIESTO_COMPLETO)
    datos["archivos"] = dict(datos["archivos"])
    datos["archivos"]["erp"] = "PENDIENTE_DE_DECLARAR"
    _escribir(tmp_path, datos)
    with pytest.raises(ManifiestoIncompleto, match="erp"):
        leer_manifiesto(tmp_path)


def test_rol_obligatorio_en_null_bloquea(tmp_path):
    datos = dict(MANIFIESTO_COMPLETO)
    datos["archivos"] = dict(datos["archivos"])
    datos["archivos"]["auxiliar"] = None
    _escribir(tmp_path, datos)
    with pytest.raises(ManifiestoIncompleto, match="auxiliar"):
        leer_manifiesto(tmp_path)


def test_rol_opcional_en_null_se_acepta_como_declaracion_explicita(tmp_path):
    _escribir(tmp_path, MANIFIESTO_COMPLETO)
    manifiesto = leer_manifiesto(tmp_path)
    assert manifiesto.archivos["pago_anterior"] is None


def test_json_invalido_es_manifiesto_incompleto(tmp_path):
    (tmp_path / NOMBRE_ARCHIVO).write_text("{ no es json", encoding="utf-8")
    with pytest.raises(ManifiestoIncompleto):
        leer_manifiesto(tmp_path)


def test_manifiesto_completo_se_lee(tmp_path):
    _escribir(tmp_path, MANIFIESTO_COMPLETO)
    manifiesto = leer_manifiesto(tmp_path)
    assert manifiesto.nit == "819002433"
    assert manifiesto.periodo == "2026-07"
    assert manifiesto.archivos["auxiliar"] == (
        "Auxiliar 2368 Julio 2026 - TERLICA SAS - DEF.xlsx")


def test_manifiesto_no_importa_nada_del_borrador_ni_de_parametros():
    """D1: el manifiesto declara identidad de archivos, nunca valores.

    Se verifica sobre las sentencias import, no sobre el texto: la palabra
    'borrador' aparece legitimamente en los comentarios que explican la
    regla (ver tests/test_parametros.py, mismo patron).
    """
    import ast
    import pathlib
    ruta = pathlib.Path(__file__).parent.parent / "motor_reteica" / "manifiesto.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos = [alias.name for alias in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            modulos = [nodo.module or ""]
        else:
            continue
        for modulo in modulos:
            assert "borrador" not in modulo
            assert "parametros" not in modulo
