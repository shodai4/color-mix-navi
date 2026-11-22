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
        r'lab: LabColor\(([-0-9.]+), ([-0-9.]+), ([-0-9.]+)\),\s*'
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
    black = next(p for p in OIL if p["pigment"] == "PBk9")
    red = next(p for p in OIL if p["name"] == "カドミウムレッド")
    yellow = next(p for p in OIL if p["name"] == "カドミウムイエロー")
    blue = next(p for p in OIL if p["name"] == "ウルトラマリン")

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
    check("赤30+白70 は明るいピンク（L*60 以上・赤みを保つ）",
          lab[0] > 60 and lab[1] > 20, f"L* {lab[0]:.1f}, a* {lab[1]:.1f}")

    lab, _ = mix_lab([yellow, blue], [0.5, 0.5])
    print(f"    黄50+青50 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("黄+青 50:50 は緑（a*<0 かつ b*>0、紫にならない）",
          lab[1] < 0 and lab[2] > 0, f"Lab {tuple(round(v, 1) for v in lab)}")

    lab, _ = mix_lab([yellow, blue], [0.7, 0.3])
    print(f"    黄70+青30 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("黄70+青30 は黄緑", lab[1] < 0 and lab[2] > 20, f"Lab {tuple(round(v, 1) for v in lab)}")


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
    blue = next(p for p in OIL if p["name"] == "ウルトラマリン")
    mid, _ = mix_lab([yellow, blue], [0.5, 0.5])
    res = solve_fast(mid, OIL, max_paints=3, limit=3)
    print(f"  黄+青の中間色 Lab {tuple(round(v, 1) for v in mid)} に対する上位3案:")
    for de, names, w, lab in res:
        print(f"    ΔE {de:5.2f}  " + ", ".join(f"{n} {int(round(x * 100))}%" for n, x in zip(names, w)))
    check("中間色の 1 位は ΔE<3", res[0][0] < 3.0, f"ΔE {res[0][0]:.3f}")

    n_evals = 18 + 153 * 9 + 816 * 36
    print(f"  1 回の全探索で評価する配合数: {n_evals:,}（1・2・3 色 / 10% 刻み）")



# --- 5. データの健全性 -----------------------------------------------------

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
    check("埋め込んだ Lab は反射率から再計算した値と一致", worst < 0.02, f"最大 ΔE {worst:.3f}")
    check("名前の重複なし（パレット内）",
          len({p["name"] for p in OIL}) == len(OIL)
          and len({p["name"] for p in WATERCOLOR}) == len(WATERCOLOR))


if __name__ == "__main__":
    test_conversions()
    test_delta_e()
    test_kubelka_munk()
    test_solver()
    test_palette()
    print()
    if failures:
        print(f"NG: {len(failures)} 件 -> {failures}")
        raise SystemExit(1)
    print("すべての検証に合格")
