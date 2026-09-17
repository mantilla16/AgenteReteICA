"""El encargo: subir de a uno, ver que falta, y completar despues.

Antes se subia todo de golpe y se esperaba. Si faltaba el balance, el auditor
lo descubria al final, leyendo que C2 quedo NO EJECUTADO, y para arreglarlo
tenia que volver a subirlo todo.

Ahora cada documento se reconoce al llegar y la carpeta del encargo sobrevive
a la revision: se agrega lo que falto y se vuelve a revisar. Cada corrida deja
su propio registro -- en auditoria importa poder ver que algo se rehizo.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from motor_reteica.api import servidor
from motor_reteica.api.servidor import app

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"

USUARIO = {"id": "11111111-1111-1111-1111-111111111111",
           "usuario": "auditor", "nombre": "Auditor de prueba",
           "correo": "auditor@rbcol.co", "rol": "AUDITOR", "activo": True}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(servidor, "_ENCARGOS", tmp_path / "encargos")
    monkeypatch.setattr(servidor, "_PAPELES", tmp_path / "papeles")
    monkeypatch.setattr(servidor.db, "abrir", lambda: None)
    monkeypatch.setattr(servidor.db, "cerrar", lambda: None)
    monkeypatch.setattr(servidor.db, "usuario_de_sesion", lambda _h: USUARIO)
    monkeypatch.setattr(servidor.db, "crear_encargo", lambda _e, _u: None)
    monkeypatch.setattr(servidor.db, "tocar_encargo", lambda _e, **k: None)
    monkeypatch.setattr(servidor.db, "encargo_de",
                        lambda enc, usuario_id: {"id": enc,
                                                 "usuario_id": usuario_id})
    with TestClient(app) as c:
        c.cookies.set(servidor.COOKIE, "token-de-prueba")
        yield c


def _subir(cliente, enc, ruta: Path):
    return cliente.post("/encargos/%s/documentos" % enc,
                        files={"archivo": (ruta.name, ruta.read_bytes())})


def test_un_encargo_nace_vacio_y_no_se_puede_revisar(cliente):
    tablero = cliente.post("/encargos").json()
    assert tablero["encargo"]
    assert tablero["puede_revisar"] is False
    assert set(tablero["faltan_obligatorios"]) == {"borrador", "auxiliar"}


def test_cada_documento_se_reconoce_al_subirlo(cliente):
    """El punto del cambio: saber el rol AHORA, no en diez minutos."""
    enc = cliente.post("/encargos").json()["encargo"]

    tablero = _subir(cliente, enc, BASE / "borrador.pdf").json()
    assert tablero["insumos"]["borrador"] == "borrador.pdf"
    assert tablero["puede_revisar"] is False, "falta el auxiliar"

    tablero = _subir(cliente, enc, BASE / "auxiliar_2368.xlsx").json()
    assert tablero["insumos"]["auxiliar"] == "auxiliar_2368.xlsx"
    assert tablero["puede_revisar"] is True


def test_el_tablero_dice_que_controles_se_van_a_perder(cliente):
    """Que el auditor decida ANTES, no que lo lea en la conclusion."""
    enc = cliente.post("/encargos").json()["encargo"]
    _subir(cliente, enc, BASE / "borrador.pdf")
    tablero = _subir(cliente, enc, BASE / "auxiliar_2368.xlsx").json()

    assert "balance" in tablero["faltan"]
    assert "C2" in tablero["controles_en_riesgo"]

    tablero = _subir(cliente, enc, BASE / "balance.xlsx").json()
    assert "balance" not in tablero["faltan"]
    assert "C2" not in tablero["controles_en_riesgo"]


def test_subir_el_mismo_nombre_reemplaza_en_vez_de_duplicar(cliente):
    """Para corregir un export mal hecho sin empezar de cero."""
    enc = cliente.post("/encargos").json()["encargo"]
    _subir(cliente, enc, BASE / "auxiliar_2368.xlsx")
    tablero = _subir(cliente, enc, BASE / "auxiliar_2368.xlsx").json()
    assert tablero["insumos"]["auxiliar"] == "auxiliar_2368.xlsx"
    assert tablero["conflictos"] == [], "no puede verse como dos auxiliares"


def test_un_documento_se_puede_quitar(cliente):
    enc = cliente.post("/encargos").json()["encargo"]
    _subir(cliente, enc, BASE / "balance.xlsx")
    tablero = cliente.delete(
        "/encargos/%s/documentos/balance.xlsx" % enc).json()
    assert tablero["insumos"]["balance"] is None
    assert "C2" in tablero["controles_en_riesgo"]


def test_el_temporal_de_excel_no_entra(cliente):
    """~$archivo.xlsx es lo que deja Excel con el libro abierto. Se cuela al
    arrastrar la carpeta entera y no es un documento."""
    enc = cliente.post("/encargos").json()["encargo"]
    respuesta = cliente.post(
        "/encargos/%s/documentos" % enc,
        files={"archivo": ("~$PT Revision.xlsx", b"basura")})
    assert respuesta.status_code == 400


def test_un_encargo_ajeno_no_se_toca(cliente, monkeypatch):
    """La carpeta lleva documentos de un cliente: no basta con saber el id."""
    enc = cliente.post("/encargos").json()["encargo"]
    monkeypatch.setattr(servidor.db, "encargo_de", lambda e, u: None)
    respuesta = _subir(cliente, enc, BASE / "balance.xlsx")
    assert respuesta.status_code == 404


def test_un_id_que_no_es_un_encargo_no_toca_el_disco(cliente):
    respuesta = cliente.get("/encargos/..%2f..%2fetc")
    assert respuesta.status_code == 404


# --------------------------------------------------------------------------
# La revision ya no corre dentro de la peticion
# --------------------------------------------------------------------------

def test_revisar_contesta_de_inmediato_y_deja_la_fila_en_proceso(
        cliente, monkeypatch):
    """El 504 venia de aqui: la peticion duraba lo que durara el motor.

    Ahora contesta al instante con el id de la corrida, y el trabajo queda en
    un hilo. Ningun timeout intermedio -- nginx, Tailscale -- alcanza a
    dispararse, porque ninguna peticion espera.
    """
    creadas, corridas = [], []
    monkeypatch.setattr(servidor.db, "crear_revision_en_proceso",
                        lambda **c: creadas.append(c))
    monkeypatch.setattr(servidor, "_correr_revision",
                        lambda *a: corridas.append(a))

    enc = cliente.post("/encargos").json()["encargo"]
    _subir(cliente, enc, BASE / "borrador.pdf")
    _subir(cliente, enc, BASE / "auxiliar_2368.xlsx")

    respuesta = cliente.post("/encargos/%s/revisar" % enc,
                             data={"nit": "819002433", "periodo": "2026-07"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "en_proceso"
    assert cuerpo["corrida"]

    assert creadas[0]["corrida"] == cuerpo["corrida"]
    assert creadas[0]["encargo"] == enc
    assert corridas, "el trabajo tiene que quedar agendado"


def test_una_revision_que_falla_queda_registrada_con_el_motivo(monkeypatch):
    """No puede desaparecer: el auditor tiene que ver que la intento."""
    fallos = []
    monkeypatch.setattr(servidor.db, "fallar_revision",
                        lambda corrida, error: fallos.append((corrida, error)))
    monkeypatch.setattr(servidor.db, "terminar_revision",
                        lambda *a, **k: None)

    def revienta(*a, **k):
        raise RuntimeError("el auxiliar no tiene la columna de retencion")
    monkeypatch.setattr(servidor, "_ejecutar_revision", revienta)

    servidor._correr_revision("abc123abc123", "def456def456", "819002433",
                              "2026-07", "santa_marta", "", "")

    assert fallos, "un fallo silencioso es peor que el fallo"
    assert "columna de retencion" in fallos[0][1]


def test_el_progreso_se_va_contando(monkeypatch, tmp_path):
    """Para que la pantalla diga en que va, en vez de un 'Procesando' mudo."""
    pasos = []
    monkeypatch.setattr(servidor, "_ENCARGOS", tmp_path)
    (tmp_path / "abc123abc123").mkdir()
    try:
        servidor._ejecutar_revision(
            "111111111111", "abc123abc123", nit="1", periodo="2026-07",
            municipio="santa_marta", declarado_por="", api_key="",
            avisar=pasos.append)
    except Exception:
        pass          # sin documentos revienta; lo que importa es el aviso
    assert pasos and "Reconociendo" in pasos[0]
