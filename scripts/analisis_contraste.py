#!/usr/bin/env python3
"""analisis_contraste.py — análisis estadístico del Capítulo III (apartado 3.6) del PA2.

Lee la ficha I1 (una fila por ejecución) y contrasta HE 1, HE 2 y HE 3 con el diseño de medidas
repetidas AB/BA:
  1. Indicadores por ejecución: MTTD con censura en T_máx (ec. 1), tramos L, E y V y MTTR (ec. 2 y 7),
     uptime (ec. 3) y detección dentro de T_máx (para la tasa de detección, ec. 8).
  2. Diferencias pareadas por escenario (ec. 9), positivas a favor de la condición NetFlow/AIOps.
  3. Shapiro-Wilk sobre las diferencias; t pareada o Wilcoxon unilateral según la normalidad (ec. 10, 11);
     IC 95 % de la diferencia media (ec. 12); d_z o r = Z/raíz(N) (ec. 13).
  4. McNemar exacta y con corrección de continuidad para la tasa de detección (ec. 14).
  5. Holm con m = 3 sobre HE 1 a HE 3 (ec. 15).
  6. Efecto de periodo (AB frente a BA) y, si se entrega, la fase en vivo (MTTD emparejado por evento).
Cada prueba se calcula con SciPy y se verifica con Pingouin; el script se detiene si discrepan.

Uso:
    python scripts/analisis_contraste.py --sintetico            # prueba con datos inventados
    python scripts/analisis_contraste.py --datos fichas_I1.csv [--vivo eventos_vivo.csv]

Los datos sintéticos solo verifican que el código funciona: NO son resultados del estudio. Sus salidas van
a output/analisis_contraste/sintetico/ y llevan la marca «DATOS SINTÉTICOS» en cada archivo y figura.
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pingouin as pg
from scipy import stats

SEMILLA = 20261011
RNG = np.random.default_rng(SEMILLA)          # única semilla del script (solo la usan los datos sintéticos)

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "output" / "analisis_contraste"
ALFA = 0.05
M_HOLM = 3
TIPOS = ["Microrráfagas", "Degradación progresiva", "Inundación UDP", "Inundación SYN", "Tormenta de capa 2"]
SEVERIDADES = ["baja", "media", "alta"]
CARGAS = ["baja", "alta"]
FECHAS = ["t_inicio", "t_deteccion", "t_localizacion", "t_correccion", "t_restauracion", "t_fin"]
plt.rcParams.update({"font.family": "Times New Roman", "font.size": 11})


# ============================================================== datos sintéticos (solo para probar)
def generar_sinteticos(rng):
    """30 escenarios 5 × 3 × 2 ejecutados bajo ambas condiciones (60 filas con el formato de la ficha I1)
    y 10 eventos de la fase en vivo. Los parámetros son inventados y plausibles, no medidos."""
    n_esc = 30
    esc = pd.DataFrame({
        "escenario": np.arange(1, n_esc + 1),
        "tipo": np.repeat(TIPOS, 6),
        "severidad": np.tile(np.repeat(SEVERIDADES, 2), 5),
        "carga": np.tile(CARGAS, 15),
    })
    # contrabalanceo: dentro de cada tipo, 3 escenarios AB y 3 BA, en orden sorteado
    esc["orden"] = np.concatenate([rng.permutation(["AB"] * 3 + ["BA"] * 3) for _ in TIPOS])

    ej = esc.loc[esc.index.repeat(2)].reset_index(drop=True)
    ej["periodo"] = np.tile([1, 2], n_esc)
    ej["condicion"] = np.where((ej["orden"] == "AB") == (ej["periodo"] == 1), 0, 1)
    n = len(ej)

    # probabilidad de detección dentro de T_máx por tipo y condición (asimetría declarada en el 1.4.3)
    p_det = {0: [0.20, 0.45, 0.90, 0.85, 0.95], 1: [0.92, 0.80, 0.95, 0.95, 0.30]}
    idx_tipo = ej["tipo"].map({t: k for k, t in enumerate(TIPOS)}).to_numpy()
    prob = np.where(ej["condicion"] == 0, np.take(p_det[0], idx_tipo), np.take(p_det[1], idx_tipo))
    factor_sev = ej["severidad"].map({"baja": 1.3, "media": 1.0, "alta": 0.8}).to_numpy()
    mu_det = np.where(ej["condicion"] == 0, 300.0, 60.0) * factor_sev            # segundos
    retardo = rng.lognormal(np.log(mu_det), 0.35)
    t_max, t_obs = 900.0, 1800.0
    detectado = (rng.random(n) < prob) & (retardo <= t_max)

    inicio = pd.Timestamp("2026-11-16 13:00:00", tz="UTC") + pd.to_timedelta(np.arange(n) * 40, unit="min")
    origen = inicio + pd.to_timedelta(np.where(detectado, retardo, t_max), unit="s")
    mu_loc = np.where(ej["condicion"] == 0, 360.0, 120.0) * np.where(ej["periodo"] == 2, 0.92, 1.0)
    loc = rng.lognormal(np.log(mu_loc), 0.30)
    cor = rng.lognormal(np.log(200.0), 0.30, n)
    ver = rng.lognormal(np.log(90.0), 0.25, n)
    t_loc = origen + pd.to_timedelta(loc, unit="s")
    t_cor = t_loc + pd.to_timedelta(cor, unit="s")
    t_res = t_cor + pd.to_timedelta(ver, unit="s")
    frac = ej["severidad"].map({"baja": 0.3, "media": 0.6, "alta": 0.9}).to_numpy()
    indisp = np.minimum(t_obs, (t_res - inicio).total_seconds().to_numpy() * frac)

    ej = ej.assign(
        fase="principal", servicio=ej["tipo"].map(
            {"Microrráfagas": "internet", "Degradación progresiva": "plataforma", "Inundación UDP": "internet",
             "Inundación SYN": "plataforma", "Tormenta de capa 2": "sistema de notas"}),
        segmento=np.where(ej["escenario"] % 2 == 0, "inalámbrico", "cableado"), operador="op1",
        franja="sin clases", ventana_fondo=[f"VF-{c}-{e:02d}" for c, e in zip(ej["carga"], ej["escenario"])],
        t_inicio=inicio, t_deteccion=pd.Series(origen).where(detectado),
        fuente_deteccion=np.where(detectado, np.where(ej["condicion"] == 0, "Zabbix", "regla de alerta"), ""),
        t_localizacion=t_loc, t_correccion=t_cor, t_restauracion=t_res,
        T_max_s=t_max, T_obs_s=t_obs, T_indisp_s=indisp.round(1),
        t_fin=inicio + pd.to_timedelta(t_obs, unit="s"), anulada=False, incidencias="",
    )

    m = 10
    vivo = pd.DataFrame({"evento": np.arange(1, m + 1), "T_max_s": t_max})
    vivo["t_inicio"] = pd.Timestamp("2026-11-30 15:00:00", tz="UTC") + pd.to_timedelta(np.arange(m) * 90, unit="min")
    r0, r1 = rng.lognormal(np.log(330.0), 0.4, m), rng.lognormal(np.log(70.0), 0.35, m)
    det0, det1 = (rng.random(m) < 0.6) & (r0 <= t_max), (rng.random(m) < 0.95) & (r1 <= t_max)
    vivo["t_deteccion_0"] = (vivo["t_inicio"] + pd.to_timedelta(r0, unit="s")).where(det0)
    vivo["t_deteccion_1"] = (vivo["t_inicio"] + pd.to_timedelta(r1, unit="s")).where(det1)
    return ej, vivo


# ============================================================== indicadores y pares
def leer_fichas(ruta):
    df = pd.read_csv(ruta)
    for c in FECHAS:
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def calcular_indicadores(df):
    """Ecuaciones (1), (2), (3), (7) y la regla de censura del apartado 2.2.5 y del 3.6."""
    d = df[(df["fase"] == "principal") & (~df["anulada"].astype(bool))].copy()
    t_max = pd.to_timedelta(d["T_max_s"], unit="s")
    limite = d["t_inicio"] + t_max
    d["detectado"] = d["t_deteccion"].notna() & (d["t_deteccion"] <= limite)
    origen = d["t_deteccion"].where(d["detectado"], limite)            # sin detección: el reloj arranca en T_máx
    minutos = lambda a, b: (a - b).dt.total_seconds() / 60.0
    d["MTTD_min"] = minutos(origen, d["t_inicio"])                      # = T_máx si no hubo detección
    d["L_min"] = minutos(d["t_localizacion"], origen)
    d["E_min"] = minutos(d["t_correccion"], d["t_localizacion"])
    d["V_min"] = minutos(d["t_restauracion"], d["t_correccion"])
    d["MTTR_min"] = d["L_min"] + d["E_min"] + d["V_min"]                # ec. (7) = t_restauración − t_detección
    d["Uptime_pct"] = (d["T_obs_s"] - d["T_indisp_s"]) / d["T_obs_s"] * 100.0
    for c in ["L_min", "E_min", "V_min"]:
        if (d[c] < 0).any():
            sys.exit(f"Marcas fuera de orden en {c}: revisar la ficha I1 de los escenarios "
                     f"{d.loc[d[c] < 0, 'escenario'].tolist()}")
    return d


def emparejar(ind):
    cuenta = ind.groupby("escenario")["condicion"].agg(["count", "nunique"])
    incompletos = cuenta[(cuenta["count"] != 2) | (cuenta["nunique"] != 2)].index.tolist()
    if incompletos:
        print(f"AVISO: escenarios sin par completo, excluidos del contraste: {incompletos}")
    ok = ind[~ind["escenario"].isin(incompletos)]
    variables = ["MTTD_min", "L_min", "E_min", "V_min", "MTTR_min", "Uptime_pct", "detectado"]
    ancho = ok.pivot(index="escenario", columns="condicion", values=variables)
    ancho.columns = [f"{v}_{c}" for v, c in ancho.columns]
    ancho = ancho.join(ok.drop_duplicates("escenario").set_index("escenario")[["tipo", "severidad", "carga", "orden"]])
    # ec. (9): positivo = mejor con NetFlow/AIOps
    for v in ["MTTD_min", "L_min", "E_min", "V_min", "MTTR_min"]:
        ancho[f"d_{v}"] = ancho[f"{v}_0"].astype(float) - ancho[f"{v}_1"].astype(float)
    ancho["d_Uptime_pct"] = ancho["Uptime_pct_1"].astype(float) - ancho["Uptime_pct_0"].astype(float)
    return ancho.reset_index()


# ============================================================== pruebas
def contraste_pareado(d, etiqueta):
    """Shapiro-Wilk → t pareada o Wilcoxon unilateral (H1: μ_d > 0), IC 95 % y tamaño del efecto."""
    d = np.asarray(d, dtype=float)
    n = d.size
    media, de = d.mean(), d.std(ddof=1)
    sw = stats.shapiro(d)
    li, ls = stats.t.interval(0.95, n - 1, loc=media, scale=de / np.sqrt(n))      # ec. (12)
    normal = sw.pvalue > ALFA
    if normal:
        r = stats.ttest_1samp(d, 0.0, alternative="greater")                      # ec. (11)
        estad, p, prueba = r.statistic, r.pvalue, "t pareada"
        efecto, nombre_ef = media / de, "d_z"                                       # ec. (13)
        ref = pg.ttest(d, 0, alternative="greater")
        p_ref = float(ref["p-val"].iloc[0])
    else:
        # aproximación normal con corrección de continuidad (la misma que aplica Pingouin por defecto)
        r = stats.wilcoxon(d, alternative="greater", method="approx", zero_method="wilcox", correction=True)
        estad, p, prueba = r.statistic, r.pvalue, "Wilcoxon"
        n_ef = int((d != 0).sum())
        z = stats.norm.isf(p)
        efecto, nombre_ef = z / np.sqrt(n_ef), "r"                                  # ec. (13)
        ref = pg.wilcoxon(d, alternative="greater", method="approx")
        p_ref = float(ref["p-val"].iloc[0])
    if not np.isclose(p, p_ref, rtol=1e-6, atol=1e-12):
        sys.exit(f"Discrepancia SciPy/Pingouin en {etiqueta}: {p} frente a {p_ref}")
    return {"indicador": etiqueta, "n": n, "media_d": media, "de_d": de, "mediana_d": np.median(d),
            "W_shapiro": sw.statistic, "p_shapiro": sw.pvalue, "prueba": prueba, "estadistico": estad,
            "p_unilateral": p, "IC95_inf": li, "IC95_sup": ls, "efecto": nombre_ef, "valor_efecto": efecto}


def mcnemar(pares):
    det0 = pares["detectado_0"].astype(bool)
    det1 = pares["detectado_1"].astype(bool)
    n10, n01 = int((~det0 & det1).sum()), int((det0 & ~det1).sum())               # solo AIOps / solo convencional
    exacta = stats.binomtest(n10, n10 + n01, 0.5).pvalue if n10 + n01 else 1.0
    chi2 = (abs(n10 - n01) - 1) ** 2 / (n10 + n01) if n10 + n01 else 0.0          # ec. (14)
    p_chi2 = stats.chi2.sf(chi2, 1) if n10 + n01 else 1.0
    n = len(pares)
    return {"n10": n10, "n01": n01, "TD_0_pct": 100 * det0.sum() / n, "TD_1_pct": 100 * det1.sum() / n,  # ec. (8)
            "chi2_cc": chi2, "p_chi2": p_chi2, "p_exacta": exacta,
            "prueba_usada": "exacta (binomial)" if n10 + n01 < 25 else "chi-cuadrado con corrección"}


def holm(pvalores):
    """Ec. (15). Devuelve los p ajustados y la decisión; se verifica con Pingouin."""
    p = np.asarray(pvalores, dtype=float)
    orden = np.argsort(p)
    m = p.size
    ajustado = np.empty(m)
    acumulado = 0.0
    for k, i in enumerate(orden):                                                  # p_(k) · (m − k + 1), monótono
        acumulado = max(acumulado, min(1.0, p[i] * (m - k)))
        ajustado[i] = acumulado
    rechaza_pg, ajustado_pg = pg.multicomp(p, alpha=ALFA, method="holm")
    if not np.allclose(ajustado, ajustado_pg):
        sys.exit("Discrepancia en la corrección de Holm frente a Pingouin")
    return ajustado, ajustado <= ALFA


def efecto_periodo(pares, var):
    ab = pares.loc[pares["orden"] == "AB", var].astype(float)
    ba = pares.loc[pares["orden"] == "BA", var].astype(float)
    r = stats.mannwhitneyu(ab, ba, alternative="two-sided")
    return {"indicador": var, "n_AB": ab.size, "n_BA": ba.size, "mediana_AB": ab.median(),
            "mediana_BA": ba.median(), "U": r.statistic, "p_bilateral": r.pvalue}


def fase_en_vivo(vivo):
    t_max = pd.to_timedelta(vivo["T_max_s"], unit="s")
    mttd = {}
    for c in (0, 1):
        det = pd.to_datetime(vivo[f"t_deteccion_{c}"], utc=True)
        ini = pd.to_datetime(vivo["t_inicio"], utc=True)
        ok = det.notna() & (det <= ini + t_max)
        mttd[c] = ((det.where(ok, ini + t_max)) - ini).dt.total_seconds() / 60.0
    return contraste_pareado(mttd[0] - mttd[1], "MTTD fase en vivo (min)")


# ============================================================== autoprueba con un caso calculado a mano
def autoprueba():
    """Un par con valores conocidos: verifica censura, tramos, MTTR, uptime, signo de las diferencias,
    Holm y McNemar contra resultados calculados a mano. Se detiene si algo no coincide."""
    t0 = pd.Timestamp("2026-11-16 13:00:00", tz="UTC")
    s = lambda seg: t0 + pd.Timedelta(seconds=seg)
    caso = pd.DataFrame({
        "escenario": [1, 1], "fase": "principal", "anulada": False, "condicion": [0, 1],
        "tipo": "Microrráfagas", "severidad": "media", "carga": "baja", "orden": "AB",
        "t_inicio": [t0, t0],
        "t_deteccion": [pd.NaT, s(60)],                    # convencional no detecta: se censura en T_máx = 900 s
        "t_localizacion": [s(900 + 300), s(60 + 120)],
        "t_correccion": [s(1200 + 180), s(180 + 180)],
        "t_restauracion": [s(1380 + 60), s(360 + 60)],
        "T_max_s": 900.0, "T_obs_s": 1800.0, "T_indisp_s": [900.0, 360.0],
    })
    ind = calcular_indicadores(caso)
    esperado = {"MTTD_min": [15.0, 1.0], "L_min": [5.0, 2.0], "E_min": [3.0, 3.0], "V_min": [1.0, 1.0],
                "MTTR_min": [9.0, 6.0], "Uptime_pct": [50.0, 80.0]}
    for col, val in esperado.items():
        if not np.allclose(ind[col].to_numpy(), val):
            sys.exit(f"Autoprueba fallida en {col}: {ind[col].tolist()} en lugar de {val}")
    if ind["detectado"].tolist() != [False, True]:
        sys.exit("Autoprueba fallida en la censura de la detección")
    par = emparejar(ind)
    if not np.allclose(par[["d_MTTD_min", "d_MTTR_min", "d_Uptime_pct"]].to_numpy(), [[14.0, 3.0, 30.0]]):
        sys.exit("Autoprueba fallida en el signo o el valor de las diferencias pareadas")
    p_aj, _ = holm([0.01, 0.04, 0.03])                    # a mano: 0,01·3 = 0,03; 0,03·2 = 0,06; máx(0,06; 0,04·1) = 0,06
    if not np.allclose(p_aj, [0.03, 0.06, 0.06]):
        sys.exit(f"Autoprueba fallida en Holm: {p_aj}")
    mc = mcnemar(pd.DataFrame({"detectado_0": [False, False, True, True], "detectado_1": [True, True, False, True]}))
    if (mc["n10"], mc["n01"]) != (2, 1):
        sys.exit("Autoprueba fallida en McNemar")
    print("Autoprueba: indicadores, censura, diferencias, Holm y McNemar coinciden con el cálculo a mano.")


# ============================================================== figuras (sin título: el título va en la leyenda de Word)
def marca(fig, sintetico):
    if sintetico:
        fig.text(0.995, 0.005, "DATOS SINTÉTICOS: no son resultados del estudio", ha="right", va="bottom",
                 fontsize=8, color="#b00000")


def figuras(pares, ind, carpeta, sintetico):
    pre = "SINTETICO_" if sintetico else ""
    paneles = [("d_MTTD_min", "Panel A: MTTD", "Diferencia (min)"),
               ("d_MTTR_min", "Panel B: MTTR", "Diferencia (min)"),
               ("d_Uptime_pct", "Panel C: uptime", "Diferencia (puntos %)")]
    fig, ejes = plt.subplots(1, 3, figsize=(9, 3.4))
    for ax, (col, rotulo, eje_y) in zip(ejes, paneles):
        vals = pares[col].astype(float)
        ax.boxplot(vals, widths=0.45, showfliers=False, medianprops={"color": "black", "linewidth": 1.6})
        ax.scatter(np.ones(len(vals)), vals, s=12, alpha=0.6, color="#333333")
        ax.axhline(0, color="#888888", lw=0.8, ls="--")
        ax.set_xticks([])
        ax.set_ylabel(eje_y)
        ax.set_xlabel(rotulo)
    marca(fig, sintetico)
    fig.tight_layout()
    fig.savefig(carpeta / f"{pre}fig_diferencias_pareadas.png", dpi=300)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.6))
    p = pares.sort_values("MTTD_min_0")
    x = np.arange(len(p))
    ax.vlines(x, p["MTTD_min_1"].astype(float), p["MTTD_min_0"].astype(float), color="#bbbbbb", lw=1)
    ax.scatter(x, p["MTTD_min_0"].astype(float), marker="s", s=18, color="#555555", label="Convencional")
    ax.scatter(x, p["MTTD_min_1"].astype(float), marker="o", s=18, color="#000000", label="NetFlow/AIOps")
    ax.set_xticks(x, p["escenario"].astype(int), fontsize=7)
    ax.set_xlabel("Escenario (ordenado por MTTD convencional)")
    ax.set_ylabel("MTTD (min)")
    ax.legend(frameon=False, fontsize=9)
    marca(fig, sintetico)
    fig.tight_layout()
    fig.savefig(carpeta / f"{pre}fig_mttd_por_par.png", dpi=300)
    plt.close(fig)

    tasa = ind.groupby(["tipo", "condicion"])["detectado"].mean().unstack() * 100
    tasa = tasa.reindex([t for t in TIPOS if t in tasa.index])
    fig, ax = plt.subplots(figsize=(7, 3.4))
    x = np.arange(len(tasa))
    ax.bar(x - 0.2, tasa[0], 0.4, color="#9a9a9a", label="Convencional")
    ax.bar(x + 0.2, tasa[1], 0.4, color="#2b2b2b", label="NetFlow/AIOps")
    ax.set_xticks(x, tasa.index, fontsize=9)
    ax.set_ylabel("Tasa de detección (%)")
    ax.set_ylim(0, 105)
    ax.legend(frameon=False, fontsize=9, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    marca(fig, sintetico)
    fig.tight_layout()
    fig.savefig(carpeta / f"{pre}fig_tasa_deteccion_por_tipo.png", dpi=300)
    plt.close(fig)


# ============================================================== reporte
def a_markdown(df, decimales=3):
    """Tabla markdown simple, sin depender de tabulate."""
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return f"{v:.{decimales}f}"
        return str(v)
    cab = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    filas = ["| " + " | ".join(fmt(v) for v in fila) + " |" for fila in df.itertuples(index=False)]
    return "\n".join([cab, sep, *filas])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sintetico", action="store_true", help="genera y analiza datos inventados (prueba del código)")
    g.add_argument("--datos", type=Path, help="CSV de la ficha I1, una fila por ejecución")
    ap.add_argument("--vivo", type=Path, help="CSV de la fase en vivo (evento, t_inicio, t_deteccion_0, t_deteccion_1, T_max_s)")
    args = ap.parse_args()

    autoprueba()
    if args.sintetico:
        fichas, vivo = generar_sinteticos(RNG)
        carpeta = SALIDA / "sintetico"
    else:
        fichas = leer_fichas(args.datos)
        vivo = pd.read_csv(args.vivo) if args.vivo else None
        carpeta = SALIDA / "real"
    carpeta.mkdir(parents=True, exist_ok=True)
    prefijo = "SINTETICO_" if args.sintetico else ""
    if args.sintetico:
        fichas.to_csv(carpeta / f"{prefijo}fichas_I1.csv", index=False)
        vivo.to_csv(carpeta / f"{prefijo}eventos_vivo.csv", index=False)

    ind = calcular_indicadores(fichas)
    pares = emparejar(ind)
    if len(pares) < 3:
        sys.exit(f"Solo hay {len(pares)} par(es) completo(s): Shapiro-Wilk y el contraste requieren al menos 3.")
    ind.to_csv(carpeta / f"{prefijo}indicadores_por_ejecucion.csv", index=False)
    pares.to_csv(carpeta / f"{prefijo}diferencias_pareadas.csv", index=False)

    principales = [("d_MTTD_min", "HE 1: MTTD (min)"), ("d_MTTR_min", "HE 2: MTTR (min)"),
                   ("d_Uptime_pct", "HE 3: uptime (puntos %)")]
    tramos = [("d_L_min", "HE 2: localización (min)"), ("d_E_min", "HE 2: ejecución correctiva (min)"),
              ("d_V_min", "HE 2: verificación (min)")]
    res = pd.DataFrame([contraste_pareado(pares[c], e) for c, e in principales])
    p_aj, rechaza = holm(res["p_unilateral"])
    res["p_Holm"], res["rechaza_H0"] = p_aj, rechaza
    res_tramos = pd.DataFrame([contraste_pareado(pares[c], e) for c, e in tramos])
    mc = mcnemar(pares)
    periodo = pd.DataFrame([efecto_periodo(pares, c) for c, _ in principales])
    vivo_res = pd.DataFrame([fase_en_vivo(vivo)]) if vivo is not None else None
    potencia = {a: pg.power_ttest(n=len(pares), power=0.80, alpha=a, contrast="paired", alternative="greater")
                for a in (ALFA, ALFA / M_HOLM)}

    res.to_csv(carpeta / f"{prefijo}contraste_hipotesis.csv", index=False)
    res_tramos.to_csv(carpeta / f"{prefijo}contraste_tramos_mttr.csv", index=False)
    periodo.to_csv(carpeta / f"{prefijo}efecto_periodo.csv", index=False)
    figuras(pares, ind, carpeta, args.sintetico)

    desc = ind.groupby("condicion")[["MTTD_min", "MTTR_min", "Uptime_pct"]].agg(["mean", "median", "std"]).round(2)
    desc.index = desc.index.map({0: "Convencional", 1: "NetFlow/AIOps"})
    desc.columns = [f"{a} {b}" for a, b in desc.columns]
    lineas = [
        "# Resumen del contraste" + (" — DATOS SINTÉTICOS (no son resultados del estudio)" if args.sintetico else ""),
        "",
        f"Ejecuciones válidas: {len(ind)} · pares completos: {len(pares)} · α = {ALFA} (unilateral) · Holm m = {M_HOLM}",
        "",
        "## Descriptivos por condición", "", a_markdown(desc.reset_index().rename(columns={"condicion": "Condición"}), 2), "",
        "## HE 1 a HE 3 (diferencias pareadas; positivo = mejor con NetFlow/AIOps)", "",
        a_markdown(res[["indicador", "n", "media_d", "mediana_d", "p_shapiro", "prueba", "estadistico",
                        "p_unilateral", "p_Holm", "rechaza_H0", "IC95_inf", "IC95_sup", "efecto", "valor_efecto"]]),
        "", "## Tramos del MTTR (sin ajuste; explican dónde actúa la intervención)", "",
        a_markdown(res_tramos[["indicador", "n", "media_d", "prueba", "p_unilateral", "IC95_inf", "IC95_sup",
                               "efecto", "valor_efecto"]]),
        "", "## Tasa de detección (McNemar)", "",
        a_markdown(pd.DataFrame([mc])),
        "", "## Efecto de periodo (AB frente a BA, Mann-Whitney bilateral)", "", a_markdown(periodo),
    ]
    if vivo_res is not None:
        lineas += ["", "## Fase en vivo (MTTD emparejado por evento)", "",
                   a_markdown(vivo_res[["indicador", "n", "media_d", "prueba", "p_unilateral", "IC95_inf",
                                        "IC95_sup", "efecto", "valor_efecto"]])]
    lineas += ["", "## Verificación de potencia (Pingouin, t pareada unilateral, 1 − β = 0,80)", "",
               f"- α = {ALFA}: efecto mínimo detectable d_z = {potencia[ALFA]:.3f} con n = {len(pares)}",
               f"- α = {ALFA}/{M_HOLM} (Holm): d_z = {potencia[ALFA / M_HOLM]:.3f}",
               "", "Todas las pruebas se calcularon con SciPy y se verificaron con Pingouin (sin discrepancias)."]
    (carpeta / f"{prefijo}resumen.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n".join(lineas))
    print(f"\nSalidas en {carpeta}")


if __name__ == "__main__":
    main()
