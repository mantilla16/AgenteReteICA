import shutil
from pathlib import Path

import pytest

from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.balance import leer_balance
from motor_reteica.ingesta.borrador_pdf import leer_borrador
from motor_reteica.ingesta.sap_retenciones import leer_sap_retenciones
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.reconstruccion import reconstruir

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
MAPA = {"800193573": "5224", "811033997": "4669", "830028245": "9903",
        "900392924": "9609", "901670478": "7490"}


@pytest.fixture(scope="session")
def base_fixtures():
    return BASE


@pytest.fixture(scope="session")
def lineas():
    return leer_auxiliar(BASE / "auxiliar_2368.xlsx")


@pytest.fixture(scope="session")
def saldos():
    return leer_balance(BASE / "balance.xlsx")


@pytest.fixture(scope="session")
def erp():
    return leer_sap_retenciones(BASE / "sap_retenciones.xlsx")


@pytest.fixture(scope="session")
def borrador():
    return leer_borrador(BASE / "borrador.pdf")


@pytest.fixture(scope="session")
def recon(lineas, erp):
    return reconstruir(lineas, erp, MUNICIPIO, MAPA)


@pytest.fixture
def carpeta_de_corrida(tmp_path):
    """Copia de las fixtures para correr el CLI encima.

    El CLI escribe atestacion.plantilla.json en la carpeta que analiza (D2),
    asi que apuntarlo a tests/fixtures la ensucia -- y las fixtures son de
    SOLO LECTURA por protocolo del proyecto. Ya paso una vez: el archivo
    llego a quedar commiteado dentro de las fixtures.
    """
    destino = tmp_path / "corrida"
    shutil.copytree(BASE, destino)
    return destino
