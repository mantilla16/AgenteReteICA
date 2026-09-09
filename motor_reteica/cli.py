"""Interfaz de linea de comandos del motor de revision de ReteICA."""

import argparse
import sys

from motor_reteica.identidad import IdentidadIncompatible
from motor_reteica.papel_excel import generar_papel
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import revisar
from motor_reteica.tipos import Estado

MUNICIPIOS = {"santa_marta": MUNICIPIO}

_SIMBOLO = {Estado.OK: "OK ", Estado.FALLA: "!! ", Estado.NO_EJECUTADO: "-- "}

# M6: el codigo de salida refleja la CONCLUSION, no solo el impacto en pesos.
# Antes era `0 if impacto_total == 0 else 1`, y devolvia exito en la corrida de
# julio 2026 -- con C7 y C12 sin ejecutar y la conclusion diciendo que la
# revision no era concluyente.
LIMPIO = 0
CON_EXCEPCIONES = 1
INSUMO_FALTANTE = 2
NO_CONCLUYENTE = 3


def _codigo_de_salida(informe) -> int:
    """Traduce el estado de la revision a un codigo para automatizacion.

    NO_CONCLUYENTE pesa mas que CON_EXCEPCIONES: una excepcion encontrada es
    un resultado; un control sin ejecutar es la AUSENCIA de resultado, y eso
    es lo que impide concluir.
    """
    if informe.controles_no_ejecutados:
        return NO_CONCLUYENTE
    if informe.controles_en_falla:
        return CON_EXCEPCIONES
    return LIMPIO if informe.puede_concluir_limpio else CON_EXCEPCIONES


def _tablero(ctx) -> None:
    print("\nREVISION DE RETEICA - NIT %s - periodo %s - %s"
          % (ctx.nit, ctx.periodo, ctx.municipio.nombre))
    print("-" * 78)
    for resultado in ctx.resultados:
        print("%s%-4s %-52s %s"
              % (_SIMBOLO[resultado.estado], resultado.codigo,
                 resultado.nombre[:52], resultado.estado.value))
    print("-" * 78)
    print("Auxiliar 2368         %14s" % ctx.total_auxiliar)
    print("Reporte del ERP       %14s" % ctx.total_erp)
    print("Base gravable         %14s" % ctx.reconstruccion.total_base)
    print("Impuesto contable     %14s" % ctx.reconstruccion.total_impuesto_contable)
    print("Impuesto declarable   %14s"
          % ctx.reconstruccion.total_impuesto_declarable)
    print("Declarado (renglon 24)%14s" % ctx.borrador.renglones["24"])
    print("-" * 78)
    print("Excepciones: %d | impacto cuantificado: %s pesos"
          % (len(ctx.informe.excepciones_ordenadas), ctx.informe.impacto_total))
    print("Conclusion limpia: %s"
          % ("SI" if ctx.informe.puede_concluir_limpio else "NO"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="motor_reteica",
        description="Revisa un borrador de declaracion de ReteICA contra los "
                    "libros y genera el papel de trabajo.")
    parser.add_argument("--carpeta", required=True,
                        help="carpeta con borrador.pdf, auxiliar_2368.xlsx, "
                             "balance.xlsx, sap_retenciones.xlsx y facturas/")
    parser.add_argument("--nit", required=True, help="NIT del contribuyente")
    parser.add_argument("--periodo", required=True, help="periodo AAAA-MM")
    parser.add_argument("--municipio", default="santa_marta",
                        choices=sorted(MUNICIPIOS))
    parser.add_argument("--salida", default="papel_reteica.xlsx")
    args = parser.parse_args(argv)

    try:
        ctx = revisar(args.carpeta, nit=args.nit, periodo=args.periodo,
                      municipio=MUNICIPIOS[args.municipio])
    except IdentidadIncompatible as error:
        print("C0 DETUVO LA REVISION: %s" % error, file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print("Falta un insumo obligatorio: %s" % error, file=sys.stderr)
        return 2

    _tablero(ctx)
    ruta = generar_papel(args.salida, ctx)
    print("\nPapel de trabajo generado en %s" % ruta)
    return _codigo_de_salida(ctx.informe)


if __name__ == "__main__":
    raise SystemExit(main())
