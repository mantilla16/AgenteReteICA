"""La descarga del papel no puede depender de que worker atienda.

Salio de produccion: la revision terminaba bien, devolvia su enlace, y al
abrirlo contestaba "Papel no encontrado o expirado." sobre un archivo que
estaba en disco. La ruta vivia en un diccionario en memoria del proceso y
gunicorn corre cuatro workers: el POST que genera el papel y el GET que lo
descarga caen en procesos distintos. Fallaba tres de cada cuatro veces, que
es peor que fallar siempre -- a veces funcionaba.

El id tambien entra por la URL, asi que aqui se fija que no sirva para pedir
archivos que no son papeles.
"""

from pathlib import Path

import pytest

from motor_reteica.api import servidor


@pytest.fixture
def corrida(tmp_path, monkeypatch):
    """Un papel en disco, como lo deja depositar()."""
    monkeypatch.setattr(servidor, "_PAPELES", tmp_path)
    corr = "fe44a79fdda6"
    papel = tmp_path / ("%s.xlsx" % corr)
    papel.write_bytes(b"PK\x03\x04 no importa el contenido")
    return corr, papel


def test_la_ruta_se_deduce_sin_memoria_del_proceso(corrida):
    """Lo que fallaba: otro worker, sin haber visto nunca esta corrida."""
    corr, papel = corrida
    assert servidor._ruta_papel(corr) == papel


def test_una_corrida_que_no_existe_no_resuelve(corrida):
    assert servidor._ruta_papel("aaaaaaaaaaaa") is None


@pytest.mark.parametrize("id_torcido", [
    "../../../etc/passwd",
    "..%2f..%2fetc",
    "fe44a79fdda6/../../../etc/passwd",
    "FE44A79FDDA6",      # el id real es minusculo
    "fe44a79fdda",       # 11: corto
    "fe44a79fdda6a",     # 13: largo
    "",
    "zzzzzzzzzzzz",      # no es hexadecimal
])
def test_un_id_que_no_es_una_corrida_no_toca_el_disco(id_torcido, corrida):
    """El id viaja en la URL: lo escribe quien quiera, no el motor."""
    assert servidor._ruta_papel(id_torcido) is None


def test_no_sirve_otro_archivo_del_deposito(tmp_path, monkeypatch):
    """Solo el papel de esa corrida, no cualquier cosa que quede ahi."""
    monkeypatch.setattr(servidor, "_PAPELES", tmp_path)
    (tmp_path / "auxiliar_del_cliente.xlsx").write_bytes(b"datos del cliente")
    assert servidor._ruta_papel("0123456789ab") is None
