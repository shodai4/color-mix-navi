"""絵具パレットの分光データを作り、Sources/PaletteData.swift を書き出す。

パレットはホルベイン（HOLBEIN）の実在色 18 色ずつ。

データの出どころ（2026-11-22 確認）:
  - 色名・顔料記号: ホルベイン公式 Technical Data Sheet
      HOC（油絵具） https://www.holbeinartistmaterials.com/wp-content/uploads/2020/12/HOCTDS.pdf
      HWC（透明水彩） https://www.holbeinartistmaterials.com/wp-content/uploads/2020/12/HWCTDS.pdf
  - 色: ホルベイン オンラインショップの公式カラーチャート（デジタルデータ）
      各色の商品画像（原色の見本）の中央値を sRGB として採取。
      公式サイトの注記どおり、画面用のデジタルデータであり実際の絵具の色とは差がある。
  - 油絵具の明度: 同じ TDS のマンセル値（例: カドミウムレッド 6R 4.6/14.8）から
      ASTM D1535 の V-Y 多項式で Y を出し、L* にした値。写真の陰影で暗く写る分を補う。
      色相・彩度はカラーチャートの値をそのまま使う。
  - 透明水彩: TDS にマンセル値がないため、カラーチャートの値をそのまま使う。

考え方:
  1. 各絵具の目標 Lab を決める（上記）。
  2. 平滑な基底（定数 + ガウス）で分光反射率を表し、
     CIE 1931 2度視野 + D65 (10nm, 380-730nm) で XYZ -> Lab を計算して
     目標 Lab に合うよう Nelder-Mead で当てはめる。
  3. 当てはめた反射率・Lab・散乱係数を Swift に埋め込む。

散乱係数 S は 2定数 Kubelka-Munk のための値で、チタニウムホワイトを 1.0 とし、
隠ぺい力（TDS の Opacity Rating: Opaque / Semi-Opaque / Semi-Transparent / Transparent）
を目安に与えた。吸収 K はマスストーンの反射率から K = S * (K/S) として求まる。
分光反射率は各絵具のマスストーン色からの近似値であり、実測の分光データではない。
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
    for mu, sigma in ((420.0, 30.0), (455.0, 40.0), (500.0, 40.0), (535.0, 35.0),
                      (580.0, 40.0), (625.0, 45.0), (670.0, 45.0)):
        cols.append(np.exp(-(((CENTER - mu) / sigma) ** 2)))
    return np.stack(cols, axis=1)  # (36, 8)


BASIS = basis_matrix()
R_MIN, R_MAX = 0.004, 0.975


def curve_from_params(c):
    r = BASIS @ np.asarray(c, dtype=float)
    return np.clip(r, R_MIN, R_MAX)


def loss(c, target_lab):
    refl = curve_from_params(c)
    de = cm.delta_e_2000(reflectance_to_lab(refl), target_lab)
    penalty = 0.0008 * float(np.sum(np.asarray(c[1:]) ** 2))
    return de * de + penalty


def nelder_mead(f, x0, step=0.18, iters=2000, tol=1e-9):
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


def fit_pigment(target_lab):
    starts = [
        np.array([0.35] + [0.0] * 7),
        np.array([0.55, -0.3, 0.1, 0.1, 0.1, 0.1, -0.2, -0.2]),
        np.array([0.20, 0.0, 0.35, -0.10, -0.10, 0.10, 0.30, 0.20]),
        np.array([0.80, -0.30, -0.10, -0.10, -0.10, -0.10, -0.20, -0.20]),
        np.array([0.08, 0.05, 0.05, 0.10, 0.10, 0.05, 0.10, 0.10]),
        np.array([0.45, 0.0, 0.4, 0.0, -0.2, -0.2, 0.2, 0.2]),
    ]
    best_c, best_v = None, float("inf")
    for s in starts:
        c, v = nelder_mead(lambda p: loss(p, target_lab), s)
        if v < best_v:
            best_c, best_v = c, v
    refl = curve_from_params(best_c)
    return refl, reflectance_to_lab(refl), target_lab


# --- 絵具の定義 ------------------------------------------------------------
# (名前, 顔料, 目標 Lab, 散乱係数 S)
#
# 油絵具の L は TDS のマンセル値から、a/b はカラーチャートの原色から。
# 透明水彩はカラーチャートの原色から（TDS にマンセル値がないため）。

OIL = [
    ("パーマネントホワイトSF", "PW6", (96.9, 0.0, 1.5), 1.00),          # H415 W 9.6/0.2
    ("ジンクホワイトSF", "PW4", (96.0, 0.0, 1.0), 0.85),                # H405 W 9.5/0.2
    ("レモンイエロー", "PY81+PW6", (93.0, -17.8, 89.4), 0.35),          # H237 0.5GY 9.2/11.6
    ("カドミウムイエロー", "PY35+PO20", (81.3, 15.9, 77.2), 0.45),      # H252 2Y 8.0/13.3
    ("イエローオーカー", "PY42", (58.7, 8.7, 48.6), 0.40),              # H240 10.5YR 5.7/6.8
    ("カドミウムオレンジ", "PO20", (64.7, 63.0, 66.5), 0.45),           # H257 2YR 6.3/14.0
    ("バーミリオンヒュー", "PY139+PO73+PR254", (52.6, 71.0, 57.2), 0.30),  # H218 7R 5.1/14.7
    ("カドミウムレッド", "PR108", (47.5, 67.0, 50.5), 0.45),            # H207 6R 4.6/14.8
    ("クリムソンレーキ", "PR177+PR254", (24.6, 36.9, 21.0), 0.10),      # H201 3R 2.4/4.3
    ("アリザリンクリムソン", "PR83", (24.6, 39.8, 23.6), 0.06),         # H223 2.5R 2.4/6.5
    ("ローシェンナ", "PY42+PBr7", (43.3, 15.0, 39.1), 0.30),            # H343 6.5YR 4.2/4.4
    ("バーントシェンナ", "PBr7", (32.9, 16.6, 15.1), 0.30),             # H345 6.8R 3.2/3.1
    ("バーントアンバー", "PBr7", (26.6, 4.3, 5.3), 0.30),               # H344 7.5R 2.6/0.8
    ("ウルトラマリンディープ", "PB29", (21.5, 36.9, -55.9), 0.05),       # H308 1P 2.1/6.5
    ("コバルトブルーヒュー", "PB15+PB29+PW6", (25.6, 25.7, -48.4), 0.12),  # H304 8.5PB 2.5/11.0
    ("セルリアンブルー", "PB35", (40.2, 9.5, -42.1), 0.35),             # H305 9PB 3.9/10.4
    ("ビリジャンヒュー", "PG7", (23.6, -6.8, -5.3), 0.10),              # H271 1.5B 2.3/1.7
    ("アイボリブラック", "PBk7+PBk9", (21.5, 0.5, -0.4), 0.10),         # H354 N 2.1/0.1
]

WATERCOLOR = [
    ("チタニウムホワイト", "PW6", (97.9, 0.0, -1.1), 1.00),
    ("レモンイエロー", "PY3+PW6", (94.8, -19.1, 86.5), 0.35),
    ("カドミウムイエローペール", "PY35", (92.4, -13.1, 85.1), 0.45),
    ("イエローオーカー", "PY42", (55.5, 10.7, 56.0), 0.35),
    ("カドミウムレッドライト", "PO20+PR108", (50.2, 68.1, 59.7), 0.45),
    ("バーミリオンヒュー", "PO73+PR254+PY110", (58.4, 61.1, 63.3), 0.30),
    ("クリムソンレーキ", "PR177+PR122+PV19", (30.1, 44.8, 22.2), 0.08),
    ("オペラ", "BV10+PR122", (58.7, 76.0, -4.1), 0.10),
    ("ローシェンナ", "PY42+PBr7", (52.8, 11.4, 49.7), 0.30),
    ("バーントシェンナ", "PBr7", (33.9, 25.1, 32.6), 0.30),
    ("バーントアンバー", "PBr7", (38.4, 20.9, 30.1), 0.30),
    ("ウルトラマリンディープ", "PB29", (25.4, 41.9, -69.5), 0.04),
    ("コバルトブルー", "PB28", (31.1, 43.4, -74.8), 0.10),
    ("セルリアンブルー", "PB35", (50.8, 4.0, -52.0), 0.30),
    ("ビリジャンヒュー", "PG7", (9.8, -1.0, -9.8), 0.08),
    ("サップグリーン", "PY150+PG7+PR122", (14.4, -13.6, 11.3), 0.10),
    ("ペインズグレイ", "PBk6+PB15+PR122", (21.3, -4.6, 2.0), 0.12),
    ("アイボリブラック", "PBk9", (11.1, -3.6, 2.6), 0.10),
]


def swift_paint(index, item, refl, lab):
    name, pigment, _target, scatter = item
    values = ", ".join(f"{v:.4f}" for v in refl)
    return (
        f'        Paint(id: {index}, name: "{name}", pigment: "{pigment}", scatter: {scatter:.2f},\n'
        f'              lab: LabColor(l: {lab[0]:.2f}, a: {lab[1]:.2f}, b: {lab[2]:.2f}),\n'
        f'              reflectance: [{values}]),'
    )


def build(items, label):
    rows, report = [], []
    for i, item in enumerate(items):
        refl, lab, target = fit_pigment(item[2])
        de = cm.delta_e_2000(lab, target)
        report.append((label, item[0], de, lab, target))
        rows.append(swift_paint(i, item, refl, lab))
    return rows, report


def main():
    oil_rows, oil_report = build(OIL, "oil")
    wc_rows, wc_report = build(WATERCOLOR, "watercolor")

    print(f"{'palette':10s} {'name':22s} {'ΔE':>6s}  target Lab")
    for label, name, de, lab, target in oil_report + wc_report:
        print(f"{label:10s} {name:22s} {de:6.2f}  "
              f"({target[0]:.1f}, {target[1]:.1f}, {target[2]:.1f})  -> "
              f"({lab[0]:.1f}, {lab[1]:.1f}, {lab[2]:.1f})")
    worst = max(r[2] for r in oil_report + wc_report)
    print(f"max ΔE(target vs fitted) = {worst:.2f}")

    header = (
        "// このファイルは scripts/generate_palette.py が生成します。手で編集しないこと。\n"
        "// ホルベインの油絵具 18 色と透明水彩 18 色。色名と顔料記号は公式 TDS のとおり。\n"
        "// 分光反射率は 380-730nm / 10nm の 36 バンド。\n"
        "// 各絵具のマスストーン色（L*a*b*）に合うよう平滑な反射率を当てはめた近似値。\n"
        "// 油絵具の明度は TDS のマンセル値、色相・彩度は公式オンラインショップの\n"
        "// カラーチャート（デジタルデータ）。透明水彩はカラーチャートの原色から。\n"
        "// scatter は 2定数 Kubelka-Munk 用の散乱係数（パーマネントホワイト = 1.0）。\n\n"
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
