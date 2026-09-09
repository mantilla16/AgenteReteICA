"""Carril propio de controles de IA (D7).

La IA NO modifica jamas C0..C15. Sus salidas entran como controles PROPIOS con
los mismos estados y la misma maquinaria de excepciones, de modo que un
hallazgo suyo bloquee la conclusion limpia igual que uno de C9 -- y no muera
en un anexo que nadie lee.

  IA-1  plausibilidad de la clasificacion   (3.1.bis capa 2, grado 2)
  IA-3  consistencia de la conclusion        (grado 3)

IA-2 (extraccion documental por imagen, 5.1) no se implementa aqui: P2 cerro
que no se construye OCR hasta que aparezca una factura escaneada de verdad.

CONDICION DE REDACCION DE IA-1, la mas importante de todo el modulo: el
control se llama PLAUSIBILIDAD, no clasificacion. Su OK significa "la IA no
encontro contradiccion", NUNCA "la clasificacion es correcta". Si se redactara
como lo segundo, el papel LAVARIA la circularidad: quedaria un OK que parece
verificacion independiente cuando el reparto se sigue tomando del borrador.
Eso es PEOR que no tener el control.
"""

import json

from motor_reteica.ia.cliente import ClienteIA
from motor_reteica.tipos import (REF_CUENTA, Estado, Excepcion,
                                 ResultadoControl, Severidad)

VERSION_PROMPT = "1.0.0"

_SISTEMA = (
    "Eres un revisor senior de auditoria en Colombia. NO calculas ni "
    "recalculas ninguna cifra: el motor deterministico es la unica fuente de "
    "verdad y cualquier numero ya fue calculado y cruzado. Respondes SOLO con "
    "un arreglo JSON valido, sin texto alrededor."
)

_PROMPT_IA1 = """Cada linea de abajo es un registro contable de retencion de
industria y comercio, con el renglon del formulario en que el contribuyente la
clasifico.

Tu tarea es de PLAUSIBILIDAD, no de clasificacion: di si la descripcion PUEDE
o NO caer en ese renglon. No propones la clasificacion correcta como veredicto;
senalas contradicciones defendibles.

Reglas:
- Si el concepto es compatible con el renglon, no lo reportes.
- Reporta solo contradicciones que defenderias ante un socio.
- CITA el texto en que te basas.
- No menciones cifras: no las tienes y no las necesitas.

Responde SOLO con un arreglo JSON de objetos con las claves:
  "linea"        el identificador de la linea, tal como aparece abajo
  "contradice"   true o false
  "evidencia"    el texto del concepto y el del renglon en que te basas
  "actividad_sugerida"  codigo CIIU de 4 digitos, o "" si no lo sabes

LINEAS:
{lineas}
"""

_PROMPT_IA3 = """Abajo esta el estado de los controles de un papel de trabajo
ya generado y su conclusion. NO recalcules nada.

Cuestiona el juicio:
- Es la conclusion consistente con las excepciones abiertas?
- Hay observaciones que deberian escalar a hallazgo?
- Queda algun riesgo sin advertir dado el alcance declarado?

Responde SOLO con un arreglo JSON de objetos con las claves:
  "asunto"     de que habla
  "comentario" que observas
  "escalar"    true si crees que algo deberia subir de severidad

CONTROLES:
{controles}

EXCEPCIONES:
{excepciones}

CONCLUSION GENERADA:
{conclusion}
"""


def _no_ejecutado(codigo, nombre, motivo) -> ResultadoControl:
    return ResultadoControl(codigo=codigo, nombre=nombre,
                            estado=Estado.NO_EJECUTADO,
                            detalle="no se ejecuto: %s" % motivo)


def _json_o_vacio(texto):
    try:
        crudo = json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return None
    return crudo if isinstance(crudo, list) else None


# --------------------------------------------------------------------------
# IA-1
# --------------------------------------------------------------------------

def _lineas_para_prompt(reconstruccion, mapa, borrador):
    """5.7: el problema no son las filas, son las COLUMNAS.

    Se envia la poblacion completa -- IA-1 juzga linea por linea -- pero solo
    concepto, cuenta y renglon. NO se envia NIT, ni nombre del tercero, ni
    montos, ni la razon social del cliente.
    """
    descripciones = {a.codigo: a.descripcion for a in borrador.actividades}
    lineas = []
    for indice, valorada in enumerate(reconstruccion.lineas_valoradas, start=1):
        linea = valorada.linea
        codigo = mapa.get((linea.nit, valorada.tarifa)) or mapa.get(linea.nit)
        if codigo is None:
            continue
        lineas.append(
            "L%d | cuenta %s | concepto: %s | renglon declarado: %s %s"
            % (indice, linea.cuenta, linea.concepto, codigo,
               descripciones.get(codigo, "")))
    return lineas, {"L%d" % i: v for i, v in
                    enumerate(reconstruccion.lineas_valoradas, start=1)}


