"""Revision Inteligente sobre el papel ya generado.

La IA cuestiona el juicio; NO calcula. Este modulo no expone ninguna via para
modificar un ResultadoControl ni el Informe: solo produce comentarios que se
anexan al papel en una hoja aparte.
"""

import json
from dataclasses import dataclass

INSTRUCCION = (
    "Eres un revisor senior de auditoria. Lee el papel de trabajo ya generado "
    "y cuestiona el JUICIO, no la aritmetica.\n\n"
    "NO calcules ni recalcules ninguna cifra. El motor deterministico es la "
    "unica fuente de verdad; cualquier numero que quieras verificar ya fue "
    "calculado y cruzado.\n\n"
    "Concentrate en:\n"
    "1. Si la clasificacion de actividad de cada linea es defendible contra "
    "el concepto de la factura.\n"
    "2. Si la conclusion es consistente con las excepciones abiertas.\n"
    "3. Si alguna observacion deberia escalar a hallazgo.\n"
    "4. Si el alcance declarado deja algun riesgo sin advertir.\n\n"
    "Responde SOLO con un arreglo JSON de objetos con las claves "
    "'control', 'comentario' y 'sugerencia'."
)


@dataclass(frozen=True)
class Comentario:
    control: str
    texto: str
    sugerencia: str


def construir_prompt(ctx) -> str:
    controles = "\n".join(
        "- %s [%s] %s: %s" % (r.codigo, r.estado.value, r.nombre, r.detalle)
        for r in ctx.resultados)
    excepciones = "\n".join(
        "- [%s] %s (renglon %s, impacto %s): %s"
        % (e.severidad.value, e.control, e.renglon or "n/a", e.impacto_pesos,
           e.descripcion)
        for e in ctx.informe.excepciones_ordenadas) or "- ninguna"
    lineas = "\n".join(
        "- %s | NIT %s | %s | %s | %s"
        % (v.linea.referencia, v.linea.nit, v.linea.cuenta, v.linea.concepto,
           v.linea.retencion)
        for v in ctx.reconstruccion.lineas_valoradas)

    return (
        "%s\n\n"
        "=== CONTEXTO ===\n"
        "Cliente NIT %s, periodo %s, municipio %s.\n\n"
        "=== CONTROLES ===\n%s\n\n"
        "=== EXCEPCIONES ===\n%s\n\n"
        "=== LINEAS DEL AUXILIAR ===\n%s\n\n"
        "=== CONCLUSION GENERADA ===\n%s\n"
        % (INSTRUCCION, ctx.nit, ctx.periodo, ctx.municipio.nombre,
           controles, excepciones, lineas, ctx.informe.conclusion))


def aplicar_revision(ctx, respuesta: str) -> list:
    """Parsea la respuesta y devuelve comentarios inmutables.

    No toca ctx: la revision no puede alterar cifras ni estados de control.
    """
    try:
        crudo = json.loads(respuesta)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(crudo, list):
        return []

    comentarios = []
    for entrada in crudo:
        if not isinstance(entrada, dict):
            continue
        comentarios.append(Comentario(
            control=str(entrada.get("control", "")),
            texto=str(entrada.get("comentario", "")),
            sugerencia=str(entrada.get("sugerencia", "")),
        ))
    return comentarios
