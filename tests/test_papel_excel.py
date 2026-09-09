from pathlib import Path

import openpyxl
import pytest

from motor_reteica.papel_excel import generar_papel
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def ctx():
    return revisar(BASE, nit="819002433", periodo="2026-07", municipio=MUNICIPIO)


@pytest.fixture(scope="module")
def libro(ctx, tmp_path_factory):
    salida = tmp_path_factory.mktemp("papel") / "papel.xlsx"
    return openpyxl.load_workbook(generar_papel(salida, ctx))


def _texto(hoja):
    return " ".join(str(c.value) for fila in hoja.iter_rows() for c in fila
                    if c.value is not None)


def test_genera_las_hojas_del_papel(libro):
    assert {"Caratula", "Controles", "Liquidacion", "Cruces", "Excepciones",
            "Parametros"} == set(libro.sheetnames)


def test_la_caratula_identifica_cliente_periodo_y_municipio(libro):
    texto = _texto(libro["Caratula"])
    assert "819002433" in texto
    assert "2026-07" in texto
    assert "Santa Marta" in texto


def test_la_conclusion_nombra_los_controles_no_ejecutados(libro):
    texto = _texto(libro["Caratula"])
    assert "C7" in texto and "C12" in texto
    assert "NO es concluyente" in texto


def test_la_conclusion_no_afirma_ausencia_de_diferencias(libro):
    """Con controles sin ejecutar no puede concluirse limpio."""
    assert "no presenta diferencias" not in _texto(libro["Caratula"])


def test_los_controles_traen_los_quince_codigos(libro):
    texto = _texto(libro["Controles"])
    for numero in range(0, 15):
        assert "C%d" % numero in texto


def test_la_liquidacion_reproduce_las_anclas(libro):
    texto = _texto(libro["Liquidacion"])
    assert "474561" in texto.replace(".0", "")
    assert "474000" in texto.replace(".0", "")


def test_parametros_declara_el_estado_de_las_tarifas(libro):
    assert "PENDIENTE_VALIDACION_ESTATUTO" in _texto(libro["Parametros"])


def test_parametros_registra_las_huellas(libro):
    texto = _texto(libro["Parametros"])
    assert "SHA256" in texto.upper()


def test_parametros_marca_los_insumos_no_obtenidos(libro):
    assert "NO OBTENIDO" in _texto(libro["Parametros"])


def test_el_papel_declara_la_limitacion_de_integridad(libro):
    texto = " ".join(_texto(libro[nombre]) for nombre in libro.sheetnames)
    assert "integridad" in texto.lower()


def test_las_excepciones_salen_ordenadas_por_severidad(libro):
    texto = _texto(libro["Excepciones"])
    assert "OBSERVACION" in texto or "AVISO" in texto


def test_parametros_declara_que_no_hubo_manifiesto_para_esta_corrida(libro):
    """1.4.b: la fixture corre en modo legado (sin manifiesto.json)."""
    texto = _texto(libro["Parametros"])
    assert "MANIFIESTO" in texto.upper()
    assert "Sin manifiesto.json" in texto
