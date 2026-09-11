"""Compila RevisionReteICA.exe con PyInstaller.

    python construir_exe.py

Existe porque la receta de compilacion no estaba escrita en ninguna parte y
el .exe distribuible se quedo atras del codigo. El riesgo no es olvidar un
flag cualquiera: es olvidar un DATO. El motor empaqueta dos archivos que no
son .py y que PyInstaller no descubre solo --

    web/index.html ................................ la interfaz
    motor_reteica/plantilla/PT_ReteICA_plantilla.xlsx  el papel de la firma

-- y sin el segundo el .exe arranca, analiza, y revienta justo al final, al
depositar el resultado. Ese archivo entro con la etapa 6, o sea DESPUES de
la ultima compilacion: un rebuild que copiara los flags viejos produciria
exactamente esa falla.

El .exe pesa ~120MB y esta en .gitignore a proposito: no pertenece al
repositorio, se genera cuando hay que distribuirlo.
"""

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
NOMBRE = "RevisionReteICA"

# (origen relativo a RAIZ, carpeta destino dentro del paquete). El destino
# tiene que replicar la ruta que el codigo espera: recursos.ruta_recurso()
# busca "web/..." bajo sys._MEIPASS, y deposito.PLANTILLA resuelve por
# __file__, que empaquetado cae en _MEIPASS/motor_reteica/plantilla.
DATOS = [
    ("web/index.html", "web"),
    ("motor_reteica/plantilla/PT_ReteICA_plantilla.xlsx",
     "motor_reteica/plantilla"),
]


def _verificar_datos() -> None:
    faltan = [o for o, _ in DATOS if not (RAIZ / o).exists()]
    if faltan:
        raise SystemExit("No estan los datos que hay que empaquetar: %s"
                         % ", ".join(faltan))


def _limpiar_andamiaje() -> None:
    """Borra build/ y el .spec, y avisa si no pudo.

    No se aborta por esto: el .exe ya esta hecho y es lo que se venia a
    buscar. Antes el borrado iba suelto dentro de main(), asi que si fallaba
    --OneDrive sincronizando, un antivirus leyendo el .pkg-- la excepcion se
    llevaba por delante el aviso de exito y dejaba 168MB de andamiaje en la
    carpeta sin que nadie se enterara. Una vez llegaron a un commit, y el
    .pkg de 125MB hizo que GitHub rechazara el push.

    La red de verdad es el .gitignore; esto solo deja la carpeta limpia.
    """
    for basura in ("build", "%s.spec" % NOMBRE):
        ruta = RAIZ / basura
        try:
            if ruta.is_dir():
                shutil.rmtree(ruta)
            else:
                ruta.unlink(missing_ok=True)
        except OSError as error:
            print("No se pudo borrar %s: %s (queda ignorado por git)"
                  % (ruta.name, error))


def main() -> int:
    _verificar_datos()
    separador = ";" if sys.platform == "win32" else ":"
    orden = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole",
             "--name", NOMBRE, "--icon", str(RAIZ / "icono_reteica.ico"),
             "--distpath", str(RAIZ), "--noconfirm"]
    for origen, destino in DATOS:
        orden += ["--add-data", "%s%s%s" % (RAIZ / origen, separador, destino)]
    orden.append(str(RAIZ / "lanzador.py"))

    print(" ".join(orden), "\n")
    codigo = subprocess.call(orden, cwd=str(RAIZ))
    if codigo == 0:
        _limpiar_andamiaje()
        exe = RAIZ / ("%s.exe" % NOMBRE)
        print("\nListo: %s (%.0f MB)" % (exe, exe.stat().st_size / 1e6))
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