def ia1_plausibilidad(reconstruccion, borrador, municipio, cliente=None,
                      mapa=None) -> ResultadoControl:
    nombre = "Plausibilidad de la clasificacion (IA)"
    mapa = mapa if mapa is not None else getattr(reconstruccion, "mapa", {})
    lineas, indice = _lineas_para_prompt(reconstruccion, mapa, borrador)
    if not lineas:
        return _no_ejecutado("IA-1", nombre, "no hay lineas clasificadas")

    prompt = _PROMPT_IA1.format(lineas="\n".join(lineas))
    respuesta = (cliente or ClienteIA()).preguntar(_SISTEMA, prompt)
    if not respuesta.hubo_respuesta:
        return _no_ejecutado("IA-1", nombre, respuesta.motivo)

    crudo = _json_o_vacio(respuesta.texto)
    if crudo is None:
        return _no_ejecutado("IA-1", nombre,
                             "el modelo no devolvio un arreglo JSON valido")

    excepciones = []
    for entrada in crudo:
        if not isinstance(entrada, dict) or not entrada.get("contradice"):
            continue
        clave = str(entrada.get("linea", ""))
        valorada = indice.get(clave)
        if valorada is None:
            continue
        linea = valorada.linea
        sugerida = str(entrada.get("actividad_sugerida", "") or "")

        # La CONSECUENCIA la calcula el motor, no la IA. Si la actividad
        # sugerida esta en otra clase de tarifa, hay impacto en pesos.
        tarifa_sugerida = municipio.tarifas_actividad.get(sugerida)
        if tarifa_sugerida is not None and tarifa_sugerida != valorada.tarifa:
            severidad = Severidad.HALLAZGO
            base = valorada.base_derivada
            impacto = abs(base * (tarifa_sugerida - valorada.tarifa))
        else:
            severidad = Severidad.OBSERVACION
            impacto = None

        descripcion = ("%s: la IA senala una contradiccion entre el concepto y "
                       "el renglon declarado. Evidencia: %s"
                       % (linea.referencia, entrada.get("evidencia", "")))
        if sugerida:
            descripcion += " Actividad que sugiere: %s." % sugerida

        excepciones.append(Excepcion(
            severidad=severidad, control="IA-1", descripcion=descripcion,
            renglon=linea.cuenta, tipo_referencia=REF_CUENTA,
            **({"impacto_pesos": impacto} if impacto is not None else {})))

    detalle = ("%d linea(s) revisadas por %s. LIMITE: esto es PLAUSIBILIDAD, no "
               "clasificacion. Que no haya contradicciones significa que la IA "
               "no encontro ninguna, NO que la clasificacion sea correcta: el "
               "reparto se sigue tomando del borrador."
               % (len(lineas), respuesta.modelo))

    return ResultadoControl(
        codigo="IA-1", nombre=nombre,
        estado=Estado.FALLA if excepciones else Estado.OK,
        detalle=("%d excepcion(es); %s" % (len(excepciones), detalle)
                 if excepciones else detalle),
        excepciones=tuple(excepciones))


# --------------------------------------------------------------------------
# IA-3
# --------------------------------------------------------------------------

def ia3_consistencia(resultados, informe, cliente=None) -> ResultadoControl:
    nombre = "Consistencia de la conclusion (IA)"
    controles = "\n".join("- %s [%s] %s" % (r.codigo, r.estado.value, r.nombre)
                          for r in resultados)
    excepciones_texto = "\n".join(
        "- [%s] %s: %s" % (e.severidad.value, e.control, e.descripcion)
        for e in informe.excepciones_ordenadas) or "- ninguna"

    prompt = _PROMPT_IA3.format(controles=controles,
                                excepciones=excepciones_texto,
                                conclusion=informe.conclusion)
    respuesta = (cliente or ClienteIA()).preguntar(_SISTEMA, prompt)
    if not respuesta.hubo_respuesta:
        return _no_ejecutado("IA-3", nombre, respuesta.motivo)

    crudo = _json_o_vacio(respuesta.texto)
    if crudo is None:
        return _no_ejecutado("IA-3", nombre,
                             "el modelo no devolvio un arreglo JSON valido")

    excepciones = []
    for entrada in crudo:
        if not isinstance(entrada, dict):
            continue
        comentario = str(entrada.get("comentario", "")).strip()
        if not comentario:
            continue
        excepciones.append(Excepcion(
            severidad=(Severidad.OBSERVACION if entrada.get("escalar")
                       else Severidad.AVISO),
            control="IA-3",
            descripcion="%s: %s" % (entrada.get("asunto", "conclusion"),
                                    comentario)))

    detalle = ("revisado por %s; la IA no modifica cifras ni estados de "
               "control" % respuesta.modelo)
    return ResultadoControl(
        codigo="IA-3", nombre=nombre,
        estado=Estado.FALLA if excepciones else Estado.OK,
        detalle=("%d comentario(s); %s" % (len(excepciones), detalle)
                 if excepciones else detalle),
        excepciones=tuple(excepciones))
