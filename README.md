# Análisis del contraste NetFlow/AIOps frente a monitoreo convencional

Código de procesamiento y análisis estadístico de la tesis:

> **Monitoreo con telemetría NetFlow y algoritmos AIOps frente al monitoreo convencional en la disponibilidad del acceso a servicios críticos de un laboratorio de un instituto superior de Arequipa, 2026**
> Jonathan Vicente Alvarez Coloma · Ingeniería de Sistemas e Informática · Universidad Continental

Es el Anexo 7 del documento. Implementa el plan de análisis del apartado 3.6 sobre los registros de la ficha I1 (una fila por ejecución) en un diseño experimental de medidas repetidas con contrabalanceo AB/BA (30 escenarios, 60 ejecuciones).

> ⚠️ **Los datos sintéticos de este repositorio solo sirven para comprobar que el código funciona. No son resultados del estudio.** Todas sus salidas llevan el prefijo `SINTETICO_` y una marca visible en las figuras.

## Qué hace

| Paso | Detalle | Ecuación del documento |
|---|---|---|
| Indicadores por ejecución | MTTD con censura en T_máx; tramos de localización (L), ejecución correctiva (E) y verificación (V); MTTR; uptime | (1), (2), (3), (7) |
| Tasa de detección | Escenarios detectados dentro de T_máx por condición | (8) |
| Diferencias pareadas | Por escenario, con signo positivo a favor de la condición NetFlow/AIOps | (9) |
| Hipótesis | Prueba unilateral sobre la media de las diferencias (H1: μ_d > 0) | (10) |
| Normalidad y prueba | Shapiro-Wilk; t pareada si hay normalidad, si no Wilcoxon de rangos con signo (aproximación normal con corrección de continuidad) | (11) |
| Magnitud | IC 95 % de la diferencia media; d_z o r = Z/√N | (12), (13) |
| Detección | McNemar exacta (binomial) si hay menos de 25 pares discordantes; chi-cuadrado con corrección en otro caso | (14) |
| Comparaciones múltiples | Holm con m = 3 sobre HE 1 a HE 3 | (15) |
| Complementos | Efecto de periodo (AB frente a BA) y fase en vivo (MTTD emparejado por evento) | — |

Controles de calidad:

- **Autoprueba:** en cada ejecución se analiza primero un caso calculado a mano (censura, tramos, MTTR, uptime, signo de las diferencias, Holm y McNemar). Si algo no coincide, el script se detiene.
- **Doble cálculo:** cada prueba se calcula con SciPy y se verifica con Pingouin. Si los valores p difieren, el script se detiene.
- **Potencia:** reporta el efecto mínimo detectable con el n de pares (d_z = 0,465 con α = 0,05 y 0,564 con α = 0,05/3 para 30 pares).

## Instalación

Requiere Python 3.12 o superior.

```bash
pip install -r requirements.txt
```

## Uso

Prueba con datos sintéticos (semilla fija 20261011):

```bash
python scripts/analisis_contraste.py --sintetico
```

Con los datos reales de la ficha I1 y, opcionalmente, la fase en vivo:

```bash
python scripts/analisis_contraste.py --datos fichas_I1.csv --vivo eventos_vivo.csv
```

Las salidas van a `output/analisis_contraste/sintetico/` o `output/analisis_contraste/real/`:

- `indicadores_por_ejecucion.csv`, `diferencias_pareadas.csv`
- `contraste_hipotesis.csv` (HE 1 a HE 3 con p ajustado por Holm), `contraste_tramos_mttr.csv`, `efecto_periodo.csv`
- `resumen.md` con todas las tablas
- Figuras sin título (el título va en la leyenda del documento): diferencias pareadas, MTTD por par y tasa de detección por tipo de anomalía

## Formato de la ficha I1 (CSV)

Una fila por ejecución. Las horas van en UTC con formato ISO 8601. `plantilla_fichas_I1.csv` trae las columnas con un par de ejemplo.

| Columna | Contenido |
|---|---|
| `escenario` | Número del escenario (1 a 30) |
| `fase` | `principal` o `en vivo` (el contraste usa `principal`) |
| `tipo`, `severidad`, `carga`, `servicio`, `segmento`, `operador`, `franja`, `ventana_fondo` | Factores y variables de control del par |
| `condicion` | 0 = monitoreo convencional; 1 = NetFlow/AIOps |
| `orden`, `periodo` | AB o BA; 1 o 2 |
| `t_inicio`, `t_deteccion`, `t_localizacion`, `t_correccion`, `t_restauracion`, `t_fin` | Marcas de tiempo (vacío en `t_deteccion` si no hubo alerta) |
| `fuente_deteccion` | Origen de la alerta |
| `T_max_s`, `T_obs_s`, `T_indisp_s` | Ventana máxima de detección, ventana de observación y tiempo de indisponibilidad, en segundos |
| `anulada` | `True` si la ejecución se anuló (se excluye) |
| `incidencias` | Texto libre |

La fase en vivo usa otro CSV con `evento, t_inicio, t_deteccion_0, t_deteccion_1, T_max_s`.

## Cómo citar

ALVAREZ COLOMA, Jonathan Vicente. *analisis-contraste-netflow-aiops* [software]. Versión 1.0. 2026. Disponible en: https://github.com/jthnconti/analisis-contraste-netflow-aiops

## Licencia

MIT. Ver [LICENSE](LICENSE).
