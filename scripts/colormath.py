"""色計算の参照実装（Swift 実装と 1 対 1 で対応させる検証用ミラー）。

Sources/ColorScience.swift と同じ式を Python で書き、数値の正しさを
scripts/verify_color_math.py で確かめるために使う。

- sRGB / Display P3 -> Linear RGB -> XYZ (D65) -> CIELAB
- CIEDE2000 (Sharma et al. 2005)
- Kubelka-Munk 単一定数理論による分光反射率の混合
"""

from __future__ import annotations

import math

# D65 白色点（CIE 1931 2度視野）
XN = 0.95047
YN = 1.0
ZN = 1.08883

# sRGB (D65) -> XYZ
SRGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)

XYZ_TO_SRGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)

# Display P3 (D65) -> XYZ
P3_TO_XYZ = (
    (0.4865709, 0.2656677, 0.1982173),
    (0.2289746, 0.6917385, 0.0792869),
    (0.0000000, 0.0451134, 1.0439444),
)


def srgb_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    c = max(0.0, c)
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def mul(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


def linear_rgb_to_xyz(rgb):
    return mul(SRGB_TO_XYZ, rgb)


def xyz_to_linear_rgb(xyz):
    return mul(XYZ_TO_SRGB, xyz)


def p3_to_xyz(rgb):
    return mul(P3_TO_XYZ, rgb)


def srgb_to_xyz(rgb):
    lin = tuple(srgb_to_linear(c) for c in rgb)
    return linear_rgb_to_xyz(lin)


def _f(t: float) -> float:
    d = 6.0 / 29.0
    if t > d ** 3:
        return t ** (1.0 / 3.0)
    return t / (3.0 * d * d) + 4.0 / 29.0


def _f_inv(t: float) -> float:
    d = 6.0 / 29.0
    if t > d:
        return t ** 3
    return 3.0 * d * d * (t - 4.0 / 29.0)


def xyz_to_lab(xyz):
    fx = _f(xyz[0] / XN)
    fy = _f(xyz[1] / YN)
    fz = _f(xyz[2] / ZN)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def lab_to_xyz(lab):
    fy = (lab[0] + 16.0) / 116.0
    fx = fy + lab[1] / 500.0
    fz = fy - lab[2] / 200.0
    return (_f_inv(fx) * XN, _f_inv(fy) * YN, _f_inv(fz) * ZN)


def xyz_to_srgb(xyz):
    lin = xyz_to_linear_rgb(xyz)
    return tuple(linear_to_srgb(c) for c in lin)


def lab_to_srgb(lab):
    return xyz_to_srgb(lab_to_xyz(lab))


def srgb_to_lab(rgb):
    return xyz_to_lab(srgb_to_xyz(rgb))


def hex_to_srgb(hex_string: str):
    h = hex_string.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def hex_to_lab(hex_string: str):
    return srgb_to_lab(hex_to_srgb(hex_string))


# --- CIEDE2000 -------------------------------------------------------------


def delta_e_2000(lab1, lab2) -> float:
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    c_bar7 = c_bar ** 7
    g = 0.5 * (1.0 - math.sqrt(c_bar7 / (c_bar7 + 25.0 ** 7)))

    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = math.hypot(a1p, b1)
    c2p = math.hypot(a2p, b2)

    h1p = 0.0 if (a1p == 0.0 and b1 == 0.0) else math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = 0.0 if (a2p == 0.0 and b2 == 0.0) else math.degrees(math.atan2(b2, a2p)) % 360.0

    dlp = l2 - l1
    dcp = c2p - c1p

    if c1p * c2p == 0.0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0

    dHp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2.0))

    lp_bar = (l1 + l2) / 2.0
    cp_bar = (c1p + c2p) / 2.0

    if c1p * c2p == 0.0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hp_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hp_bar = (h1p + h2p + 360.0) / 2.0
    else:
        hp_bar = (h1p + h2p - 360.0) / 2.0

    t = (1.0
         - 0.17 * math.cos(math.radians(hp_bar - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * hp_bar))
         + 0.32 * math.cos(math.radians(3.0 * hp_bar + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * hp_bar - 63.0)))

    d_theta = 30.0 * math.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    cp_bar7 = cp_bar ** 7
    r_c = 2.0 * math.sqrt(cp_bar7 / (cp_bar7 + 25.0 ** 7))
    l_term = (lp_bar - 50.0) ** 2
    s_l = 1.0 + (0.015 * l_term) / math.sqrt(20.0 + l_term)
    s_c = 1.0 + 0.045 * cp_bar
    s_h = 1.0 + 0.015 * cp_bar * t
    r_t = -math.sin(math.radians(2.0 * d_theta)) * r_c

    return math.sqrt(
        (dlp / s_l) ** 2
        + (dcp / s_c) ** 2
        + (dHp / s_h) ** 2
        + r_t * (dcp / s_c) * (dHp / s_h)
    )


# --- Kubelka-Munk ----------------------------------------------------------


def reflectance_to_ks(r: float) -> float:
    r = max(1e-4, min(1.0 - 1e-4, r))
    return (1.0 - r) ** 2 / (2.0 * r)


def ks_to_reflectance(ks: float) -> float:
    ks = max(0.0, ks)
    return 1.0 + ks - math.sqrt(ks * ks + 2.0 * ks)


def mix_reflectance(curves, weights):
    bands = len(curves[0])
    mixed = []
    for i in range(bands):
        ks = 0.0
        for curve, w in zip(curves, weights):
            ks += reflectance_to_ks(curve[i]) * w
        mixed.append(ks_to_reflectance(ks))
    return mixed


def mix_two_constant(curves, scatters, weights):
    """2定数 Kubelka-Munk。各絵具の散乱係数 S を分けて扱い、
    K = S * (K/S)、混合は K と S を別々に線形結合する。
    白の散乱が強いことを表現でき、白で淡くした色が暗く転ばない。"""
    bands = len(curves[0])
    s_mix = sum(s * w for s, w in zip(scatters, weights))
    if s_mix <= 0:
        return [1.0] * bands
    mixed = []
    for i in range(bands):
        k_mix = 0.0
        for curve, s, w in zip(curves, scatters, weights):
            k_mix += reflectance_to_ks(curve[i]) * s * w
        mixed.append(ks_to_reflectance(k_mix / s_mix))
    return mixed


def spectral_to_xyz(reflectance, cmf, illuminant, k):
    x = y = z = 0.0
    for r, (xb, yb, zb), s in zip(reflectance, cmf, illuminant):
        w = s * r
        x += w * xb
        y += w * yb
        z += w * zb
    return (k * x, k * y, k * z)
