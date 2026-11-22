"""数値検証: 色変換・CIEDE2000・Kubelka-Munk・レシピ探索。

Swift 実装 (ColorScience.swift / MixSolver.swift) と同じ手順を Python で書き、
既知の基準値と突き合わせる。実行: python3 scripts/verify_color_math.py
"""

from __future__ import annotations

import csv
import math
import re
import time
from pathlib import Path

import numpy as np

import colormath as cm

HERE = Path(__file__).resolve().parent
DATA = HERE / "spectral-data"
ROOT = HERE.parent

failures: list[str] = []


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


# --- 分光データ ------------------------------------------------------------

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


def lab_from_reflectance(refl):
    xyz = tuple(v / 100.0 for v in cm.spectral_to_xyz(refl, CMF, SPD, K))
    return cm.xyz_to_lab(xyz)


# --- パレット読み込み（生成された Swift から） -----------------------------

def load_palette(swift_text, name):
    start = swift_text.index(f"static let {name}: [Paint] = [")
    end = swift_text.index("    ]", start)
    block = swift_text[start:end]
    paints = []
    for m in re.finditer(
        r'Paint\(id: (\d+), name: "([^"]+)", pigment: "([^"]+)", scatter: ([0-9.]+),\s*'
        r'lab: LabColor\(l: ([-0-9.]+), a: ([-0-9.]+), b: ([-0-9.]+)\),\s*'
        r'reflectance: \[([^\]]+)\]\)',
        block,
    ):
        paints.append({
            "id": int(m.group(1)),
            "name": m.group(2),
            "pigment": m.group(3),
            "scatter": float(m.group(4)),
            "lab": (float(m.group(5)), float(m.group(6)), float(m.group(7))),
            "refl": [float(v) for v in m.group(8).split(",")],
        })
    return paints


SWIFT = (ROOT / "Sources" / "PaletteData.swift").read_text()
OIL = load_palette(SWIFT, "oil")
WATERCOLOR = load_palette(SWIFT, "watercolor")

# --- 1. 色変換 -------------------------------------------------------------

def test_conversions():
    print("\n== 色変換 ==")
    lab_white = cm.srgb_to_lab((1.0, 1.0, 1.0))
    check("sRGB 白 -> Lab(100, 0, 0)", all(abs(a - b) < 1e-4 for a, b in zip(lab_white, (100, 0, 0))),
          f"{tuple(round(v, 6) for v in lab_white)}")

    for label, rgb, expect in [
        ("赤", (1, 0, 0), (53.24, 80.09, 67.20)),
        ("緑", (0, 1, 0), (87.73, -86.18, 83.18)),
        ("青", (0, 0, 1), (32.30, 79.19, -107.86)),
    ]:
        got = cm.srgb_to_lab(rgb)
        check(f"sRGB {label} -> Lab", all(abs(g - e) < 0.02 for g, e in zip(got, expect)),
              f"{tuple(round(v, 2) for v in got)} / 期待 {expect}")

    worst = 0.0
    for rgb in [(0.13, 0.54, 0.77), (0.95, 0.75, 0.2), (0.42, 0.2, 0.6), (0.02, 0.02, 0.05)]:
        back = cm.lab_to_srgb(cm.srgb_to_lab(rgb))
        worst = max(worst, max(abs(a - b) for a, b in zip(back, rgb)))
    check("sRGB -> Lab -> sRGB 往復", worst < 1e-6, f"max 誤差 {worst:.2e}")

    # 分光: 完全拡散反射 (R=1) は D65 白色
    white_lab = lab_from_reflectance([1.0] * 36)
    check("分光 R=1 -> Lab(100,0,0) ±0.1", abs(white_lab[0] - 100) < 0.1
          and math.hypot(white_lab[1], white_lab[2]) < 0.1,
          f"{tuple(round(v, 3) for v in white_lab)}")

    # Display P3 の赤 (1,0,0) は sRGB の赤より鮮やか
    xyz = cm.p3_to_xyz((1.0, 0.0, 0.0))
    lab = cm.xyz_to_lab(xyz)
    check("Display P3 赤 -> Lab が sRGB 赤より高彩度", math.hypot(lab[1], lab[2]) > math.hypot(80.09, 67.20),
          f"{tuple(round(v, 2) for v in lab)}")


# --- 2. CIEDE2000 ----------------------------------------------------------

