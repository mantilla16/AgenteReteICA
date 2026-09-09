"""Envoltorio interactivo del motor de revision de ReteICA.

Pide carpeta, NIT, periodo y municipio por teclado y llama al mismo
motor_reteica.cli.main() que usa la linea de comandos -- no hay logica
nueva aqui, solo conveniencia para no escribir el comando a mano cada vez.

No cambia el flujo del manifiesto (D2): si la carpeta no trae
manifiesto.json completo, el motor sigue escribiendo la plantilla y
deteniendose igual que siempre. Este envoltorio solo pregunta lo minimo
para arrancar esa corrida.
"""

import sys
from pathlib import Path

from motor_reteica.cli import main as cli_main

MUNICIPIOS_DISPONIBLES = {"1": "santa_marta"}


def _preguntar(etiqueta, por_defecto=None):
    sufijo = " [%s]" % por_defecto if por_defecto else ""
    valor = input("%s%s: " % (etiqueta, sufijo)).strip()
    return valor or por_defecto


def _preguntar_obligatorio(etiqueta):
    valor = _preguntar(etiqueta)
    while not valor:
        print("   (obligatorio)")
        valor = _preguntar(etiqueta)
    return valor


def _preguntar_carpeta():
    carpeta = _preguntar_obligatorio("Carpeta con los archivos del cliente")
    while not Path(carpeta).is_dir():
        print("   -> no existe esa carpeta: %s" % carpeta)
        carpeta = _preguntar_obligatorio("Carpeta con los archivos del cliente")
    return carpeta


def main() -> int:
    print("=" * 70)
    print("MOTOR DE REVISION DE RETEICA")
    print("=" * 70)
    print()

    carpeta = _preguntar_carpeta()
    nit = _preguntar_obligatorio("NIT del contribuyente")
    periodo = _preguntar_obligatorio("Periodo a revisar (AAAA-MM, ej. 2026-07)")
    salida = _preguntar("Nombre del papel de trabajo a generar",
                        "papel_reteica_%s.xlsx" % periodo.replace("-", ""))

    respuesta_ia = _preguntar(
        "¿Ejecutar tambien la Revision Inteligente (IA-1/IA-3)? "
        "Requiere ANTHROPIC_API_KEY (s/N)", "n")
    con_ia = str(respuesta_ia).strip().lower().startswith("s")

    argv = ["--carpeta", carpeta, "--nit", nit, "--periodo", periodo,
            "--municipio", "santa_marta", "--salida", salida]
    if con_ia:
        argv.append("--revision-inteligente")

    print()
    print("-" * 70)
    try:
        codigo = cli_main(argv)
    except Exception as error:  # el envoltorio no debe morir con un traceback crudo
        print("\nERROR: %s: %s" % (type(error).__name__, error))
        codigo = 1
    print("-" * 70)

    print()
    try:
        input("Presiona ENTER para cerrar esta ventana...")
    except EOFError:
        pass  # sin consola interactiva (piped/CI): no hay nada que esperar
    return codigo


if __name__ == "__main__":
    sys.exit(main())
