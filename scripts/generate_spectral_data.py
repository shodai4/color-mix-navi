"""CIE 1931 2度視野 + D65 から、分光反射率 -> XYZ の重みを Swift に埋め込む。

X = Σ w_x[i] * R[i]（Y=100 基準）、w = k * S(λ) * x̄(λ)。
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "spectral-data"
ROOT = HERE.parent


def main() -> None:
    cmf, spd = [], []
    with (DATA / "cmf_1931_2deg.csv").open() as fh:
        for row in csv.DictReader(fh):
            cmf.append((float(row["x_bar"]), float(row["y_bar"]), float(row["z_bar"])))
    with (DATA / "d65.csv").open() as fh:
        for row in csv.DictReader(fh):
            spd.append(float(row["spd"]))

    k = 100.0 / sum(s * c[1] for s, c in zip(spd, cmf))
    wx = [k * s * c[0] for s, c in zip(spd, cmf)]
    wy = [k * s * c[1] for s, c in zip(spd, cmf)]
    wz = [k * s * c[2] for s, c in zip(spd, cmf)]

    def fmt(values):
        return ", ".join(f"{v:.6f}" for v in values)

    body = f"""// このファイルは scripts/generate_spectral_data.py が生成します。手で編集しないこと。
//
// CIE 1931 2度標準観測者 x̄(λ), ȳ(λ), z̄(λ) と CIE 標準光源 D65 の分光分布から、
// 分光反射率を XYZ に変換する重み（10nm 刻み 380-730nm、36 バンド、Y=100 基準）。
// w = k * S(λ) * 観測者(λ),  k = 100 / Σ S(λ)ȳ(λ)
// X = Σ wX[i] * R[i],  Y = Σ wY[i] * R[i],  Z = Σ wZ[i] * R[i]

import Foundation

enum SpectralData {{
    static let wavelengths: [Double] = [{fmt([380.0 + 10.0 * i for i in range(len(wx))])}]

    static let weightsX: [Double] = [{fmt(wx)}]

    static let weightsY: [Double] = [{fmt(wy)}]

    static let weightsZ: [Double] = [{fmt(wz)}]
}}
"""
    (ROOT / "Sources" / "SpectralData.swift").write_text(body)
    print("wrote Sources/SpectralData.swift")
    print("白 (R=1) -> XYZ "
          f"{sum(wx):.4f} {sum(wy):.4f} {sum(wz):.4f}")


if __name__ == "__main__":
    main()
