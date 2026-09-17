"""El auditor puede eliminar sus revisiones del historial.

Se borran DOS cosas juntas: la fila en base y el archivo del papel en
disco. El orden importa -- primero el archivo, despues la fila -- para no
dejar un archivo huerfano si la fila falla al borrarse, o una fila
apuntando a un archivo que ya no existe.

Autorizacion: solo el dueño puede. La visibilidad ya viaja por WHERE en
todas las consultas; el borrado sigue la misma disciplina.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motor_reteica.api import servidor
from motor_reteica.api.servidor import app


USUARIO = {"id": "11111111-1111-1111-1111-111111111111",
           "usuario": "auditor", "nombre": "Auditor",
           "correo": "a@rbcol.co", "rol": "AUDITOR", "activo": True}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """API con base doblada, y un papel en disco listo para borrar."""
    monkeypatch.setattr(servidor, "_PAPELES", tmp_path)
    monkeypatch.setattr(servidor.db, "abrir", lambda: None)
    monkeypatch.setattr(servidor.db, "cerrar", lambda: None)
    monkeypatch.setattr(servidor.db, "usuario_de_sesion", lambda _h: USUARIO)
    with TestClient(app) as c:
        c.cookies.set(servidor.COOKIE, "token-de-prueba")
        yield c


def _papel(tmp_path: Path, corr: str) -> Path:
    p = tmp_path / ("%s.xlsx" % corr)
    p.write_bytes(b"PK\x03\x04 papel de prueba")
    return p


def test_borra_la_fila_y_el_archivo(cliente, tmp_path, monkeypatch):
    corr = "abc123abc123"
    papel = _papel(tmp_path, corr)
    borradas = []
    monkeypatch.setattr(servidor.db, "revision_de",
                        lambda c, u: {"corrida": c, "nit": "1"})
    monkeypatch.setattr(servidor.db, "borrar_revision",
                        lambda c, u: borradas.append(c) or True)

    r = cliente.delete("/revisiones/" + corr)
    assert r.status_code == 200
    assert r.json() == {"borrada": True}
    assert not papel.exists(), "el archivo del papel tenia que borrarse"
    assert borradas == [corr]


def test_una_revision_de_otro_no_se_puede_borrar(cliente, tmp_path,
                                                  monkeypatch):
    """El WHERE por usuario en revision_de() decide -- si dice None, es
    ajena y respondemos 404 igual que si no existiera. Nunca 'no autorizado'
    con el fin de no filtrar la existencia de la corrida."""
    papel = _papel(tmp_path, "otroaotroaotro"[:12])
    monkeypatch.setattr(servidor.db, "revision_de", lambda c, u: None)
    borradas = []
    monkeypatch.setattr(servidor.db, "borrar_revision",
                        lambda c, u: borradas.append(c) or False)

    r = cliente.delete("/revisiones/otroaotroaotr")
    assert r.status_code == 404
    assert papel.exists(), "no puede tocar archivos ajenos"
    assert borradas == [], "no debe llegar al DELETE de la BD"


def test_id_invalido_no_toca_el_disco(cliente, monkeypatch):
    """El id viaja en la URL: lo escribe quien quiera. Como con la
    descarga, un id que no matchee el formato no debe llegar al disco."""
    monkeypatch.setattr(servidor.db, "revision_de", lambda c, u: None)
    r = cliente.delete("/revisiones/..%2f..%2fetc%2fpasswd")
    assert r.status_code == 404


def test_si_el_archivo_no_esta_igual_borra_la_fila(cliente, monkeypatch):
    """La descarga distinguia entre fila y archivo (uno puede purgarse antes
    que el otro por politica de retencion). El borrado tiene que aceptar
    ese caso: si el archivo ya no esta, la fila igual sale."""
    monkeypatch.setattr(servidor.db, "revision_de",
                        lambda c, u: {"corrida": c, "nit": "1"})
    borradas = []
    monkeypatch.setattr(servidor.db, "borrar_revision",
                        lambda c, u: borradas.append(c) or True)

    r = cliente.delete("/revisiones/abc123abc123")
    assert r.status_code == 200
    assert r.json()["borrada"] is True
    assert borradas == ["abc123abc123"]
