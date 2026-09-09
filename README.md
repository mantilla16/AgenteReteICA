# Motor de Revisión de ReteICA

Revisa el **borrador de la declaración mensual de ReteICA preparado por el cliente**
contra los libros, y produce un papel de trabajo con evidencia y hallazgos.

No liquida el impuesto. El borrador es **objeto de prueba**, nunca fuente de parámetros.

- Spec: `../docs/superpowers/specs/2026-09-08-revision-reteica-design.md`
- Plan: `../docs/superpowers/plans/2026-09-08-motor-reteica.md`

## Uso

```bash
python -m motor_reteica.cli --carpeta <dir> --nit 819002433 --periodo 2026-07 --salida papel.xlsx
```

La carpeta debe contener:

| Archivo | Obligatorio | Si falta |
|---|---|---|
| `borrador.pdf` | Sí | Se detiene |
| `auxiliar_2368.xlsx` | Sí | Se detiene |
| `balance.xlsx` | No | C2 → NO EJECUTADO |
| `sap_retenciones.xlsx` | No | C3, C4, C5 → NO EJECUTADO |
| `facturas/*.pdf` | No | C11 → NO EJECUTADO |

Códigos de salida: `0` sin impacto cuantificado, `1` con impacto, `2` la revisión se detuvo.

## Los tres estados

`OK`, `FALLA` y **`NO EJECUTADO`**. La ausencia de un insumo nunca produce OK, y cualquier
control en FALLA o NO EJECUTADO impide una conclusión limpia. Un control que el municipio
no exige se marca `aplica=False` y no cuenta como insumo faltante.

## De dónde sale cada cifra

| Cifra | Fuente |
|---|---|
| Tarifa | Cuenta contable (`2368010007` → 7‰) |
| Retención | Libro auxiliar 2368 |
| **Base** | **Reporte del ERP** |
| Agrupación en renglones | Borrador, solo para agrupar |

**La base no se deriva de la retención.** El auxiliar guarda la retención ya redondeada:
derivarla da 49.012.586 frente a los 49.012.569 reales, y recalcular `base × tarifa`
devolvería la retención por construcción, volviendo circular a C4. Sin reporte del ERP,
`base_es_derivada=True` y C4 se reporta NO EJECUTADO.

## Controles

| Cód | Control |
|---|---|
| C0 | Identidad de las fuentes (detiene el proceso) |
| C1 | El formulario cuadra consigo mismo |
| C2 | Balance vs auxiliar por cuenta |
| C3 | Auxiliar vs reporte del ERP por tercero |
| C4 | Recálculo base × tarifa por tercero |
| C5 | Coherencia cuenta contable vs código de retención |
| C6 | Clasificación de actividad **por línea** |
| C7 | Tarifas vs Acuerdo municipal |
| C8 | Corte |
| C9 | Reconstrucción vs borrador (terminal) |
| C10 | Redondeo al mil por renglón |
| C11 | Cotejo de facturas fuente |
| C12 | Continuidad con el mes anterior |
| C13 | Formales y trazabilidad de insumos |
| C14 | Compras vs servicios (si el municipio lo exige) |

## Fuera de alcance

- **Integridad.** El motor parte de la 2368: no detecta al proveedor gravado al que nunca
  se le retuvo. Queda declarado en el papel.
- **Autorretención de ICA.** Otra fuente (libro auxiliar de ingresos) y otro riesgo.
- **Municipios distintos de Santa Marta.** La arquitectura los admite; añadir uno es
  escribir un archivo en `parametros/municipios/`.

## Pruebas

```bash
python -m pytest -q
```

151 pruebas, incluida `test_mutacion.py`, que altera deliberadamente cada insumo y verifica
que dispare el control correcto y solo ese. Un motor probado solo con datos correctos no
está probado.

## Trampas del formato ya blindadas con test

- El NIT está en la columna `Asignación` del auxiliar, no en `Tercero`.
- El movimiento del periodo está en `Saldo Haber per.inf.`, no en `Saldo acumulado`.
- La cuenta `2368010090` es contrapartida de pago y se excluye del universo.
- El reporte del ERP se titula "RETENCIÓN IVA COLOMBIA" aunque sea de ICA, y trae base
  bruta con IVA junto a la base sujeta.
- El formulario imprime `31 = 27+28+29`, que es **falso**; la ecuación real es `31 = 27+29+30`.
- La primera fecha de una factura suele ser la autorización de la DIAN, no la emisión.
