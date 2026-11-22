"""ホルベイン油絵具カタログ（PDF）から全色のデータを抜き出す。

入力: downloads/油絵具カタログ.pdf（2026年11月2日現在・全7ページ）
出力: scripts/catalog/oil_catalog.json

ページの使われ方:
  P2-P4  色見本。1色につき「左半分＝原色」「右半分＝パーマネントホワイトSF 1:1 混色」。
         見本の下に品番・色名（英/仏/日）・耐光性・乾燥日数・シリーズ記号。
  P5-P6  全色一覧表。品番（10/20/40/110ml）・色名・シリーズ・耐光性・混色記号・
         乾燥所要日数・透明性（記号）・毒性注意・使用顔料。
  P7     価格一覧（サイズ×シリーズの税込価格）。

方針:
  - 数値・記号は表（P5-P6）を正とする。
  - 色（RGB）だけは P2-P4 の見本から、実際の描画を読んで採る。
  - 透明性の記号はベクター図形なので、記号の形（輪郭だけ／半分塗り／縦線入り／塗りつぶし）で判別する。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pymupdf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PDF = ROOT.parent.parent / "downloads" / "油絵具カタログ.pdf"
OUT = HERE / "catalog" / "oil_catalog.json"

SCALE = 300 / 72  # 300dpi で描画したときの pt -> px

ROMAN = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4}
SERIES = set("ABCDEFGHIJKL")
SERIES_WIDE = {chr(ord("Ａ") + i): chr(ord("A") + i) for i in range(12)}

JP = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
REF = re.compile(r"^(HH|H)(\d{3})$")
PIGMENT = re.compile(r"^P[A-Z][a-z]?\d+$")

GROUPS = {
    "RED": "赤",
    "ORANGE": "橙",
    "YELLOW": "黄",
    "GREEN": "緑",
    "BLUE": "青",
    "VIOLET": "紫",
    "BROWN & BLACK": "茶黒",
    "GREY": "灰",
    "GOLD & SILVER": "金銀",
    "ANTIQUE COLOR（岩絵具使用・油絵具）": "アンティーク",
}
SIZE_COLUMNS = [(30, 60, "10ml"), (60, 88, "20ml"), (88, 110, "40ml"), (110, 137, "110ml")]


# ---------------------------------------------------------------- 文字の拾い出し


def words(page):
    return [w for w in page.get_text("words") if w[4].strip()]


def group_rows(ws, tol=2.6):
    rows = []
    for w in sorted(ws, key=lambda w: w[1]):
        for row in rows:
            if abs(row["y"] - w[1]) < tol:
                row["words"].append(w)
                break
        else:
            rows.append({"y": w[1], "words": [w]})
    for row in rows:
        row["words"].sort(key=lambda w: w[0])
    return sorted(rows, key=lambda r: r["y"])


def text_of(row):
    return " ".join(w[4] for w in row["words"])


# ---------------------------------------------------------------- 一覧表（P5-P6）


def opacity_of(page, y):
    """透明性の記号を、その行の高さにある円の形から判別する。

    記号は文字ではなくベクター図形で、行の文字より 2pt 下に中心がある。
    輪郭だけ＝透明、左半分塗り＝半透明、縦線入り＝半不透明、塗りつぶし＝不透明。
    """
    best = None
    target = y + 2.0
    for d in page.get_drawings():
        r = d["rect"]
        if not (428 < r.x0 < 462 and 4 < r.height < 8 and r.width < 8):
            continue
        if abs(r.y0 - target) > 3.0:
            continue
        if best is None or abs(r.y0 - target) < abs(best[0] - target):
            best = (r.y0, d)
    if best is None:
        return None
    kinds = set(i[0] for i in best[1]["items"])
    count = len(best[1]["items"])
    if count == 8 and "l" not in kinds:
        return "透明"
    if count == 7:
        return "半透明"
    if count == 10:
        return "半不透明"
    if count == 4:
        return "不透明"
    return None


def normalize_pigments(parts):
    """['PR177,','254'] -> 'PR177+PR254'。『, 29』の続き番号は同じ系統の別番号。"""
    out = []
    pending = None
    for p in parts:
        p = p.strip(",. ")
        if PIGMENT.match(p):
            if pending:
                out.append(pending)
            pending = p
        elif pending and re.fullmatch(r"\d{1,3}", p):
            family = re.match(r"^P[A-Z][a-z]?", pending).group(0)
            out.append(pending)
            pending = family + p
    if pending:
        out.append(pending)
    return "+".join(out)


def parse_table(pages):
    items = []
    group = None
    for page in pages:
        for row in group_rows(words(page)):
            tokens = [(w[0], w[4]) for w in row["words"]]
            refs = [t for _, t in tokens if REF.match(t)]

            # 色の系統の見出し
            left_text = " ".join(
                t for x, t in tokens if x < 200 and re.fullmatch(r"[A-Z&]+", t)
            ).strip()
            heading = GROUPS.get(left_text)
            if heading is None:
                heading = next((GROUPS[t] for x, t in tokens if t in GROUPS and x < 200), None)
            if heading is None and not refs:
                heading = next((GROUPS[t] for _, t in tokens if t in GROUPS), None)
            if heading is None and any(t == "ANTIQUE" for _, t in tokens) and any(
                t.startswith("COLOR") for _, t in tokens
            ):
                heading = "アンティーク"
            if heading:
                group = heading
            if not refs or row["y"] < 56:
                continue
            if any(re.match(r"H9\d\d", t) for t in refs):
                continue  # セットの行

            sizes = {"10ml": None, "20ml": None, "40ml": None, "110ml": None}
            for x0, x1, key in SIZE_COLUMNS:
                for x, t in tokens:
                    if x0 <= x < x1 and REF.match(t):
                        sizes[key] = t

            jp, en, series, permanency, admix, drying, pigments = [], [], None, 0, None, None, []
            toxicity = None
            traditional = None
            is_antique = group == "アンティーク"
            for x, tok in tokens:
                if REF.match(tok) or tok in ("ー", "-"):
                    continue
                if tok in SERIES and 330 <= x < 365:
                    series = tok
                elif tok in SERIES_WIDE:
                    series = SERIES_WIDE[tok]
                elif "＊" in tok:
                    permanency = tok.count("＊")
                elif any(ch in ROMAN for ch in tok):
                    drying = next(ROMAN[ch] for ch in tok if ch in ROMAN)
                elif tok in ("N", "S") and 380 < x < 410:
                    admix = tok
                elif "Co" in tok:
                    toxicity = "コバルト"
                elif 135 <= x < 235 and (JP.search(tok) or tok.startswith("No.")):
                    if is_antique and x >= 200 and traditional is None:
                        traditional = tok
                    else:
                        jp.append(tok)
                elif 235 <= x < 340:
                    en.append(tok)
                elif x >= 460:
                    pigments.append(tok)

            items.append(
                {
                    "refs": sizes,
                    "ref20": sizes["20ml"] or next((r for r in sizes.values() if r), None),
                    "name_jp": "".join(jp).strip(),
                    "name_en": " ".join(en).strip(),
                    "traditional": traditional,
                    "group": group,
                    "series": series,
                    "permanency": permanency,
                    "admixing": admix,
                    "drying": drying,
                    "opacity": opacity_of(page, row["y"]),
                    "toxicity": toxicity,
                    "pigments": normalize_pigments(pigments),
                }
            )
    return items


# ---------------------------------------------------------------- 価格（P7）


def parse_prices(page):
    """サイズ×シリーズの税込価格。左の列が 10ml/20ml、右の列が 40ml/110ml。"""
    prices = {"10ml": {}, "20ml": {}, "40ml": {}, "110ml": {}}
    for row in group_rows(words(page)):
        cells = {"left": [], "right": []}
        for w in row["words"]:
            cells["left" if w[0] < 330 else "right"].append(w)
        for side, ws in cells.items():
            if not ws:
                continue
            series = None
            price = None
            for w in ws:
                tok = w[4]
                if tok in SERIES:
                    series = tok
                elif tok in SERIES_WIDE:
                    series = SERIES_WIDE[tok]
                elif tok.startswith("¥") and price is None:
                    price = int(tok[1:].replace(",", ""))
            if not (series and price):
                continue
            y = row["y"]
            if side == "left":
                size = "10ml" if y < 235 else ("20ml" if y < 400 else None)
            else:
                size = "40ml" if y < 315 else ("110ml" if y < 430 else None)
            if size:
                prices[size][series] = price
    return prices


# ---------------------------------------------------------------- 色見本（P2-P4）


def caption_lines(page, anchor):
    """品番の行を受けて、その見本の説明（色名・記号）を行ごとに集める。"""
    x0 = min(w[0] for w in anchor)
    y0 = min(w[1] for w in anchor)
    ws = [w for w in words(page) if y0 - 1.5 <= w[1] <= y0 + 32 and x0 - 6 <= w[0] <= x0 + 108]
    return group_rows(ws)


def parse_swatch_page(page):
    ws = words(page)
    refs = [w for w in ws if REF.match(w[4])]
    clusters = []
    for w in sorted(refs, key=lambda w: (round(w[1] / 2), w[0])):
        for c in clusters:
            right = max(v[2] for v in c)
            if abs(c[0][1] - w[1]) < 1.6 and -1 <= w[0] - right < 32:
                c.append(w)
                break
        else:
            clusters.append([w])

    found = []
    for c in clusters:
        y0 = min(w[1] for w in c)
        x0 = min(w[0] for w in c)
        lines = caption_lines(page, c)
        flat = [w[4] for line in lines for w in line["words"]]
        joined = " ".join(flat)
        if "Series Code" in joined or "ABCDE" in joined:
            continue

        permanency = max([t.count("＊") for t in flat if "＊" in t] or [0])
        drying = None
        for t in flat:
            hit = next((ROMAN[ch] for ch in t if ch in ROMAN), None)
            if hit:
                drying = hit
        series = None
        for t in flat:
            if t in SERIES:
                series = t
            elif t in SERIES_WIDE:
                series = SERIES_WIDE[t]
        admix = "N" if any(t == "N" for t in flat) else None

        en, jp = [], []
        for line in lines:
            t = " ".join(w[4] for w in line["words"]).strip()
            if not t or any(ch in t for ch in "＊ⅠⅡⅢⅣ") or REF.match(t.split()[0]):
                continue
            if JP.search(t):
                if not re.fullmatch(r"[A-Z]", t):
                    jp.append(t)
            elif re.fullmatch(r"[A-Z0-9 .'&]+", t):
                en.append(t)

        found.append(
            {
                "x": x0,
                "y": y0,
                "refs": sorted(w[4] for w in c),
                "ref20": next(
                    (w[4] for w in sorted(c, key=lambda w: w[0]) if not w[4].startswith("HH")),
                    c[0][4],
                ),
                "name_en": en[0] if en else "",
                "name_jp": jp[0] if jp else "",
                "permanency": permanency,
                "drying": drying,
                "series": series,
                "admixing": admix,
            }
        )
    return found


def swatch_box(x0, y0):
    """見本の矩形。カタログの見本は全色同じ寸法で、品番の行の左上に揃っている。

    実測（300dpi）: 幅 382px（91.7pt）、高さ 189px（45.4pt）、左端＝品番の x0、
    上端＝品番の y0 - 47.2pt。見本ごとの検出は淡い色で崩れるので、寸法は固定にする。
    """
    px = lambda v: int(round(v * SCALE))
    return (px(x0), px(y0 - 47.2), px(x0) + 382, px(y0 - 47.2) + 189)


def sample_swatch(pixmap, box):
    img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)[:, :, :3]
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    out = {}
    for key, cx in (("pure", 0.25), ("tint", 0.75)):
        sx0 = int(x0 + w * (cx - 0.10))
        sx1 = int(x0 + w * (cx + 0.10))
        sy0 = int(y0 + h * 0.25)
        sy1 = int(y0 + h * 0.75)
        patch = img[sy0:sy1, sx0:sx1].reshape(-1, 3)
        if patch.size == 0:
            return None
        out[key] = [int(v) for v in np.median(patch, axis=0)]
    return out


def parse_swatches(doc):
    out = []
    for pno in (1, 2, 3):
        page = doc[pno]
        pix = page.get_pixmap(dpi=300)
        for item in parse_swatch_page(page):
            box = swatch_box(item["x"], item["y"])
            rgb = sample_swatch(pix, box)
            if rgb is None:
                continue
            item.pop("x")
            item.pop("y")
            item.update(rgb)
            item["page"] = pno + 1
            out.append(item)
    return out


# ---------------------------------------------------------------- まとめ


def main():
    doc = pymupdf.open(PDF)
    table = parse_table([doc[4], doc[5]])
    prices = parse_prices(doc[6])
    swatches = parse_swatches(doc)

    by_ref = {}
    for row in swatches:
        by_ref.setdefault(row["ref20"], []).append(row)

    merged = []
    for row in table:
        sw = by_ref.pop(row["ref20"], None)
        if not sw:
            print("見本なし:", row["ref20"], row["name_jp"])
            continue
        sw = sw[0]
        row = dict(row)
        row["pure_rgb"] = sw["pure"]
        row["tint_rgb"] = sw["tint"]
        row["name_en_chart"] = sw["name_en"]
        row["price_20ml"] = prices["20ml"].get(row["series"]) if row["series"] else None
        merged.append(row)

    for ref, sw in by_ref.items():
        print("表にない見本:", ref, sw[0]["name_jp"], sw[0]["name_en"])

    print("表:", len(table), "見本:", len(swatches), "統合:", len(merged))
    print("価格:", json.dumps(prices, ensure_ascii=False))
    print("20ml価格なし:", [m["name_jp"] for m in merged if not m["price_20ml"]])
    print("透明性なし:", [m["name_jp"] for m in merged if not m["opacity"]])
    print("乾燥日数なし:", [m["name_jp"] for m in merged if not m["drying"]])
    print("顔料なし:", [m["name_jp"] for m in merged if not m["pigments"]])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"prices": prices, "colors": merged}, ensure_ascii=False, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
