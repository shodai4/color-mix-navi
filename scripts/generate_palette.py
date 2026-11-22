"""絵具パレットの分光データを作り、Sources/PaletteData.swift を書き出す。

油絵具は scripts/extract_catalog.py が抜き出したホルベイン公式カタログ
（2026年11月2日現在）の全色。透明水彩は従来の 18 色。

考える順番:
  1. 色見本の左半分（原色）の RGB から目標 Lab を決める。
  2. 右半分（パーマネントホワイトSF 1:1 混色）の RGB から目標 Lab を決める。
  3. 平滑な基底（定数 + ガウス）で分光反射率を表し、散乱係数 S と一緒に、
     「原色の予測 Lab」と「白 1:1 混色の予測 Lab」の両方が見本に合うよう当てはめる。
     S は白を 1.0 とした相対値で、混色の淡まり方をカタログの実例に合わせるための値。
  4. 当てはめた反射率・Lab・散乱係数と、カタログの品番・系統・乾燥日数・
     透明性・耐光性・混色記号・価格・顔料を Swift に埋め込む。

データの出どころ:
  - 色・品番・記号・価格: downloads/油絵具カタログ.pdf（ホルベイン画材、2026/11/2）
    色見本は印刷物なので、カタログ自身の注記どおり実際の絵具の色とは差がある。
  - カタログに単色の掲載がないホワイト（パーマネントホワイトSF・チタニウムホワイト・
    ジンクホワイトSF）とアリザリンクリムソンは、ホルベイン公式 TDS の値を残す。
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np

import colormath as cm

HERE = Path(__file__).resolve().parent
DATA = HERE / "spectral-data"
CATALOG = HERE / "catalog" / "oil_catalog.json"
ROOT = HERE.parent

BANDS = list(range(380, 731, 10))
CENTER = np.array(BANDS, dtype=float)

WHITE_LAB = (96.9, 0.0, 1.5)


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
R_MIN, R_MAX = 0.0015, 0.975


def curve_from_params(c):
    r = BASIS @ np.asarray(c, dtype=float)
    return np.clip(r, R_MIN, R_MAX)


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


STARTS = [
    np.array([0.35] + [0.0] * 7),
    np.array([0.55, -0.3, 0.1, 0.1, 0.1, 0.1, -0.2, -0.2]),
    np.array([0.20, 0.0, 0.35, -0.10, -0.10, 0.10, 0.30, 0.20]),
    np.array([0.80, -0.30, -0.10, -0.10, -0.10, -0.10, -0.20, -0.20]),
    np.array([0.08, 0.05, 0.05, 0.10, 0.10, 0.05, 0.10, 0.10]),
    np.array([0.45, 0.0, 0.4, 0.0, -0.2, -0.2, 0.2, 0.2]),
]


def fit_pigment(target_lab):
    """原色 1 点だけに合わせる（白・カタログ外の色むけ）。"""
    def loss(c):
        refl = curve_from_params(c)
        de = cm.delta_e_2000(reflectance_to_lab(refl), target_lab)
        penalty = 0.0008 * float(np.sum(np.asarray(c[1:]) ** 2))
        return de * de + penalty

    best_c, best_v = None, float("inf")
    for s in STARTS:
        c, v = nelder_mead(loss, s)
        if v < best_v:
            best_c, best_v = c, v
    return curve_from_params(best_c), reflectance_to_lab(curve_from_params(best_c))


WHITE_REFL, _ = fit_pigment(WHITE_LAB)


def fit_catalog_color(pure_rgb, tint_rgb, scatter_hint=0.20):
    """原色と白 1:1 混色の両方に合わせて、反射率と散乱係数を決める。"""
    pure = cm.srgb_to_lab(tuple(c / 255.0 for c in pure_rgb))
    tint = cm.srgb_to_lab(tuple(c / 255.0 for c in tint_rgb))

    def loss(p):
        refl = curve_from_params(p[:8])
        s = float(min(1.0, max(0.02, p[8])))
        lab = reflectance_to_lab(refl)
        mixed = cm.mix_two_constant([refl, WHITE_REFL], [s, 1.0], [0.5, 0.5])
        tlab = reflectance_to_lab(mixed)
        penalty = 0.0015 * float(np.sum(np.asarray(p[:8][1:]) ** 2))
        return cm.delta_e_2000(lab, pure) ** 2 + cm.delta_e_2000(tlab, tint) ** 2 + penalty

    starts = [np.append(s, scatter_hint) for s in STARTS[:4]]
    starts.append(np.append(STARTS[1], scatter_hint * 3))
    best_p, best_v = None, float("inf")
    for st in starts:
        p, v = nelder_mead(loss, st, step=0.12, iters=1600)
        if v < best_v:
            best_p, best_v = p, v

    refl = curve_from_params(best_p[:8])
    s = float(min(1.0, max(0.02, best_p[8])))
    lab = reflectance_to_lab(refl)
    tlab = reflectance_to_lab(cm.mix_two_constant([refl, WHITE_REFL], [s, 1.0], [0.5, 0.5]))
    return {
        "refl": refl,
        "lab": lab,
        "scatter": s,
        "dE_pure": cm.delta_e_2000(lab, pure),
        "dE_tint": cm.delta_e_2000(tlab, tint),
        "target_pure": pure,
        "target_tint": tint,
    }


# --- 絵具の定義 ------------------------------------------------------------

# カタログに単色の掲載がない色。値は TDS（と従来のパレット）のまま。
EXTRAS = [
    {"name": "パーマネントホワイトSF", "pigment": "PW6", "lab": WHITE_LAB, "scatter": 1.00,
     "group": "白", "note": "カタログではセットの内容品として掲載"},
    {"name": "チタニウムホワイト", "pigment": "PW6", "lab": (97.9, 0.0, -1.1), "scatter": 1.00,
     "group": "白", "note": "カタログではセットの内容品として掲載"},
    {"name": "ジンクホワイトSF", "pigment": "PW4", "lab": (96.0, 0.0, 1.0), "scatter": 0.85,
     "group": "白", "note": "TDS の値。本カタログの一覧には無い"},
    {"name": "アリザリンクリムソン", "pigment": "PR83", "lab": (24.6, 39.8, 23.6), "scatter": 0.06,
     "group": "赤", "note": "TDS の値。本カタログの一覧には無い"},
]

CLASSIC_NAMES = [
    "パーマネントホワイトSF", "ジンクホワイトSF", "レモンイエロー", "カドミウムイエロー",
    "イエローオーカー", "カドミウムオレンジ", "バーミリオンヒュー", "カドミウムレッド",
    "クリムソンレーキ", "アリザリンクリムソン", "ローシェンナ", "バーントシェンナ",
    "バーントアンバー", "ウルトラマリンディープ", "コバルトブルーヒュー", "セルリアンブルー",
    "ビリジャンヒュー", "アイボリブラック",
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

PERMANENCY_LABEL = {4: "絶対堅牢", 3: "堅牢", 2: "比較的堅牢", 1: "変化しやすい", 0: "著しく変化しやすい"}


def normalize_name(text):
    """カタログの字間スペースを詰める（『ジョーン ブリヤン No.2』→『ジョーンブリヤン No.2』）。"""
    compact = re.sub(r"\s+", "", text)
    return compact.replace("No.", " No.").replace("  No.", " No.").strip()


def swift_string(text):
    return text.replace('\\', '\\\\').replace('"', '\\"')


def paint_swift(index, item, refl, lab, scatter, classic, meta):
    values = ", ".join(f"{v:.4f}" for v in refl)
    if meta:
        admix = f'"{meta["admixing"]}"' if meta.get("admixing") else "nil"
        ref = f'"{meta["ref"]}"' if meta.get("ref") else "nil"
        meta_text = (
            f'PaintMeta(ref: {ref}, group: "{meta["group"]}", series: "{meta["series"]}",\n'
            f'                        permanency: {meta["permanency"]}, drying: {meta["drying"]},\n'
            f'                        opacity: "{meta["opacity"]}", admixing: {admix},\n'
            f'                        price20: {meta["price20"]}, metallic: {str(meta["metallic"]).lower()})'
        )
        meta_part = f"meta: {meta_text}"
    else:
        meta_part = "meta: nil"
    return (
        f'        Paint(id: {index}, name: "{swift_string(item["name"])}", '
        f'pigment: "{swift_string(item["pigment"])}", scatter: {scatter:.2f},\n'
        f'              lab: LabColor(l: {lab[0]:.2f}, a: {lab[1]:.2f}, b: {lab[2]:.2f}),\n'
        f'              reflectance: [{values}],\n'
        f'              classic: {str(classic).lower()},\n'
        f'              {meta_part}),'
    )


def main():
    catalog = json.loads(CATALOG.read_text())
    report = []
    oil = []

    for row in catalog["colors"]:
        name = normalize_name(row["name_jp"])
        result = fit_catalog_color(row["pure_rgb"], row["tint_rgb"])
        metallic = row["group"] == "金銀"
        if metallic:
            # 金属色は Kubelka-Munk の前提から外れる。見本の原色だけに合わせる。
            refl, lab = fit_pigment(result["target_pure"])
            result = dict(result, refl=refl, lab=lab, scatter=0.90,
                          dE_pure=cm.delta_e_2000(lab, result["target_pure"]),
                          dE_tint=float("nan"))
        pigment = row["pigments"] or ("岩絵具" if row["group"] == "アンティーク" else "")
        opacity = row["opacity"] or "不透明"
        oil.append({
            "name": name,
            "pigment": pigment,
            "lab": result["lab"],
            "refl": result["refl"],
            "scatter": result["scatter"],
            "classic": name in CLASSIC_NAMES,
            "meta": {
                "ref": row["ref20"],
                "group": row["group"],
                "series": row["series"] or "",
                "permanency": row["permanency"],
                "drying": row["drying"],
                "opacity": opacity,
                "admixing": row["admixing"],
                "price20": row["price_20ml"] or 0,
                "metallic": metallic,
            },
        })
        report.append({
            "ref": row["ref20"], "name": name, "drying": row["drying"], "opacity": opacity,
            "dE_pure": round(result["dE_pure"], 3),
            "dE_tint": None if metallic else round(result["dE_tint"], 3),
            "scatter": round(result["scatter"], 3),
        })

    for extra in EXTRAS:
        refl, lab = fit_pigment(extra["lab"])
        oil.append({
            "name": extra["name"], "pigment": extra["pigment"], "lab": lab, "refl": refl,
            "scatter": extra["scatter"], "classic": extra["name"] in CLASSIC_NAMES, "meta": None,
        })
        report.append({"ref": None, "name": extra["name"], "drying": None, "opacity": None,
                       "dE_pure": round(cm.delta_e_2000(lab, extra["lab"]), 3), "dE_tint": None,
                       "scatter": extra["scatter"]})

    watercolor = []
    for name, pigment, lab, scatter in WATERCOLOR:
        refl, fitted = fit_pigment(lab)
        watercolor.append({"name": name, "pigment": pigment, "lab": fitted, "refl": refl,
                           "scatter": scatter})

    names = [p["name"] for p in oil]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise SystemExit(f"名前が重複: {duplicates}")

    missing_classic = [n for n in CLASSIC_NAMES if n not in names]
    if missing_classic:
        raise SystemExit(f"定番色が見つからない: {missing_classic}")

    header = (
        "// このファイルは scripts/generate_palette.py が生成します。手で編集しないこと。\n"
        "// 油絵具: ホルベイン公式カタログ（2026年11月2日現在）の全色。\n"
        "// 透明水彩: ホルベイン公式 TDS とカラーチャートの 18 色。\n"
        "// 分光反射率は 380-730nm / 10nm の 36 バンド。\n"
        "// 油絵具は『原色』と『パーマネントホワイトSF 1:1 混色』の両方の見本に合うよう、\n"
        "// 反射率と散乱係数を当てはめた近似値。\n"
        "// scatter は 2定数 Kubelka-Munk 用の散乱係数（パーマネントホワイトSF = 1.0）。\n\n"
        "import Foundation\n\n"
        "enum PaletteData {\n"
    )
    body = ["    static let oil: [Paint] = ["]
    for i, item in enumerate(oil):
        body.append(paint_swift(i, item, item["refl"], item["lab"], item["scatter"],
                                item["classic"], item["meta"]))
    body.append("    ]\n")
    body.append("    static let watercolor: [Paint] = [")
    for i, item in enumerate(watercolor):
        body.append(paint_swift(i, item, item["refl"], item["lab"], item["scatter"], False, None))
    body.append("    ]\n")
    body.append("    static let bandCount = 36")
    body.append("}")

    (ROOT / "Sources" / "PaletteData.swift").write_text(header + "\n".join(body) + "\n")

    (CATALOG.parent / "palette_report.json").write_text(
        json.dumps({"colors": report}, ensure_ascii=False, indent=1) + "\n"
    )

    print(f"油絵具 {len(oil)} 色 / 透明水彩 {len(watercolor)} 色")
    worst = sorted([r for r in report if r["dE_tint"] is not None], key=lambda r: -r["dE_tint"])[:8]
    print("白混色の当てはめが悪い順:")
    for r in worst:
        print(f"  {r['name'][:20]:22s} dE(pure)={r['dE_pure']:.2f} dE(tint)={r['dE_tint']:.2f} S={r['scatter']}")
    print("原色の当てはめ最大:", max(r["dE_pure"] for r in report))
    print("wrote Sources/PaletteData.swift")


if __name__ == "__main__":
    main()
