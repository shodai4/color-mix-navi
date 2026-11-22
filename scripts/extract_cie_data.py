"""CIE の標準データ（等色関数・D65 分光照度）を 10nm 刻みで切り出す。

入力: colour-science のデータセット（CIE の公開データを収録）。次の 2 つを
spectral-data/ に置いてから実行する。

    curl -o spectral-data/cmf.py \
      https://raw.githubusercontent.com/colour-science/colour/master/colour/colorimetry/datasets/cmfs.py
    curl -o spectral-data/illuminants.py \
      https://raw.githubusercontent.com/colour-science/colour/master/colour/colorimetry/datasets/illuminants/sds.py

出力: cmf_1931_2deg.csv, d65.csv（380-730nm / 10nm、36 バンド）
※ 生成済みの CSV をリポジトリに含めてあるので、通常はこのスクリプトを動かさなくてよい。
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

BANDS = list(range(380, 731, 10))
HERE = Path(__file__).resolve().parent
DATA = HERE / "spectral-data"


def block(lines, header, start_at=0):
    """header 行の直後から、同じインデントの閉じ括弧までを取り出す。"""
    for i in range(start_at, len(lines)):
        if header in lines[i] and lines[i].rstrip().endswith("{"):
            out = []
            for line in lines[i + 1:]:
                if line.startswith("    }") or line.startswith("}"):
                    break
                out.append(line)
            return out, i
    raise SystemExit(f"not found: {header}")


def main() -> None:
    cmf_lines = (DATA / "cmf.py").read_text().splitlines()
    ill_lines = (DATA / "illuminants.py").read_text().splitlines()

    cmf_block, _ = block(cmf_lines, '"CIE 1931 2 Degree Standard Observer": {')
    cmf = {}
    for line in cmf_block:
        m = re.match(r"\s*(\d+): \(([^)]+)\),", line)
        if m:
            cmf[int(m.group(1))] = tuple(float(v) for v in m.group(2).split(","))

    ill_block, _ = block(ill_lines, '"D65": {')
    d65 = {}
    for line in ill_block:
        m = re.match(r"\s*(\d+): ([0-9.]+),", line)
        if m:
            d65[int(m.group(1))] = float(m.group(2))

    with (DATA / "cmf_1931_2deg.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lambda", "x_bar", "y_bar", "z_bar"])
        for lam in BANDS:
            w.writerow([lam, *[f"{v:.9f}" for v in cmf[lam]]])

    with (DATA / "d65.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lambda", "spd"])
        for lam in BANDS:
            w.writerow([lam, f"{d65[lam]:.4f}"])

    k = 100.0 / sum(d65[lam] * cmf[lam][1] for lam in BANDS)
    x = k * sum(d65[lam] * cmf[lam][0] for lam in BANDS)
    y = k * sum(d65[lam] * cmf[lam][1] for lam in BANDS)
    z = k * sum(d65[lam] * cmf[lam][2] for lam in BANDS)
    print(f"white -> XYZ {x:.4f} {y:.4f} {z:.4f} (k = {k:.6f})")
    if abs(x - 95.047) > 0.15 or abs(z - 108.883) > 0.2:
        print("WARNING: 10nm 近似の白色点が規格値から外れています", file=sys.stderr)
    print(f"wrote {DATA/'cmf_1931_2deg.csv'} and {DATA/'d65.csv'} ({len(BANDS)} bands)")


if __name__ == "__main__":
    main()
