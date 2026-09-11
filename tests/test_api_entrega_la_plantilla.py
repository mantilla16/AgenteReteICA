"""La interfaz web tiene que entregar el papel de la firma, no otro libro.

La etapa 6 cambio el entregable: el resultado es la plantilla real de la
firma, con sus nueve hojas y su logo. La CLI se cambio (--formato plantilla,
por defecto) y la API se quedo llamando a generar_papel(), el libro que se
inventaba el motor.

Nadie lo noto porque la API no tenia una sola prueba de extremo a extremo.
El error salio compilando el .exe y probandolo a mano: la interfaz --que es
lo que ve el usuario que hace doble clic-- devolvia el formato viejo.

Por eso esta prueba mira las HOJAS del archivo descargado y no que la
llamada no reviente: lo que fallaba devolvia 200 y un .xlsx perfectamente
valido, solo que el equivocado.
"""

import zipfile
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from motor_reteica.api.servidor import app

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"

# Las de la plantilla de la firma. El libro viejo traia otras
# ("Caratula", "Controles", "Recalculo"...), asi que basta con exigir estas.
HOJAS_DE_LA_FIRMA = {"Check List", "DECLARACION", "REVISION ICA",
                     "BORRADOR TERLICA", "BALANCE", "AUX FISCAL",
                     "CUADRO RETEICA"}


@pytest.fixture(scope="module")
def descargado(tmp_path_factory):
    """Sube las fixtures por HTTP y devuelve el .xlsx que responde la API."""
    with TestClient(app) as cliente:
        archivos = [("archivos", (r.name, r.read_bytes()))
                    for r in sorted(BASE.iterdir()) if r.is_file()]
        archivos += [("archivos", (r.name, r.read_bytes()))
                     for r in sorted((BASE / "facturas").iterdir())]
        respuesta = cliente.post(
            "/analizar", files=archivos,
            data={"nit": "819002433", "periodo": "2026-07",
                  "municipio": "santa_marta"})
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()

        papel = cliente.get(cuerpo["descarga"])
        assert papel.status_code == 200

    destino = tmp_path_factory.mktemp("api") / "papel.xlsx"
    destino.write_bytes(papel.content)
    return destino


def test_la_api_devuelve_el_papel_de_la_firma(descargado):
    libro = openpyxl.load_workbook(descargado)
    faltan = HOJAS_DE_LA_FIRMA - set(libro.sheetnames)
    assert not faltan, "la API no entrego la plantilla; faltan %s" % faltan


def test_el_papel_de_la_api_conserva_el_logo(descargado):
    """fidelidad.py restituye el EMF; openpyxl solo no lo lograria."""
    partes = set(zipfile.ZipFile(descargado).namelist())
    assert "xl/media/image1.emf" in partes


def test_el_papel_de_la_api_trae_las_cifras_del_motor(descargado):
    """D11, version final: lo que cruza de hoja va como numero.

    Antes esta prueba exigia que F20 fuera un SUMIF. Con formula, lo unico
    verificable era la cadena; el numero podia salir en blanco o en #N/D y
    la prueba seguia en verde. Ahora se comprueba la cifra.
    """
    hoja = openpyxl.load_workbook(descargado)["REVISION ICA"]
    assert isinstance(hoja["F20"].value, (int, float)), hoja["F20"].value
    assert hoja["N12"].value + hoja["N13"].value == 474561
