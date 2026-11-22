"""絵具パレットの分光データを作り、Sources/PaletteData.swift を書き出す。

考え方:
  1. 各絵具の「よく見るマスストーン色」(16 進) を目標 Lab にする。
  2. 平滑な 5 基底（定数 + 4 つのガウス）で分光反射率を表し、
     その反射率から CIE 1931 2度視野 + D65 (10nm, 380-730nm) で
     XYZ -> Lab を計算して目標 Lab に合うよう Nelder-Mead で当てはめる。
  3. 当てはめた反射率・Lab・散乱係数を Swift に埋め込む。

散乱係数 S は 2定数 Kubelka-Munk のための値で、チタニウムホワイトを 1.0 とし、
隠ぺい力（不透明な顔料ほど大きい）を目安に与えた。吸収 K は
マスストーンの反射率から K = S * (K/S) として求まる。
分光反射率は各顔料の代表的なマスストーン色からの近似値であり、実測値ではない。
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

import colormath as cm

HERE = Path(__file__).resolve().parent
DATA = HERE / "spectral-data"
ROOT = HERE.parent

BANDS = list(range(380, 731, 10))
CENTER = np.array(BANDS, dtype=float)


def load_cie():
    cmf, spd = [], []
    with (DATA / "cmf_1931_2deg.csv").open() as fh:
        for row in csv.DictReader(fh):
            cmf.append((float(row["x_bar"]), float(row["y_bar"]), float(row["z_bar"])))
    with (DATA / "d65.csv").open() as fh:
        for row in csv.DictReader(fh):
            spd.append(float(row["spd"]))
    k = 100.0 / sum(s * c[1] for s, c in zip(spd, cmf))
    return cmf, spd, k


CMF, SPD, K = load_cie()


def reflectance_to_lab(refl):
    # spectral_to_xyz は Y=100 基準なので、Lab 用に 0-1 に戻す
    xyz = tuple(v / 100.0 for v in cm.spectral_to_xyz(refl, CMF, SPD, K))
    return cm.xyz_to_lab(xyz)


# --- 平滑基底 --------------------------------------------------------------

def basis_matrix():
    cols = [np.ones_like(CENTER)]
    for mu, sigma in ((450.0, 55.0), (510.0, 45.0), (575.0, 45.0), (640.0, 58.0)):
        cols.append(np.exp(-(((CENTER - mu) / sigma) ** 2)))
    return np.stack(cols, axis=1)  # (36, 5)


BASIS = basis_matrix()
R_MIN, R_MAX = 0.020, 0.975


def curve_from_params(c):
    r = BASIS @ np.asarray(c, dtype=float)
    return np.clip(r, R_MIN, R_MAX)


def loss(c, target_lab):
    refl = curve_from_params(c)
    de = cm.delta_e_2000(reflectance_to_lab(refl), target_lab)
    penalty = 0.0008 * float(np.sum(np.asarray(c[1:]) ** 2))
    return de * de + penalty


def nelder_mead(f, x0, step=0.18, iters=1500, tol=1e-9):
    n = len(x0)
    simplex = [np.array(x0, dtype=float)]
    for i in range(n):
        p = np.array(x0, dtype=float)
        p[i] += step
        simplex.append(p)
    values = [f(p) for p in simplex]

    for _ in range(iters):
        order = np.argsort(values)
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) < tol:
            break
        centroid = np.mean(simplex[:-1], axis=0)
        worst = simplex[-1]
        xr = centroid + (centroid - worst)
        fr = f(xr)
        if fr < values[0]:
            xe = centroid + 2.0 * (centroid - worst)
            fe = f(xe)
            if fe < fr:
                simplex[-1], values[-1] = xe, fe
            else:
                simplex[-1], values[-1] = xr, fr
        elif fr < values[-2]:
            simplex[-1], values[-1] = xr, fr
        else:
            xc = centroid + 0.5 * (worst - centroid)
            fc = f(xc)
            if fc < values[-1]:
                simplex[-1], values[-1] = xc, fc
            else:
                best = simplex[0]
                simplex = [best] + [best + 0.5 * (p - best) for p in simplex[1:]]
                values = [values[0]] + [f(p) for p in simplex[1:]]
    idx = int(np.argmin(values))
    return simplex[idx], values[idx]


def fit_pigment(hex_color):
    target = cm.hex_to_lab(hex_color)
    starts = [
        np.array([0.35, 0.0, 0.0, 0.0, 0.0]),
        np.array([0.55, -0.2, 0.1, 0.1, -0.2]),
        np.array([0.20, 0.35, -0.10, -0.10, 0.30]),
        np.array([0.80, -0.30, -0.10, -0.10, -0.20]),
        np.array([0.08, 0.05, 0.10, 0.05, 0.10]),
    ]
    best_c, best_v = None, float("inf")
    for s in starts:
        c, v = nelder_mead(lambda p: loss(p, target), s)
        if v < best_v:
            best_c, best_v = c, v
    refl = curve_from_params(best_c)
    return refl, reflectance_to_lab(refl), target


# --- 絵具の定義 ------------------------------------------------------------
# (名前, 顔料, 目標色, 散乱係数 S)

SCATTER = {
    "PW6": 1.00,
    "PY3": 0.30,
    "PY35": 0.45,
    "PY43": 0.40,
    "PO20": 0.45,
    "PR108": 0.45,
    "PR122": 0.15,
    "PR83": 0.06,
    "PBr7": 0.30,
    "PB29": 0.05,
    "PB28": 0.12,
    "PB35": 0.35,
    "PB27": 0.03,
    "PG18": 0.10,
    "PG8": 0.10,
    "PBk9": 0.10,
    "PBk6": 0.12,
}

OIL = [
    ("チタニウムホワイト", "PW6", "#F8F6EF"),
    ("レモンイエロー", "PY3", "#F6E24F"),
    ("カドミウムイエロー", "PY35", "#F3C126"),
    ("イエローオーカー", "PY43", "#C99A4C"),
    ("カドミウムオレンジ", "PO20", "#E1732A"),
    ("カドミウムレッド", "PR108", "#CE3327"),
    ("キナクリドンレッド", "PR122", "#A62B3C"),
    ("アリザリンクリムゾン", "PR83", "#7E2430"),
    ("ローシエナ", "PBr7", "#B0743C"),
    ("バーントシエナ", "PBr7", "#8B4A2B"),
    ("バーントアンバー", "PBr7", "#5E3620"),
    ("ウルトラマリン", "PB29", "#2C3A8E"),
    ("コバルトブルー", "PB28", "#2F68AE"),
    ("セルリアンブルー", "PB35", "#4F9CBE"),
    ("プルシアンブルー", "PB27", "#1C2E45"),
    ("ビリジアン", "PG18", "#2A5F51"),
    ("サップグリーン", "PG8", "#43592B"),
    ("アイボリーブラック", "PBk9", "#2B2724"),
]

WATERCOLOR = [
    ("チタニウムホワイト", "PW6", "#F9F7F1"),
    ("レモンイエロー", "PY3", "#F8E75C"),
    ("カドミウムイエロー", "PY35", "#F6CC31"),
    ("イエローオーカー", "PY43", "#D4A44F"),
    ("カドミウムレッド", "PR108", "#D7402E"),
    ("キナクリドンレッド", "PR122", "#B62B44"),
    ("アリザリンクリムゾン", "PR83", "#95263A"),
    ("オペラ", "PR122", "#E04A78"),
    ("ローシエナ", "PBr7", "#BC7C42"),
    ("バーントシエナ", "PBr7", "#97502D"),
    ("バーントアンバー", "PBr7", "#6B3E23"),
    ("ウルトラマリン", "PB29", "#34429B"),
    ("コバルトブルー", "PB28", "#3572B8"),
    ("セルリアンブルー", "PB35", "#5CAACE"),
    ("プルシアンブルー", "PB27", "#213750"),
    ("ビリジアン", "PG18", "#2C7061"),
    ("サップグリーン", "PG8", "#476230"),
    ("ペインズグレー", "PBk6", "#4A5661"),
]


def swift_paint(index, item, refl, lab):
    name, pigment, _hex = item
    values = ", ".join(f"{v:.4f}" for v in refl)
    return (
        f'        Paint(id: {index}, name: "{name}", pigment: "{pigment}", scatter: {SCATTER[pigment]:.2f},\n'
        f'              lab: LabColor(l: {lab[0]:.2f}, a: {lab[1]:.2f}, b: {lab[2]:.2f}),\n'
        f'              reflectance: [{values}]),'
    )


def build(items, label):
    rows, report = [], []
    for i, item in enumerate(items):
        refl, lab, target = fit_pigment(item[2])
        de = cm.delta_e_2000(lab, target)
        report.append((label, item[0], de, lab, item[2]))
        rows.append(swift_paint(i, item, refl, lab))
    return rows, report


def main():
    oil_rows, oil_report = build(OIL, "oil")
    wc_rows, wc_report = build(WATERCOLOR, "watercolor")

    print(f"{'palette':10s} {'name':22s} {'ΔE':>6s}  target   fitted Lab")
    for label, name, de, lab, hx in oil_report + wc_report:
        print(f"{label:10s} {name:22s} {de:6.2f}  {hx}  "
              f"({lab[0]:.1f}, {lab[1]:.1f}, {lab[2]:.1f})")
    worst = max(r[2] for r in oil_report + wc_report)
    print(f"max ΔE(target vs fitted) = {worst:.2f}")

    header = (
        "// このファイルは scripts/generate_palette.py が生成します。手で編集しないこと。\n"
        "// 分光反射率は 380-730nm / 10nm の 36 バンド。\n"
        "// 各絵具の代表的なマスストーン色（L*a*b*）に合うよう平滑な反射率を当てはめた近似値。\n"
        "// scatter は 2定数 Kubelka-Munk 用の散乱係数（チタニウムホワイト = 1.0）。\n\n"
        "import Foundation\n\n"
        "enum PaletteData {\n"
    )
    body = []
    body.append("    static let oil: [Paint] = [")
    body.extend(oil_rows)
    body.append("    ]\n")
    body.append("    static let watercolor: [Paint] = [")
    body.extend(wc_rows)
    body.append("    ]\n")
    body.append("    static let bandCount = 36")
    body.append("}")

    (ROOT / "Sources" / "PaletteData.swift").write_text(header + "\n".join(body) + "\n")
    print("wrote Sources/PaletteData.swift")


if __name__ == "__main__":
    main()
