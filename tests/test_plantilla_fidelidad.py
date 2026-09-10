"""Etapa 6: guardar la plantilla sin degradarla.

El papel final es la plantilla real de la firma. Cargarla y volver a
guardarla con openpyxl PIERDE el logo (EMF), la otra imagen, dos de los tres
dibujos y la CONFIGURACION DE IMPRESION. En un documento que se imprime y se
firma eso no es cosmetico, y ademas es del tipo de dano que nadie nota hasta
que el papel ya salio.
"""

import zipfile
import warnings
from pathlib import Path

import openpyxl
import pytest

from motor_reteica.plantilla.fidelidad import guardar_conservando_formato

PLANTILLA = (Path(__file__).parent.parent / "motor_reteica" / "plantilla"
             / "PT_ReteICA_plantilla.xlsx")

# Medido sobre la plantilla real: esto es lo que openpyxl destruye.
_PARTES_FRAGILES = (
    "xl/media/image1.emf",
    "xl/media/image2.png",
    "xl/drawings/drawing1.xml",
    "xl/drawings/drawing2.xml",
    "xl/drawings/drawing3.xml",
    "xl/printerSettings/printerSettings1.bin",
    "xl/printerSettings/printerSettings2.bin",
    "xl/worksheets/_rels/sheet1.xml.rels",
    "xl/worksheets/_rels/sheet4.xml.rels",
    "xl/worksheets/_rels/sheet8.xml.rels",
)


def _cargar():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(PLANTILLA)


def _partes(ruta):
    with zipfile.ZipFile(ruta) as z:
        return set(z.namelist())


def test_openpyxl_a_secas_si_destruye_la_plantilla(tmp_path):
    """La premisa. Si algun dia openpyxl deja de romperla, esto avisa y el
    remiendo de fidelidad.py se puede simplificar."""
    salida = tmp_path / "crudo.xlsx"
    _cargar().save(salida)
    perdidas = [p for p in _PARTES_FRAGILES if p not in _partes(salida)]
    assert perdidas, "openpyxl ya no destruye nada: revisar si el remiendo sobra"
    assert "xl/media/image1.emf" in perdidas, "el logo deberia perderse sin remiendo"


def test_el_logo_y_la_impresion_sobreviven(tmp_path):
    salida = guardar_conservando_formato(_cargar(), PLANTILLA,
                                         tmp_path / "papel.xlsx")
    presentes = _partes(salida)
    faltantes = [p for p in _PARTES_FRAGILES if p not in presentes]
    assert faltantes == [], "se perdieron partes de la plantilla: %s" % faltantes


def test_no_se_pierde_ninguna_parte_salvo_la_cache_de_calculo(tmp_path):
    salida = guardar_conservando_formato(_cargar(), PLANTILLA,
                                         tmp_path / "papel.xlsx")
    perdidas = _partes(PLANTILLA) - _partes(salida)
    assert perdidas == {"xl/calcChain.xml"}, perdidas


def test_los_valores_escritos_si_llegan(tmp_path):
    """Conservar el formato no puede significar ignorar lo que se escribio."""
    libro = _cargar()
    libro["AUX FISCAL"]["M7"] = "VALOR DE PRUEBA DEL MOTOR"
    salida = guardar_conservando_formato(libro, PLANTILLA,
                                         tmp_path / "papel.xlsx")
    leido = openpyxl.load_workbook(salida)
    assert leido["AUX FISCAL"]["M7"].value == "VALOR DE PRUEBA DEL MOTOR"


def test_las_formulas_de_la_plantilla_siguen_siendo_formulas(tmp_path):
    """Si se congelaran a valor, el papel dejaria de estar vivo (D11)."""
    salida = guardar_conservando_formato(_cargar(), PLANTILLA,
                                         tmp_path / "papel.xlsx")
    leido = openpyxl.load_workbook(salida, data_only=False)
    assert str(leido["DECLARACION"]["K8"].value).startswith("=SUM")
    assert str(leido["AUX FISCAL"]["I19"].value).startswith("=SUM")


def test_la_hoja_del_logo_conserva_su_enlace_al_dibujo(tmp_path):
    """El archivo puede traer el EMF y aun asi no mostrarlo, si la hoja perdio
    su <drawing r:id>. Es el fallo silencioso de este remiendo."""
    salida = guardar_conservando_formato(_cargar(), PLANTILLA,
                                         tmp_path / "papel.xlsx")
    with zipfile.ZipFile(salida) as z:
        assert "<drawing" in z.read("xl/worksheets/sheet1.xml").decode("utf-8")


def test_el_resultado_lo_puede_volver_a_abrir_openpyxl(tmp_path):
    """Un paquete remendado a mano puede quedar corrupto: al menos que un
    lector de xlsx lo acepte y vea las 9 hojas."""
    salida = guardar_conservando_formato(_cargar(), PLANTILLA,
                                         tmp_path / "papel.xlsx")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        leido = openpyxl.load_workbook(salida)
    assert len(leido.sheetnames) == 9
    assert "Check List" in leido.sheetnames
