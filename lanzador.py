"""Lanzador de doble-clic del Motor de Revision de ReteICA.

Arranca el servidor web local, espera a que el puerto responda, abre el
navegador por defecto y se mantiene vivo. Empaquetado con PyInstaller
(--onefile --noconsole): el usuario hace doble clic, se abre el navegador,
trabaja, y cierra con el boton "Cerrar" de la interfaz (que apaga el proceso).

Correr en desarrollo:  python lanzador.py
"""

import os
import socket
import sys
import threading
import time
import webbrowser

# Empaquetado con --noconsole, sys.stdout/stderr son None; cualquier libreria
# que imprima (uvicorn, logging) reventaria. Se redirigen antes de importar nada.
if sys.stdout is None or sys.stderr is None:
    _nulo = open(os.devnull, "w")
    sys.stdout = sys.stdout or _nulo
    sys.stderr = sys.stderr or _nulo

import uvicorn  # noqa: E402

from motor_reteica.api.servidor import app  # noqa: E402

HOST = "127.0.0.1"
PUERTO_INICIAL = 8010


def _puerto_libre(inicio: int, intentos: int = 50) -> int:
    for p in range(inicio, inicio + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, p))
                return p
            except OSError:
                continue
    return inicio


def _esperar_puerto(puerto: int, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((HOST, puerto)) == 0:
                return True
        time.sleep(0.25)
    return False


def _abrir_navegador(puerto: int) -> None:
    if _esperar_puerto(puerto):
        webbrowser.open("http://%s:%d" % (HOST, puerto))


def main() -> int:
    puerto = _puerto_libre(PUERTO_INICIAL)
    threading.Thread(target=_abrir_navegador, args=(puerto,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