def test_delta_e():
    print("\n== CIEDE2000 ==")
    rows = []
    for line in (DATA / "ciede2000-testdata.txt").read_text().splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) == 7:
            rows.append([float(p) for p in parts])
    worst = 0.0
    for r in rows:
        got = cm.delta_e_2000((r[0], r[1], r[2]), (r[3], r[4], r[5]))
        worst = max(worst, abs(got - r[6]))
    check(f"Sharma 2005 の {len(rows)} ペア", worst < 5e-4, f"最大誤差 {worst:.2e}")
    check("同一色の ΔE = 0", cm.delta_e_2000((50, 10, -20), (50, 10, -20)) == 0.0)


# --- 3. Kubelka-Munk -------------------------------------------------------

def mix_lab(paints, weights):
    refl = cm.mix_two_constant([p["refl"] for p in paints],
                               [p["scatter"] for p in paints], weights)
    return lab_from_reflectance(refl), refl


def test_kubelka_munk():
    print("\n== Kubelka-Munk（2定数） ==")
    white = next(p for p in OIL if p["pigment"] == "PW6")
    black = next(p for p in OIL if p["name"] == "アイボリブラック")
    red = next(p for p in OIL if p["name"] == "カドミウムレッド")
    yellow = next(p for p in OIL if p["name"] == "カドミウムイエロー")
    blue = next(p for p in OIL if p["name"] == "ウルトラマリンディープ")

    lab, _ = mix_lab([white], [1.0])
    check("単色 100% は元の色と一致", cm.delta_e_2000(lab, white["lab"]) < 0.01,
          f"ΔE {cm.delta_e_2000(lab, white['lab']):.3f}")

    lab, _ = mix_lab([white, black], [0.9, 0.1])
    print(f"    白90+黒10 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("白90+黒10 は明るいグレー", 70 < lab[0] < 95, f"L* {lab[0]:.1f}")

    lab, _ = mix_lab([white, black], [0.5, 0.5])
    print(f"    白50+黒50 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("白50+黒50 は中間のグレー", 40 < lab[0] < 70 and math.hypot(lab[1], lab[2]) < 6,
          f"L* {lab[0]:.1f}")

    linear_l = 0.5 * white["lab"][0] + 0.5 * black["lab"][0]
    check("白+黒50:50 は線形平均より暗い（減法混色の濁り）", lab[0] < linear_l,
          f"L* {lab[0]:.1f} vs 線形平均 {linear_l:.1f}")

    lab, _ = mix_lab([red, white], [0.3, 0.7])
    print(f"    赤30+白70 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("赤30+白70 は明るいピンク（L*55 以上・赤みを保つ）",
          lab[0] > 55 and lab[1] > 40, f"L* {lab[0]:.1f}, a* {lab[1]:.1f}")

    lab, _ = mix_lab([yellow, blue], [0.5, 0.5])
    print(f"    黄50+青50 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("黄+青 50:50 は緑（a*<0 かつ b*>0、紫にならない）",
          lab[1] < 0 and lab[2] > 0, f"Lab {tuple(round(v, 1) for v in lab)}")

    lab, _ = mix_lab([yellow, blue], [0.7, 0.3])
    print(f"    黄70+青30 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("黄70+青30 は黄緑（緑みがあり、黄より暗い）",
          lab[1] < 0 and lab[2] > 10 and lab[0] < 60, f"Lab {tuple(round(v, 1) for v in lab)}")


# --- 4. レシピ探索（Swift と同じアルゴリズム） -----------------------------

def mix_weights(n):
    """n 色の 10% 刻み配合（すべて 10% 以上）。"""
    if n == 1:
        yield [1.0]
        return
    if n == 2:
        for a in range(1, 10):
            yield [a / 10.0, 1.0 - a / 10.0]
        return
    for a in range(1, 9):
        for b in range(1, 10 - a):
            c = 10 - a - b
            if c >= 1:
                yield [a / 10.0, b / 10.0, c / 10.0]


def solve(target, paints, max_paints=3, limit=3):
    """Swift の MixSolver と同じ手順（総当たり + 10% 刻み）。"""
    best = []  # (dE, key, weights, lab)
    for n in range(1, max_paints + 1):
        for combo in combinations(list(range(len(paints))), n):
            for w in mix_weights(n):
                lab, _ = mix_lab([paints[i] for i in combo], w)
                de = cm.delta_e_2000(target, lab)
                if len(best) < 40:
                    best.append((de, combo, w, lab))
                    best.sort(key=lambda x: x[0])
                elif de < best[-1][0]:
                    best[-1] = (de, combo, w, lab)
                    best.sort(key=lambda x: x[0])
    out, seen = [], set()
    for de, key, w, lab in best:
        if key in seen:
            continue
        seen.add(key)
        out.append((de, [paints[i]["name"] for i in key], w, lab))
        if len(out) == limit:
            break
    return out


KS_CACHE: dict[int, np.ndarray] = {}


def ks_matrix(paints):
    """(K 行列, S ベクトル)。K = S * (K/S)。"""
    key = id(paints)
    if key not in KS_CACHE:
        k = np.array([[cm.reflectance_to_ks(v) * p["scatter"] for v in p["refl"]] for p in paints])
        sv = np.array([p["scatter"] for p in paints])
        KS_CACHE[key] = (k, sv)
    return KS_CACHE[key]


def mix_lab_np(ks, combo, weights):
    kmat, svec = ks
    w = np.asarray(weights, dtype=float)  # (nWeights, n)
    idx = list(combo)
    k = np.tensordot(w, kmat[idx], axes=(1, 0))  # (nWeights, 36)
    s = (w @ svec[idx])[:, None]
    ratio = k / np.maximum(s, 1e-9)
    r = 1.0 + ratio - np.sqrt(ratio * ratio + 2.0 * ratio)
    scale = np.array([s for s in SPD])[:, None] * r.T
    xyz = np.array(CMF).T @ scale  # (3, nWeights)
    labs = []
    for i in range(xyz.shape[1]):
        labs.append(cm.xyz_to_lab(tuple(float(v) * K / 100.0 for v in xyz[:, i])))
    return labs


def solve_fast(target, paints, max_paints=3, limit=3):
    """同じ探索を numpy で回す版（検証を現実的な時間で終えるため）。"""
    ks = ks_matrix(paints)
    best = []
    for n in range(1, max_paints + 1):
        for combo in combinations(list(range(len(paints))), n):
            weights = list(mix_weights(n))
            labs = mix_lab_np(ks, combo, weights)
            for w, lab in zip(weights, labs):
                de = cm.delta_e_2000(target, lab)
                if len(best) < 40:
                    best.append((de, combo, w, lab))
                    best.sort(key=lambda x: x[0])
                elif de < best[-1][0]:
                    best[-1] = (de, combo, w, lab)
                    best.sort(key=lambda x: x[0])
    out, seen = [], set()
    for de, key, w, lab in best:
        if key in seen:
            continue
        seen.add(key)
        out.append((de, [paints[i]["name"] for i in key], w, lab))
        if len(out) == limit:
            break
    return out


def combinations(pool, n):
    pool = list(pool)
    if n == 0:
        yield ()
        return
    for i in range(len(pool)):
        for rest in combinations(pool[i + 1:], n - 1):
            yield (pool[i], *rest)


def test_solver():
    print("\n== レシピ探索 ==")
    t0 = time.time()
    worst = 0.0
    for palette in (OIL, WATERCOLOR):
        for p in palette:
            res = solve_fast(p["lab"], palette, max_paints=3, limit=1)
            worst = max(worst, res[0][0])
    elapsed = time.time() - t0
    check(f"36 色すべて、目標=その絵具の色で ΔE<1 の配合が見つかる（{elapsed:.1f} 秒）",
          worst < 1.0, f"最悪 ΔE {worst:.3f}")

    # 純 Python の素直な実装（Swift と同じ手順）と一致するか
    t0 = time.time()
    ref = solve(OIL[5]["lab"], OIL, max_paints=2, limit=1)
    mirror_ms = (time.time() - t0) * 1000
    fast = solve_fast(OIL[5]["lab"], OIL, max_paints=2, limit=1)
    check("素直な実装と numpy 版の最良解が一致",
          ref[0][1] == fast[0][1] and abs(ref[0][0] - fast[0][0]) < 1e-9,
          f"{ref[0][1]} ΔE {ref[0][0]:.4f}")
    print(f"  素直な実装（1-2色探索）: {mirror_ms:.0f} ms")

    # 2 色の中間色
    yellow = next(p for p in OIL if p["name"] == "カドミウムイエロー")
    blue = next(p for p in OIL if p["name"] == "ウルトラマリンディープ")
    mid, _ = mix_lab([yellow, blue], [0.5, 0.5])
    res = solve_fast(mid, OIL, max_paints=3, limit=3)
    print(f"  黄+青の中間色 Lab {tuple(round(v, 1) for v in mid)} に対する上位3案:")
    for de, names, w, lab in res:
        print(f"    ΔE {de:5.2f}  " + ", ".join(f"{n} {int(round(x * 100))}%" for n, x in zip(names, w)))
    check("中間色の 1 位は ΔE<3", res[0][0] < 3.0, f"ΔE {res[0][0]:.3f}")

    n_evals = 18 + 153 * 9 + 816 * 36
    print(f"  1 回の全探索で評価する配合数: {n_evals:,}（1・2・3 色 / 10% 刻み）")




# --- 5. 表示矩形と画素座標 -------------------------------------------------

def fitted_rect(image, bounds):
    ib, bb = image, bounds
    scale = min(bb[0] / ib[0], bb[1] / ib[1])
    w, h = ib[0] * scale, ib[1] * scale
    return ((bb[0] - w) / 2, (bb[1] - h) / 2, w, h)


def pixel_point(point, rect, image):
    rx, ry, rw, rh = rect
    u = (point[0] - rx) / rw
    v = (point[1] - ry) / rh
    x = math.floor(u * image[0])
    y = math.floor(v * image[1])
    return (min(max(x, 0), image[0] - 1), min(max(y, 0), image[1] - 1))


def test_geometry():
    print("\n== 座標変換（.scaledToFit） ==")
    cases = [
        ((4000, 3000), (390, 500)),
        ((3000, 4000), (390, 500)),
        ((4000, 4000), (390, 500)),
        ((100, 100), (390, 500)),
    ]
    ok = True
    detail = []
    for image, bounds in cases:
        rect = fitted_rect(image, bounds)
        corners = [
            ((rect[0], rect[1]), (0, 0)),
            ((rect[0] + rect[2] - 0.01, rect[1] + rect[3] - 0.01), (image[0] - 1, image[1] - 1)),
            ((rect[0] + rect[2] / 2, rect[1] + rect[3] / 2), (image[0] // 2, image[1] // 2)),
        ]
        for point, expect in corners:
            got = pixel_point(point, rect, image)
            if got != expect:
                ok = False
                detail.append(f"{image}{point} -> {got} (expect {expect})")
    check("横・縦・正方形・小さい画像で、左上/右下/中央が正しい画素に当たる", ok,
          "; ".join(detail))
    rect = fitted_rect((4000, 3000), (390, 500))
    check("写真の外を触っても端の画素に丸まる",
          pixel_point((-20, -20), rect, (4000, 3000)) == (0, 0)
          and pixel_point((999, 999), rect, (4000, 3000)) == (3999, 2999))

# --- 6. データの健全性 -----------------------------------------------------

def test_palette():
    print("\n== パレット ==")
    check("油絵具は 18 色", len(OIL) == 18, str(len(OIL)))
    check("透明水彩は 18 色", len(WATERCOLOR) == 18, str(len(WATERCOLOR)))
    check("反射率はすべて 0-1 の範囲",
          all(0.0 <= v <= 1.0 for p in OIL + WATERCOLOR for v in p["refl"]))
    check("反射率は 36 バンド", all(len(p["refl"]) == 36 for p in OIL + WATERCOLOR))
    worst = 0.0
    for p in OIL + WATERCOLOR:
        worst = max(worst, cm.delta_e_2000(p["lab"], lab_from_reflectance(p["refl"])))
    check("埋め込んだ Lab は反射率から再計算した値と一致", worst < 0.03, f"最大 ΔE {worst:.3f}")
    check("名前の重複なし（パレット内）",
          len({p["name"] for p in OIL}) == len(OIL)
          and len({p["name"] for p in WATERCOLOR}) == len(WATERCOLOR))



# --- 7. 5 色限定の探索 -------------------------------------------------------

FIVE_NAMES = ["パーマネントホワイトSF", "カドミウムレッド", "カドミウムイエロー",
              "ウルトラマリンディープ", "アイボリブラック"]


def five_paints():
    return [p for p in OIL if p["name"] in FIVE_NAMES]


def test_five_color_solver():
    print("\n== 5 色限定の探索 ==")
    five = five_paints()
    check("5 色がそろっている", len(five) == 5, ", ".join(p["name"] for p in five))

    white = next(p for p in five if p["name"] == "パーマネントホワイトSF")
    red = next(p for p in five if p["name"] == "カドミウムレッド")
    blue = next(p for p in five if p["name"] == "ウルトラマリンディープ")

    targets = {
        "赤と白の混色": mix_lab([red, white], [0.5, 0.5])[0],
        "写真の空の青": cm.hex_to_lab("#6E9BC5"),
        "鮮やかな緑（範囲外）": cm.srgb_to_lab((0.0, 1.0, 0.0)),
        "5 色の外の色（黄緑）": cm.hex_to_lab("#7FA05A"),
    }

    names = {p["name"] for p in five}
    ok_subset = True
    for label, target in targets.items():
        limited = solve_fast(target, five, max_paints=3, limit=3)
        full = solve_fast(target, OIL, max_paints=3, limit=3)
        used = {n for recipe in limited for n in recipe[1]}
        inside = used <= names
        ok_subset = ok_subset and inside
        print(f"    {label}: 5 色の最良 ΔE {limited[0][0]:5.2f} / 18 色の最良 ΔE {full[0][0]:5.2f} "
              f"({', '.join(limited[0][1])})")
        check(f"{label}: 5 色以外が混ざらない", inside, str(used - names))
        check(f"{label}: 18 色のほうが同じか良い", full[0][0] <= limited[0][0] + 1e-9,
              f"{full[0][0]:.4f} vs {limited[0][0]:.4f}")

    # 5 色のうち 2 色を混ぜた色は、その 2 色（か、より近い組み合わせ）で再現できる
    mixed, _ = mix_lab([red, white], [0.4, 0.6])
    best = solve_fast(mixed, five, max_paints=3, limit=1)
    check("5 色どうしの混色は 5 色で ΔE<1", best[0][0] < 1.0, f"ΔE {best[0][0]:.3f}")


# --- 8. 3D LUT（写真全体の色域再現） ----------------------------------------

def gamut_samples(paints):
    """Swift の MixSolver.gamutSamples と同じ候補（1〜3 色・10% 刻み）。"""
    out = []
    n = len(paints)

    def add(indices, weights):
        refl = cm.mix_two_constant([paints[i]["refl"] for i in indices],
                                   [paints[i]["scatter"] for i in indices], weights)
        lab = lab_from_reflectance(refl)
        rgb = cm.lab_to_srgb(lab)
        out.append((lab, tuple(min(max(c, 0.0), 1.0) for c in rgb)))

    for i in range(n):
        add([i], [1.0])
    for i in range(n):
        for j in range(i + 1, n):
            for step in range(1, 10):
                f = step / 10.0
                add([i, j], [f, 1 - f])
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                for a in range(1, 9):
                    for b in range(1, 10 - a):
                        c = 10 - a - b
                        if c < 1:
                            continue
                        add([i, j, k], [a / 10.0, b / 10.0, c / 10.0])
    return out


def srgb_to_lab_np(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=float)
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    matrix = np.array(cm.SRGB_TO_XYZ)
    xyz = linear @ matrix.T
    scaled = xyz / np.array([cm.XN, cm.YN, cm.ZN])
    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(scaled > epsilon, np.cbrt(scaled), (kappa * scaled + 16) / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def delta_e_2000_np(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """lab1 (N,3) x lab2 (M,3) -> (N,M) の CIEDE2000。"""
    L1, a1, b1 = (lab1[:, 0][:, None], lab1[:, 1][:, None], lab1[:, 2][:, None])
    L2, a2, b2 = (lab2[:, 0][None, :], lab2[:, 1][None, :], lab2[:, 2][None, :])

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    c_bar = (C1 + C2) / 2
    g = 0.5 * (1 - np.sqrt(c_bar ** 7 / (c_bar ** 7 + 25.0 ** 7)))
    a1p = (1 + g) * a1
    a2p = (1 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360

    d_l = L2 - L1
    d_c = c2p - c1p
    dh = h2p - h1p
    d_hp = np.where(np.abs(dh) <= 180, dh, np.where(dh > 180, dh - 360, dh + 360))
    d_hp = np.where(c1p * c2p == 0, 0.0, d_hp)
    d_h = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(d_hp / 2))

    l_bar = (L1 + L2) / 2
    cp_bar = (c1p + c2p) / 2
    sum_h = h1p + h2p
    hp_bar = np.where(np.abs(h1p - h2p) <= 180, sum_h / 2,
                      np.where(sum_h < 360, (sum_h + 360) / 2, (sum_h - 360) / 2))
    hp_bar = np.where(c1p * c2p == 0, sum_h, hp_bar)

    t = (1 - 0.17 * np.cos(np.radians(hp_bar - 30))
         + 0.24 * np.cos(np.radians(2 * hp_bar))
         + 0.32 * np.cos(np.radians(3 * hp_bar + 6))
         - 0.20 * np.cos(np.radians(4 * hp_bar - 63)))
    d_theta = 30 * np.exp(-(((hp_bar - 275) / 25) ** 2))
    cp7 = cp_bar ** 7
    r_c = 2 * np.sqrt(cp7 / (cp7 + 25.0 ** 7))
    l_term = (l_bar - 50) ** 2
    s_l = 1 + 0.015 * l_term / np.sqrt(20 + l_term)
    s_c = 1 + 0.045 * cp_bar
    s_h = 1 + 0.015 * cp_bar * t
    r_t = -np.sin(np.radians(2 * d_theta)) * r_c

    term_l = d_l / s_l
    term_c = d_c / s_c
    term_h = d_h / s_h
    return np.sqrt(term_l ** 2 + term_c ** 2 + term_h ** 2 + r_t * term_c * term_h)


def build_lut(samples, size=33, chunk=1500):
    """Swift の PreviewEngine.buildLUT と同じ。格子点ごとに Lab 最近傍の候補の番号。"""
    grid = np.linspace(0.0, 1.0, size)
    points = np.array([(r, g, b) for r in grid for g in grid for b in grid])
    sample_lab = np.array([s[0] for s in samples])
    indices = np.zeros(len(points), dtype=int)
    for i in range(0, len(points), chunk):
        labs = srgb_to_lab_np(points[i:i + chunk])
        d = (labs[:, None, :] - sample_lab[None, :, :]) ** 2
        indices[i:i + chunk] = d.sum(axis=2).argmin(axis=1)
    return indices.reshape(size, size, size), np.array([s[0] for s in samples]), np.array([s[1] for s in samples])


def lut_lookup_np(indices, sample_lab, sample_rgb, rgb: np.ndarray) -> np.ndarray:
    """格子のまわりの 8 候補から Lab 距離で最も近い色。Swift の ColorLUT.lookup と同じ。"""
    rgb = np.atleast_2d(np.asarray(rgb, dtype=float))
    size = indices.shape[0]
    n = size - 1
    coords = np.clip(rgb, 0.0, 1.0) * n
    base = np.minimum(np.floor(coords).astype(int), n - 1)
    pix_lab = srgb_to_lab_np(rgb)

    best = np.zeros(len(rgb), dtype=int)
    best_distance = np.full(len(rgb), np.inf)
    for di in (0, 1):
        for dj in (0, 1):
            for dk in (0, 1):
                candidate = indices[base[:, 0] + di, base[:, 1] + dj, base[:, 2] + dk]
                delta = pix_lab - sample_lab[candidate]
                distance = (delta ** 2).sum(axis=1)
                better = distance < best_distance
                best = np.where(better, candidate, best)
                best_distance = np.where(better, distance, best_distance)
    return sample_rgb[best]


def test_lut():
    print("\n== 3D LUT（5 色の色域） ==")
    five = five_paints()
    samples = gamut_samples(five)
    print(f"    候補の色: {len(samples)} 通り（1〜3 色・10% 刻み）")
    check("5 色の候補は 455 通り", len(samples) == 5 + 10 * 9 + 10 * 36, str(len(samples)))

    sample_lab = np.array([s[0] for s in samples])
    sample_rgb = np.array([s[1] for s in samples])
    rng = np.random.default_rng(7)

    # numpy の経路が 1 対 1 の実装と同じ Lab を出すか
    probe = rng.random((20, 3))
    worst_lab = 0.0
    for rgb in probe:
        mine = srgb_to_lab_np(rgb)
        ref = cm.srgb_to_lab(tuple(rgb))
        worst_lab = max(worst_lab, max(abs(mine[i] - ref[i]) for i in range(3)))
    check("numpy の sRGB->Lab は 1 対 1 の実装と一致", worst_lab < 1e-9, f"最大誤差 {worst_lab:.2e}")

    indices, lut_lab, lut_rgb = build_lut(samples)
    check("LUT は 33×33×33 の格子", indices.shape == (33, 33, 33), str(indices.shape))
    check("格子点の番号は候補の範囲内", int(indices.max()) < len(samples), str(int(indices.max())))

    random_rgb = rng.random((2000, 3))
    mapped = lut_lookup_np(indices, lut_lab, lut_rgb, random_rgb)
    distances = np.sqrt(((mapped[:, None, :] - lut_rgb[None, :, :]) ** 2).sum(axis=2))
    check("変換後の色は必ず 5 色で作れる色そのもの", float(distances.min(axis=1).max()) < 1e-12,
          f"最大距離 {distances.min(axis=1).max():.2e}")

    # 5 色で作れる色を入れると、その色のまま返る
    probe = lut_rgb[rng.integers(0, len(lut_rgb), 200)]
    back = lut_lookup_np(indices, lut_lab, lut_rgb, probe)
    errors = [cm.delta_e_2000(tuple(probe[i]), tuple(back[i])) for i in range(len(probe))]
    check("5 色で作れる色は、その色のまま返る（ΔE<3）", max(errors) < 3.0, f"最大 ΔE {max(errors):.2f}")

    # 5 色で作れない鮮やかな色は、色域の内側へ寄る
    for label, rgb in [("純色の緑", (0.0, 1.0, 0.0)),
                       ("純色のマゼンタ", (1.0, 0.0, 1.0)),
                       ("純色の青", (0.0, 0.0, 1.0)),
                       ("鮮やかなシアン", (0.0, 1.0, 1.0))]:
        target = np.array([cm.srgb_to_lab(rgb)])
        before = float(delta_e_2000_np(target, sample_lab).min())
        out = lut_lookup_np(indices, lut_lab, lut_rgb, np.array([rgb]))[0]
        out_lab = np.array([cm.srgb_to_lab(tuple(float(c) for c in out))])
        after = float(delta_e_2000_np(out_lab, sample_lab).min())
        chroma_before = float(np.hypot(target[0, 1], target[0, 2]))
        chroma_after = float(np.hypot(out_lab[0, 1], out_lab[0, 2]))
        print(f"    {label}: ΔE {before:5.2f} -> {after:4.2f} / C* {chroma_before:5.1f} -> {chroma_after:5.1f}")
        check(f"{label} は色域の内側に収まる", after < before - 1e-6, f"{before:.3f} -> {after:.3f}")
        check(f"{label} は彩度が下がる", chroma_after <= chroma_before + 1e-6,
              f"C* {chroma_before:.1f} -> {chroma_after:.1f}")

    # 格子をまたいでも、隣り合う候補が同じなら同じ色
    same = lut_lookup_np(indices, lut_lab, lut_rgb, np.array([[0.5, 0.5, 0.5], [0.5, 0.5, 0.52]]))
    check("近い色どうしは同じか近い色になる",
          cm.delta_e_2000(tuple(same[0]), tuple(same[1])) < 5.0,
          f"ΔE {cm.delta_e_2000(tuple(same[0]), tuple(same[1])):.2f}")


# --- 9. 面化（Kuwahara） -----------------------------------------------------

def kuwahara_np(image: np.ndarray, radius: int) -> np.ndarray:
    """Swift の PreviewEngine.kuwahara と同じ、積分画像の 4 象限 Kuwahara。"""
    height, width = image.shape[:2]
    luma = 0.2126 * image[..., 0] + 0.7152 * image[..., 1] + 0.0722 * image[..., 2]

    def integral(a):
        return np.pad(np.cumsum(np.cumsum(a, axis=0), axis=1), ((1, 0), (1, 0)))

    sums = [integral(image[..., 0]), integral(image[..., 1]), integral(image[..., 2]),
            integral(luma), integral(luma ** 2)]

    def rect(s, x0, y0, x1, y1):
        return s[y1, x1] - s[y0, x1] - s[y1, x0] + s[y0, x0]

    ys, xs = np.mgrid[0:height, 0:width]
    best_var = np.full((height, width), np.inf)
    best_mean = np.zeros((height, width, 3))

    for quadrant in range(4):
        if quadrant in (0, 2):
            x0 = np.maximum(xs - radius, 0)
            x1 = xs + 1
        else:
            x0 = xs
            x1 = np.minimum(xs + radius + 1, width)
        if quadrant < 2:
            y0 = np.maximum(ys - radius, 0)
            y1 = ys + 1
        else:
            y0 = ys
            y1 = np.minimum(ys + radius + 1, height)
        area = (x1 - x0) * (y1 - y0)
        s_l = rect(sums[3], x0, y0, x1, y1)
        s_l2 = rect(sums[4], x0, y0, x1, y1)
        mean = s_l / area
        var = np.maximum(s_l2 / area - mean ** 2, 0)
        better = var < best_var
        best_var = np.where(better, var, best_var)
        for channel in range(3):
            m = rect(sums[channel], x0, y0, x1, y1) / area
            best_mean[..., channel] = np.where(better, m, best_mean[..., channel])
    return best_mean


def test_kuwahara():
    print("\n== 面化（Kuwahara） ==")
    uniform = np.full((32, 32, 3), (0.3, 0.5, 0.7))
    check("一様な画像は変わらない", float(np.abs(kuwahara_np(uniform, 3) - uniform).max()) < 1e-12)

    step = np.zeros((24, 24, 3))
    step[:, :12] = 0.2
    step[:, 12:] = 0.8
    radius = 3
    out = kuwahara_np(step, radius)
    left = out[:, :12 - radius]
    right = out[:, 12 + radius:]
    check("エッジから離れた面の色はそのまま（左 0.2）", float(np.abs(left - 0.2).max()) < 1e-12)
    check("エッジから離れた面の色はそのまま（右 0.8）", float(np.abs(right - 0.8).max()) < 1e-12)

    edge_values = np.round(out[:, 10:14, 0] * 1000) / 1000
    only_sides = np.isin(edge_values, [0.2, 0.8])
    check("エッジの境目でも中間色を作らない", bool(only_sides.all()), str(np.unique(edge_values)))

    rng = np.random.default_rng(3)
    noisy = np.clip(0.5 + rng.normal(0, 0.12, (40, 40, 3)), 0, 1)
    smoothed = kuwahara_np(noisy, 3)

    def local_variance(img):
        luma = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
        pad = np.pad(luma, 4, mode='edge')
        windows = np.lib.stride_tricks.sliding_window_view(pad, (9, 9))
        return float(np.mean(np.var(windows, axis=(2, 3))))

    check("細かなムラが減る（面になる）", local_variance(smoothed) < local_variance(noisy) * 0.6,
          f"{local_variance(noisy):.5f} -> {local_variance(smoothed):.5f}")

    # 面化してから 5 色の色域へ。面の境目は残り、色は 5 色の範囲に収まる。
    five = five_paints()
    indices, lut_lab, lut_rgb = build_lut(gamut_samples(five))
    gradient = np.zeros((120, 160, 3))
    gradient[..., 0] = np.linspace(0, 1, 160)[None, :]
    gradient[..., 1] = np.linspace(0, 1, 120)[:, None]
    gradient[..., 2] = 0.35
    composed = lut_lookup_np(indices, lut_lab, lut_rgb, kuwahara_np(gradient, 3).reshape(-1, 3))
    distances = np.sqrt(((composed[:, None, :] - lut_rgb[None, :, :]) ** 2).sum(axis=2))
    check("面化＋5色再現の色も、5 色で作れる色そのもの", float(distances.min(axis=1).max()) < 1e-12,
          f"最大距離 {distances.min(axis=1).max():.2e}")
    column_means = composed.reshape(120, 160, 3)[:, :, 0].mean(axis=0)
    check("面化＋5色再現でも左右のグラデーションは残る",
          float(column_means[-10:].mean() - column_means[:10].mean()) > 0.05,
          f"{column_means[:10].mean():.3f} -> {column_means[-10:].mean():.3f}")


if __name__ == "__main__":
    test_conversions()
    test_delta_e()
    test_kubelka_munk()
    test_solver()
    test_geometry()
    test_palette()
    test_five_color_solver()
    test_lut()
    test_kuwahara()
    print()
    if failures:
        print(f"NG: {len(failures)} 件 -> {failures}")
        raise SystemExit(1)
    print("すべての検証に合格")
