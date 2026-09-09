"""M7: identidad del programa que genero el papel.

El papel ya registra el SHA-256 de cada fuente. Eso prueba que los DATOS no
cambiaron, pero no dice con que CODIGO se procesaron. Un papel de trabajo
firmado que no se puede reproducir es indefendible: la pregunta "que version
genero esto" tiene que tener respuesta impresa.

La huella no se maquilla. Si el arbol tiene cambios sin commitear el papel lo
dice con el sufijo '+sucio', porque un papel generado sobre codigo no
versionado NO es reproducible. Si no hay git, dice 'sin-git' en vez de
inventar un valor.
"""

import subprocess
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
SIN_GIT = "sin-git"
SUFIJO_SUCIO = "+sucio"


def _git(*argumentos):
    try:
        salida = subprocess.run(
            ("git", *argumentos), cwd=_RAIZ, capture_output=True, text=True,
            timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if salida.returncode != 0:
        return None
    return salida.stdout.strip()


def huella_del_codigo() -> str:
    """Hash del commit, con marca si hay cambios sin commitear."""
    commit = _git("rev-parse", "--short", "HEAD")
    if not commit:
        return SIN_GIT

    # --porcelain limitado a esta carpeta: cambios en otros proyectos del
    # repositorio no ensucian la huella de este motor.
    sucio = _git("status", "--porcelain", "--", str(_RAIZ))
    return commit + SUFIJO_SUCIO if sucio else commit


def sello() -> str:
    from motor_reteica import __version__
    return "%s (%s)" % (__version__, huella_del_codigo())
