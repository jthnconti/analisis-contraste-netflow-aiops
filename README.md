# analisis-contraste-netflow-aiops

Script en Python que procesa los registros de un experimento de monitoreo de red y aplica las pruebas estadísticas para comparar dos formas de detectar fallas: una basada en flujos NetFlow con un clasificador y otra basada en sondeo SNMP/ICMP. Acompaña una tesis de pregrado de ingeniería (Universidad Continental, 2026), que se cita aparte.

> ⚠️ El modo `--sintetico` genera datos inventados solo para probar el código. Sus archivos llevan el prefijo `SINTETICO_` y una marca en cada figura. No son datos del experimento.

## Funciones

- Calcula, para cada corrida, el tiempo hasta la primera alerta (con un tope de espera), el tiempo hasta reponer el servicio desglosado en tres tramos y la proporción de tiempo en servicio.
- Empareja las corridas de cada escenario y obtiene la diferencia entre ambas formas de monitoreo (positiva cuando gana la basada en flujos).
- Elige la prueba según la forma de las diferencias: Shapiro-Wilk y luego t de Student pareada o Wilcoxon, en ambos casos de una cola.
- Informa intervalo de confianza al 95 % y tamaño del efecto (d_z o r).
- Compara cuántos escenarios detecta cada forma con McNemar (exacta con pocos pares discordantes).
- Ajusta los valores p de las tres hipótesis con el método de Holm.
- Revisa si el orden de las corridas influyó (AB frente a BA) y, si se le entrega ese archivo, también procesa lo ocurrido con tráfico real.

## Verificaciones internas

- Antes de leer los datos corre un caso resuelto a mano; si cualquier valor no coincide, se detiene.
- Cada prueba se calcula con SciPy y se repite con Pingouin; si los valores p difieren, se detiene.
- Muestra el efecto mínimo detectable para el número de pares disponible.

## Requisitos e instalación

Python 3.12 o superior.

```bash
pip install -r requirements.txt
```

## Ejemplos

Con datos de prueba (semilla 20261011):

```bash
python scripts/analisis_contraste.py --sintetico
```

Con los registros reales y, opcionalmente, los eventos en vivo:

```bash
python scripts/analisis_contraste.py --datos fichas_I1.csv --vivo eventos_vivo.csv
```

Los resultados quedan en `output/analisis_contraste/sintetico/` o `output/analisis_contraste/real/`: tablas CSV por corrida, por par y por hipótesis, un `resumen.md` y figuras sin título.

## Formato de entrada

CSV con un registro por corrida y horas en UTC (ISO 8601). `plantilla_fichas_I1.csv` sirve de ejemplo.

| Campo | Significado |
|---|---|
| `escenario` | Identificador del escenario (1 a 30) |
| `fase` | `principal` o `en vivo`; las pruebas usan solo `principal` |
| `tipo`, `severidad`, `carga`, `servicio`, `segmento`, `operador`, `franja`, `ventana_fondo` | Características del escenario |
| `condicion` | 0 = sondeo SNMP/ICMP; 1 = flujos con clasificador |
| `orden`, `periodo` | Secuencia AB o BA; primera o segunda corrida |
| `t_inicio`, `t_deteccion`, `t_localizacion`, `t_correccion`, `t_restauracion`, `t_fin` | Marcas de tiempo; `t_deteccion` vacía si no hubo alerta |
| `fuente_deteccion` | Qué emitió la alerta |
| `T_max_s`, `T_obs_s`, `T_indisp_s` | Tope de espera, ventana observada y tiempo sin servicio, en segundos |
| `anulada` | `True` para descartar la corrida |
| `incidencias` | Notas libres |

Los eventos en vivo van en otro CSV con `evento, t_inicio, t_deteccion_0, t_deteccion_1, T_max_s`.

## Versión citada

La tesis usa la versión publicada como `v1.0` (commit `4f7377c`). Los cambios posteriores en este README no modifican el script.

## Licencia

MIT. Ver [LICENSE](LICENSE).
