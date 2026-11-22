"""数値検証: 色変換・CIEDE2000・Kubelka-Munk・レシピ探索。

Swift 実装 (ColorScience.swift / MixSolver.swift) と同じ手順を Python で書き、
既知の基準値と突き合わせる。実行: python3 scripts/verify_color_math.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
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
    pattern = (
        r'Paint\(id: (\d+), name: "([^"]+)", pigment: "([^"]+)", scatter: ([0-9.]+),\s*'
        r'lab: LabColor\(l: ([-0-9.]+), a: ([-0-9.]+), b: ([-0-9.]+)\),\s*'
        r'reflectance: \[([^\]]+)\],\s*'
        r'classic: (true|false),\s*'
        r'meta: (nil|PaintMeta\(ref: (?:nil|"([^"]*)"), group: "([^"]*)", series: "([^"]*)",\s*'
        r'permanency: (\d+), drying: (\d+),\s*'
        r'opacity: "([^"]*)", admixing: (?:nil|"([^"]*)"),\s*'
        r'price20: (\d+), metallic: (true|false)\))'
    )
    for m in re.finditer(pattern, block, re.DOTALL):
        meta = None
        if m.group(10) != "nil":
            meta = {
                "ref": m.group(11),
                "group": m.group(12),
                "series": m.group(13),
                "permanency": int(m.group(14)),
                "drying": int(m.group(15)),
                "opacity": m.group(16),
                "admixing": m.group(17),
                "price20": int(m.group(18)),
                "metallic": m.group(19) == "true",
            }
        paints.append({
            "id": int(m.group(1)),
            "name": m.group(2),
            "pigment": m.group(3),
            "scatter": float(m.group(4)),
            "lab": (float(m.group(5)), float(m.group(6)), float(m.group(7))),
            "refl": [float(v) for v in m.group(8).split(",")],
            "classic": m.group(9) == "true",
            "meta": meta,
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
    white = next(p for p in OIL if p["name"] == "パーマネントホワイトSF")
    black = next(p for p in OIL if p["name"] == "アイボリブラック")
    red = next(p for p in OIL if p["name"] == "カドミウムレッド")
    yellow = next(p for p in OIL if p["name"] == "カドミウムイエロー")
    blue = next(p for p in OIL if p["name"] == "ウルトラマリンディープ")

    lab, _ = mix_lab([white], [1.0])
    check("単色 100% は元の色と一致", cm.delta_e_2000(lab, white["lab"]) < 0.01,
          f"ΔE {cm.delta_e_2000(lab, white['lab']):.3f}")

    # アイボリブラックの散乱はカタログの 1:1 混色見本に合わせてあるので、
    # 白 1:1 で L* 35 前後まで落ちる（黒の着色力が強い）。
    lab, _ = mix_lab([white, black], [0.9, 0.1])
    print(f"    白90+黒10 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("白90+黒10 は明るいグレー", 55 < lab[0] < 80, f"L* {lab[0]:.1f}")

    lab, _ = mix_lab([white, black], [0.5, 0.5])
    print(f"    白50+黒50 -> Lab {tuple(round(v, 1) for v in lab)}")
    check("白50+黒50 は中明度のグレー（無彩色に近い）",
          25 < lab[0] < 45 and math.hypot(lab[1], lab[2]) < 12,
          f"L* {lab[0]:.1f}, C* {math.hypot(lab[1], lab[2]):.1f}")

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


# --- Swift の SolverCore と同じ「絞り込みつき」探索 --------------------------

def _segment_distance(point, a, b):
    ex, ey, ez = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    px, py, pz = point[0] - a[0], point[1] - a[1], point[2] - a[2]
    length = ex * ex + ey * ey + ez * ez
    t = (px * ex + py * ey + pz * ez) / length if length > 0 else 0.0
    t = min(max(t, 0.0), 1.0)
    dx, dy, dz = px - ex * t, py - ey * t, pz - ez * t
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _triangle_distance(point, a, b, c):
    ax, ay, az = a
    bx, by, bz = b
    cx, cy, cz = c
    px, py, pz = point
    abx, aby, abz = bx - ax, by - ay, bz - az
    acx, acy, acz = cx - ax, cy - ay, cz - az
    apx, apy, apz = px - ax, py - ay, pz - az
    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    if d1 <= 0 and d2 <= 0:
        return math.sqrt(apx * apx + apy * apy + apz * apz)
    bpx, bpy, bpz = px - bx, py - by, pz - bz
    d3 = abx * bpx + aby * bpy + abz * bpz
    d4 = acx * bpx + acy * bpy + acz * bpz
    if d3 >= 0 and d4 <= d3:
        return math.sqrt(bpx * bpx + bpy * bpy + bpz * bpz)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        qx, qy, qz = apx - abx * v, apy - aby * v, apz - abz * v
        return math.sqrt(qx * qx + qy * qy + qz * qz)
    cpx, cpy, cpz = px - cx, py - cy, pz - cz
    d5 = abx * cpx + aby * cpy + abz * cpz
    d6 = acx * cpx + acy * cpy + acz * cpz
    if d6 >= 0 and d5 <= d6:
        return math.sqrt(cpx * cpx + cpy * cpy + cpz * cpz)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        qx, qy, qz = apx - acx * w, apy - acy * w, apz - acz * w
        return math.sqrt(qx * qx + qy * qy + qz * qz)
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        qx, qy, qz = bpx - (cx - bx) * w, bpy - (cy - by) * w, bpz - (cz - bz) * w
        return math.sqrt(qx * qx + qy * qy + qz * qz)
    denom = va + vb + vc
    if abs(denom) < 1e-9:
        return _segment_distance(point, a, b)
    v = vb / denom
    w = vc / denom
    nx, ny, nz = apx - (abx * v + acx * w), apy - (aby * v + acy * w), apz - (abz * v + acz * w)
    return math.sqrt(nx * nx + ny * ny + nz * nz)


def _insert_sorted(best, item, keep):
    import bisect
    keys = [entry[0] for entry in best]
    index = bisect.bisect_left(keys, item[0])
    best.insert(index, item)
    if len(best) > keep:
        best.pop()


def closest_pairs(target, paints, keep):
    best = []
    labs = [p["lab"] for p in paints]
    n = len(labs)
    for i in range(n):
        for j in range(i + 1, n):
            distance = _segment_distance(target, labs[i], labs[j])
            if len(best) == keep and distance >= best[-1][0]:
                continue
            _insert_sorted(best, (distance, (i, j)), keep)
    return [entry[1] for entry in best]


def closest_triples(target, paints, keep, lifts=(0.0, 8.0, 16.0)):
    """Swift の closestTriples と同じ。混色は三角形より暗く出るので、
    目標色を持ち上げた位置からも三角形までの距離を見る。"""
    labs = [p["lab"] for p in paints]
    n = len(labs)
    merged = {}
    for lift in lifts:
        point = (target[0] + lift, target[1], target[2])
        best = []
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    distance = _triangle_distance(point, labs[i], labs[j], labs[k])
                    if len(best) == keep and distance >= best[-1][0]:
                        continue
                    _insert_sorted(best, (distance, (i, j, k)), keep)
        for distance, combo in best:
            if combo in merged and merged[combo] <= distance:
                continue
            merged[combo] = distance
    return [combo for combo, _ in sorted(merged.items(), key=lambda item: item[1])]


def solve_pruned(target, paints, max_paints=3, limit=3,
                 pair_keep=480, triple_keep=500, exhaustive_limit=24):
    """Swift の SolverCore.run と同じ手順（Lab の線分・三角形で組み合わせを絞る）。"""
    ks = ks_matrix(paints)
    best = []

    def offer(combo, weights):
        w = np.asarray(weights, dtype=float)
        if w.ndim == 1:
            w = w[None, :]
        labs = mix_lab_np(ks, combo, w)
        for w, lab in zip(weights, labs):
            de = cm.delta_e_2000(target, lab)
            if len(best) < 40:
                best.append((de, tuple(combo), w, lab))
                best.sort(key=lambda x: x[0])
            elif de < best[-1][0]:
                best[-1] = (de, tuple(combo), w, lab)
                best.sort(key=lambda x: x[0])

    n = len(paints)
    for i in range(n):
        offer((i,), [1.0])

    if max_paints >= 2:
        pairs = list(combinations(range(n), 2)) if n <= exhaustive_limit else closest_pairs(target, paints, pair_keep)
        weights = list(mix_weights(2))
        for combo in pairs:
            offer(combo, weights)

    if max_paints >= 3:
        triples = list(combinations(range(n), 3)) if n <= exhaustive_limit else closest_triples(target, paints, triple_keep)
        weights = list(mix_weights(3))
        for combo in triples:
            offer(combo, weights)

    out, seen = [], set()
    for de, key, w, lab in best:
        if key in seen:
            continue
        seen.add(key)
        out.append((de, [paints[i]["name"] for i in key], w, lab))
        if len(out) == limit:
            break
    return out


def test_solver():
    print("\n== レシピ探索 ==")
    classic = [p for p in OIL if p["classic"]]
    t0 = time.time()
    worst = 0.0
    for p in classic:
        res = solve_fast(p["lab"], classic, max_paints=3, limit=1)
        worst = max(worst, res[0][0])
    elapsed = time.time() - t0
    check(f"定番18色: すべて目標=その絵具の色で ΔE<1 の配合が見つかる（{elapsed:.1f} 秒）",
          worst < 1.0, f"最悪 ΔE {worst:.3f}")

    # 純 Python の素直な実装（Swift と同じ手順）と一致するか
    t0 = time.time()
    ref = solve(classic[5]["lab"], classic, max_paints=2, limit=1)
    mirror_ms = (time.time() - t0) * 1000
    fast = solve_fast(classic[5]["lab"], classic, max_paints=2, limit=1)
    check("素直な実装と numpy 版の最良解が一致",
          ref[0][1] == fast[0][1] and abs(ref[0][0] - fast[0][0]) < 1e-9,
          f"{ref[0][1]} ΔE {ref[0][0]:.4f}")
    print(f"  素直な実装（1-2色探索）: {mirror_ms:.0f} ms")

    # 2 色の中間色
    yellow = next(p for p in OIL if p["name"] == "カドミウムイエロー")
    blue = next(p for p in OIL if p["name"] == "ウルトラマリンディープ")
    mid, _ = mix_lab([yellow, blue], [0.5, 0.5])
    res = solve_fast(mid, classic, max_paints=3, limit=3)
    print(f"  黄+青の中間色 Lab {tuple(round(v, 1) for v in mid)} に対する上位3案（定番18色）:")
    for de, names, w, lab in res:
        print(f"    ΔE {de:5.2f}  " + ", ".join(f"{n} {int(round(x * 100))}%" for n, x in zip(names, w)))
    check("中間色の 1 位は ΔE<3", res[0][0] < 3.0, f"ΔE {res[0][0]:.3f}")

    n_evals = 111 + 6105 * 9 + 221815 * 36
    print(f"  全111色を総当たりにすると 1 回で {n_evals:,} 通り（絞り込みで 480×9 + 最大1500×36 に削る）")

    # 全111色: 絞り込みつきでも、その絵具の色に届く
    sample = [OIL[i] for i in (0, 6, 13, 24, 37, 52, 68, 81, 95, 104, 108)]
    t0 = time.time()
    worst = 0.0
    worst_name = ""
    for p in sample:
        found = solve_pruned(p["lab"], OIL, max_paints=3, limit=1)
        if found[0][0] > worst:
            worst, worst_name = found[0][0], p["name"]
    elapsed = time.time() - t0
    check(f"全111色: 絞り込みつき探索で自分の色に ΔE<1（{elapsed:.1f} 秒）",
          worst < 1.0, f"最悪 ΔE {worst:.3f}（{worst_name}）")

    # 既知の 3 色混色を当てられるか（絞り込みが正解を落としていないか）
    import random
    rng = random.Random(11)
    broken = []
    for _ in range(8):
        combo = rng.sample(range(len(OIL)), 3)
        weights = rng.choice([[0.5, 0.3, 0.2], [0.6, 0.2, 0.2], [0.4, 0.4, 0.2], [0.5, 0.4, 0.1]])
        target, _ = mix_lab([OIL[i] for i in combo], weights)
        found = solve_pruned(target, OIL, max_paints=3, limit=1)
        if found[0][0] > 1.5:
            broken.append(([OIL[i]["name"] for i in combo], round(found[0][0], 2)))
    check("既知の3色混色 8 通りを ΔE<1.5 で再現", not broken, str(broken))

    # 30 色では、絞り込みの結果が総当たりと同じ答えになるか
    subset = OIL[:30]
    diffs = []
    for hexv in ("#6E9BC5", "#B96A47", "#7FA05A"):
        target = cm.hex_to_lab(hexv)
        exact = solve_fast(target, subset, max_paints=3, limit=1)
        pruned = solve_pruned(target, subset, max_paints=3, limit=1)
        diffs.append((hexv, round(exact[0][0], 3), round(pruned[0][0], 3)))
    check("絞り込みつきの最良 ΔE が総当たりと 0.5 以内で一致",
          all(abs(e - q) < 0.5 for _, e, q in diffs), str(diffs))


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


# --- 5b. 写真の向き（EXIF Orientation） -------------------------------------

def swift_orientation_transforms():
    """PhotoSampler.swift の変換表をそのまま読み出す（Swift と Python を同じ 1 つの表で検算する）。"""
    text = (ROOT / "Sources" / "PhotoSampler.swift").read_text()
    pattern = re.compile(
        r"case (\d+): return CGAffineTransform\(a: (-?\d+), b: (-?\d+), c: (-?\d+), "
        r"d: (-?\d+), tx: ([wh0-9.]+), ty: ([wh0-9.]+)\)")
    table = {}
    for m in pattern.finditer(text):
        exif = int(m.group(1))
        table[exif] = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)),
                       m.group(6), m.group(7))
    return table


def swift_swaps_dimensions():
    text = (ROOT / "Sources" / "PhotoSampler.swift").read_text()
    m = re.search(r"\((\d+)\.\.\.(\d+)\)\.contains\(value\)", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def resolved(transform, w, h):
    a, b, c, d, tx, ty = transform
    lookup = {"w": w, "h": h}
    return (float(a), float(b), float(c), float(d),
            float(lookup.get(tx, tx)), float(lookup.get(ty, ty)))


def draw_normalized(src, transform, swaps):
    """CGBitmapContext に CGImage を変換つきで描いた結果を作る。

    - バッファは左上原点（先頭の行が絵の上）。CGImage も同じ並びで表示される。
    - ユーザー座標は左下原点（CGContext の既定）。変換がないとき、画素 (i, j)
      （左から i 列・上から j 行）はユーザー座標 (i + 0.5, 高さ - j - 0.5) に置かれる。
    """
    h, w = src.shape
    dst_h, dst_w = (w, h) if swaps else (h, w)
    a, b, c, d, tx, ty = resolved(transform, w, h)
    out = np.full((dst_h, dst_w), -1, dtype=int)
    for j in range(h):
        for i in range(w):
            x, y = i + 0.5, h - j - 0.5
            dx = a * x + c * y + tx
            dy = b * x + d * y + ty
            col = math.floor(dx)
            device_row = math.floor(dy)          # 下から数えた行
            out[dst_h - 1 - device_row, col] = src[j, i]
    return out


def displayed_shape(src, exif):
    """EXIF の向きで表示したときの絵（独立した定義: 回転・反転の合成）。"""
    if exif == 1:
        return src.copy()
    if exif == 2:
        return np.fliplr(src)                    # 左右反転
    if exif == 3:
        return np.rot90(src, 2)                  # 180°
    if exif == 4:
        return np.flipud(src)                    # 上下反転
    if exif == 5:
        return np.transpose(src)                 # 主対角で折り返す（転置）
    if exif == 6:
        return np.rot90(src, -1)                 # 時計回りに 90°
    if exif == 7:
        return np.rot90(np.fliplr(src), -1)      # 左右反転＋時計回りに 90°（反転）
    if exif == 8:
        return np.rot90(src, 1)                  # 反時計回りに 90°
    raise ValueError(exif)


def test_orientation():
    print("\n== 写真の向き（EXIF Orientation） ==")
    transforms = swift_orientation_transforms()
    check("変換表に EXIF 1〜8 がすべてある", sorted(transforms) == list(range(1, 9)),
          f"{sorted(transforms)}")

    swaps_range = swift_swaps_dimensions()
    check("縦横が入れ替わる向きは 5〜8", swaps_range == (5, 8), str(swaps_range))

    # 元画像の画素に「どの画素か」が分かる番号を入れて、向きごとの結果を照合する。
    samples = [np.arange(15).reshape(3, 5), np.arange(28).reshape(7, 4)]
    for exif in range(1, 9):
        swaps = swaps_range[0] <= exif <= swaps_range[1]
        ok = True
        detail = []
        for src in samples:
            got = draw_normalized(src, transforms[exif], swaps)
            want = displayed_shape(src, exif)
            if got.shape != want.shape or not np.array_equal(got, want):
                ok = False
                detail.append(f"{src.shape} -> {got.shape}（期待 {want.shape}）")
        check(f"EXIF {exif}: 描いた絵が表示の向きと一致", ok, "; ".join(detail))

    # 左上の画素がどこへ行くか（向きの意味そのものの確認）
    corners = {1: "left-top", 2: "right-top", 3: "right-bottom", 4: "left-bottom",
               5: "left-top", 6: "right-top", 7: "right-bottom", 8: "left-bottom"}
    corner_errors = []
    for exif, expect in corners.items():
        src = np.zeros((3, 5), dtype=int)
        src[0, 0] = 1
        swaps = swaps_range[0] <= exif <= swaps_range[1]
        got = np.argwhere(draw_normalized(src, transforms[exif], swaps) == 1)[0]
        h, w = got
        label = ("left" if w == 0 else "right") + "-" + ("top" if h == 0 else "bottom")
        if label != expect:
            corner_errors.append(f"EXIF {exif}: {label}（期待 {expect}）")
    check("左上の画素が、EXIF の意味どおりの角へ行く", not corner_errors, "; ".join(corner_errors))

    # 端末の写真の実寸: 縦で撮った 1 枚（記録は横 4032×3024・EXIF 6）
    portrait = draw_normalized(np.zeros((3024, 4032), dtype=int), transforms[6], True)
    check("縦で撮った写真（4032×3024・EXIF 6）は 3024×4032 の縦になる",
          portrait.shape == (4032, 3024), str(portrait.shape))
    rect = fitted_rect((portrait.shape[1], portrait.shape[0]), (390, 500))
    check("その写真は縦長の枠に合う（左右に余白が出る）",
          rect[3] > rect[2] and abs(rect[3] - 500) < 1e-9, f"{rect}")

    # 表示の中央を触ると、向きに関係なく元画像の中央の画素を拾う
    centre_errors = []
    for exif in range(1, 9):
        swaps = swaps_range[0] <= exif <= swaps_range[1]
        src = np.arange(15).reshape(3, 5)
        got = draw_normalized(src, transforms[exif], swaps)
        dh, dw = got.shape
        r = fitted_rect((dw, dh), (390, 500))
        x, y = pixel_point((r[0] + r[2] / 2, r[1] + r[3] / 2), r, (dw, dh))
        if got[y, x] != src[1, 2]:
            centre_errors.append(f"EXIF {exif}: {got[y, x]}（期待 {src[1, 2]}）")
    check("表示の中央を触ると、どの向きでも元画像の中央の画素を拾う", not centre_errors,
          "; ".join(centre_errors))

    # 直した原因そのものの見張り: UIImage の draw（上下反転の原因）を経由しない
    text = (ROOT / "Sources" / "PhotoSampler.swift").read_text()
    check("向きは CGImage と EXIF の値で焼き込み、UIImage の draw を使わない",
          "UIGraphicsPushContext" not in text and "UIImage(" not in text
          and "context.draw(cgImage" in text)


# --- 6. データの健全性 -----------------------------------------------------

def test_palette():
    print("\n== パレット ==")
    catalog_colors = [p for p in OIL if p["meta"]]
    check("油絵具は 111 色（カタログ 107 ＋ カタログ外 4）", len(OIL) == 111,
          f"{len(OIL)}（カタログ {len(catalog_colors)}）")
    check("透明水彩は 18 色", len(WATERCOLOR) == 18, str(len(WATERCOLOR)))
    check("カタログの色は 107 色", len(catalog_colors) == 107, str(len(catalog_colors)))
    check("定番 18 色が classic で指定されている",
          sum(1 for p in OIL if p["classic"]) == 18, str(sum(1 for p in OIL if p["classic"])))
    check("反射率はすべて 0-1 の範囲",
          all(0.0 <= v <= 1.0 for p in OIL + WATERCOLOR for v in p["refl"]))
    check("反射率は 36 バンド", all(len(p["refl"]) == 36 for p in OIL + WATERCOLOR))
    worst = 0.0
    for p in OIL + WATERCOLOR:
        worst = max(worst, cm.delta_e_2000(p["lab"], lab_from_reflectance(p["refl"])))
    check("埋め込んだ Lab は反射率から再計算した値と一致", worst < 0.1, f"最大 ΔE {worst:.3f}")
    check("名前の重複なし（パレット内）",
          len({p["name"] for p in OIL}) == len(OIL)
          and len({p["name"] for p in WATERCOLOR}) == len(WATERCOLOR))
    check("5 色プリセットの絵具がすべてパレットにある",
          all(name in {p["name"] for p in OIL}
              for name in ("パーマネントホワイトSF", "カドミウムレッド", "カドミウムイエロー",
                             "ウルトラマリンディープ", "アイボリブラック", "イエローオーカー",
                             "バーントシェンナ"))
          and all(name in {p["name"] for p in WATERCOLOR}
                  for name in ("チタニウムホワイト", "カドミウムレッドライト",
                               "カドミウムイエローペール", "ウルトラマリンディープ",
                               "アイボリブラック")))


# --- 6b. カタログ（PDF から抜いたデータ）との突き合わせ ---------------------

CATALOG_JSON = HERE / "catalog" / "oil_catalog.json"
REPORT_JSON = HERE / "catalog" / "palette_report.json"


def test_catalog():
    print("\n== カタログのデータ ==")
    cat = json.loads(CATALOG_JSON.read_text())
    rows = cat["colors"]
    prices = cat["prices"]

    check("カタログの色数は 107", len(rows) == 107, str(len(rows)))
    refs = [r["ref20"] for r in rows]
    check("品番（20ml）が重複しない", len(set(refs)) == len(refs))

    groups = Counter(r["group"] for r in rows)
    expect = Counter({"赤": 15, "橙": 3, "黄": 17, "緑": 17, "青": 18,
                      "紫": 7, "茶黒": 13, "灰": 8, "金銀": 2, "アンティーク": 7})
    check("系統の内訳が表のとおり", groups == expect, f"{dict(groups)}")

    check("乾燥所要日数が 1〜4", all(1 <= (r["drying"] or 0) <= 4 for r in rows),
          str([r["ref20"] for r in rows if not (1 <= (r["drying"] or 0) <= 4)]))
    check("透明性が 4 段階のいずれか（金属色はカタログに記号なし）",
          all(r["opacity"] in {"透明", "半透明", "半不透明", "不透明"}
              for r in rows if r["group"] != "金銀")
          and all(r["opacity"] is None for r in rows if r["group"] == "金銀"),
          str([(r["ref20"], r["opacity"]) for r in rows if r["group"] != "金銀"
               and r["opacity"] not in {"透明", "半透明", "半不透明", "不透明"}]))
    check("耐光性（＊の数）が 0〜4", all(0 <= r["permanency"] <= 4 for r in rows))
    check("シリーズ記号が A〜L", all(r["series"] in set("ABCDEFGHIJKL") for r in rows),
          str([(r["ref20"], r["series"]) for r in rows if r["series"] not in set("ABCDEFGHIJKL")]))

    price_table = prices["20ml"]
    bad = [(r["ref20"], r["series"], r["price_20ml"]) for r in rows
           if r["price_20ml"] != price_table[r["series"]]]
    check("20ml の価格がシリーズの価格表と一致", not bad, str(bad[:5]))
    check("価格表（20ml）の並びがカタログのとおり",
          price_table == {"A": 550, "B": 605, "C": 770, "D": 1430,
                          "E": 2310, "H": 2530, "I": 5060, "L": 3300}, str(price_table))
    check("価格表（40ml / 110ml / 10ml）の代表値",
          prices["40ml"]["H"] == 4620 and prices["110ml"]["E"] == 9350 and prices["10ml"]["A"] == 330)

    check("原色・白混色の RGB が 0〜255",
          all(0 <= v <= 255 for r in rows for v in r["pure_rgb"] + r["tint_rgb"]))
    check("原色と白混色が別の値", all(r["pure_rgb"] != r["tint_rgb"] for r in rows
                                  if r["group"] != "金銀"),
          str([r["ref20"] for r in rows if r["group"] != "金銀" and r["pure_rgb"] == r["tint_rgb"]]))

    # Swift のパレットと一致するか
    by_ref = {p["meta"]["ref"]: p for p in OIL if p["meta"]}
    mismatch = []
    worst_color = (0.0, "")
    for r in rows:
        p = by_ref.get(r["ref20"])
        if p is None:
            mismatch.append((r["ref20"], "missing"))
            continue
        if (p["meta"]["drying"] != r["drying"]
                or p["meta"]["opacity"] != (r["opacity"] or "不透明")
                or p["meta"]["price20"] != r["price_20ml"]
                or p["meta"]["group"] != r["group"]
                or p["meta"]["permanency"] != r["permanency"]):
            mismatch.append((r["ref20"], "field"))
        target = cm.srgb_to_lab(tuple(v / 255 for v in r["pure_rgb"]))
        de = cm.delta_e_2000(p["lab"], target)
        if de > worst_color[0]:
            worst_color = (de, r["name_jp"])
    check("Swift の品番・系統・乾燥・透明性・耐光・価格がカタログと一致", not mismatch, str(mismatch[:5]))
    check("Swift の色（Lab）が見本の原色と ΔE 8 以内", worst_color[0] < 8.0,
          f"最大 ΔE {worst_color[0]:.2f}（{worst_color[1]}）")

    # 白 1:1 混色の再現
    white = next(p for p in OIL if p["name"] == "パーマネントホワイトSF")
    deltas = []
    for r in rows:
        if r["group"] == "金銀":
            continue
        p = by_ref[r["ref20"]]
        refl = cm.mix_two_constant([p["refl"], white["refl"]],
                                   [p["scatter"], white["scatter"]], [0.5, 0.5])
        predicted = lab_from_reflectance(refl)
        target = cm.srgb_to_lab(tuple(v / 255 for v in r["tint_rgb"]))
        deltas.append((cm.delta_e_2000(predicted, target), p["name"]))
    deltas.sort()
    median = deltas[len(deltas) // 2][0]
    worst = deltas[-1]
    check("白 1:1 混色の予測がカタログの見本に合う（中央値 ΔE<2）", median < 2.0, f"中央値 {median:.2f}")
    check("白 1:1 混色の予測の最大 ΔE が 8 未満", worst[0] < 8.0,
          f"最大 {worst[0]:.2f}（{worst[1]}）")

    # 白混色は原色より明るい（金属色を除く）
    lighter = 0
    for r in rows:
        if r["group"] == "金銀":
            continue
        pure = cm.srgb_to_lab(tuple(v / 255 for v in r["pure_rgb"]))
        tint = cm.srgb_to_lab(tuple(v / 255 for v in r["tint_rgb"]))
        if tint[0] >= pure[0]:
            lighter += 1
    total = len([r for r in rows if r["group"] != "金銀"])
    check("白混色の見本は原色より明るい（金属色を除く）", lighter >= total - 3,
          f"{lighter}/{total}")

    report = json.loads(REPORT_JSON.read_text())["colors"]
    check("当てはめレポートの件数がパレットと一致", len(report) == len(OIL), str(len(report)))


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
        full = solve_pruned(target, OIL, max_paints=3, limit=3)
        used = {n for recipe in limited for n in recipe[1]}
        inside = used <= names
        ok_subset = ok_subset and inside
        print(f"    {label}: 5 色の最良 ΔE {limited[0][0]:5.2f} / 全色の最良 ΔE {full[0][0]:5.2f} "
              f"({', '.join(limited[0][1])})")
        check(f"{label}: 5 色以外が混ざらない", inside, str(used - names))
        check(f"{label}: 全色のほうが同じか良い（絞り込みの遅れ 0.3 まで）",
              full[0][0] <= limited[0][0] + 0.3,
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
    test_orientation()
    test_palette()
    test_catalog()
    test_five_color_solver()
    test_lut()
    test_kuwahara()
    print()
    if failures:
        print(f"NG: {len(failures)} 件 -> {failures}")
        raise SystemExit(1)
    print("すべての検証に合格")
