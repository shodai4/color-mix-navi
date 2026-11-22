import Foundation

/// 知覚的な色差を測るための CIELAB 色。
struct LabColor: Hashable {
    var l: Double
    var a: Double
    var b: Double

    var chroma: Double { (a * a + b * b).squareRoot() }
}

/// 色空間を問わない 3 成分（0-1）。
struct RGBComponents: Hashable {
    var r: Double
    var g: Double
    var b: Double

    var clamped: RGBComponents {
        RGBComponents(r: min(max(r, 0), 1), g: min(max(g, 0), 1), b: min(max(b, 0), 1))
    }

    var hexString: String {
        let color = clamped
        return String(
            format: "#%02X%02X%02X",
            Int((color.r * 255).rounded()),
            Int((color.g * 255).rounded()),
            Int((color.b * 255).rounded())
        )
    }
}

/// sRGB / Display P3 / 分光反射率と CIELAB の変換、CIEDE2000、Kubelka-Munk。
///
/// 行列と白色点は CIE の定義値（D65）を使う。分光計算は CIE 1931 2度視野 +
/// D65 を 380-730nm / 10nm で積分した重み（SpectralData）で行う。
enum ColorScience {
    // D65 白色点
    private static let whiteX = 0.95047
    private static let whiteY = 1.0
    private static let whiteZ = 1.08883

    // 6/29 まわり
    private static let epsilon = 216.0 / 24389.0     // (6/29)^3
    private static let kappa = 24389.0 / 27.0        // (29/3)^3

    // MARK: 伝達関数

    static func linearize(_ value: Double) -> Double {
        // sRGB / Display P3 共通の伝達関数
        value <= 0.04045 ? value / 12.92 : pow((value + 0.055) / 1.055, 2.4)
    }

    static func delinearize(_ value: Double) -> Double {
        let c = max(0, value)
        return c <= 0.0031308 ? 12.92 * c : 1.055 * pow(c, 1.0 / 2.4) - 0.055
    }

    // MARK: XYZ

    /// リニア sRGB -> XYZ (D65)
    static func xyz(fromLinearSRGB color: RGBComponents) -> RGBComponents {
        RGBComponents(
            r: 0.4124564 * color.r + 0.3575761 * color.g + 0.1804375 * color.b,
            g: 0.2126729 * color.r + 0.7151522 * color.g + 0.0721750 * color.b,
            b: 0.0193339 * color.r + 0.1191920 * color.g + 0.9503041 * color.b
        )
    }

    /// XYZ (D65) -> リニア sRGB
    static func linearSRGB(fromXYZ xyz: RGBComponents) -> RGBComponents {
        RGBComponents(
            r: 3.2404542 * xyz.r - 1.5371385 * xyz.g - 0.4985314 * xyz.b,
            g: -0.9692660 * xyz.r + 1.8760108 * xyz.g + 0.0415560 * xyz.b,
            b: 0.0556434 * xyz.r - 0.2040259 * xyz.g + 1.0572252 * xyz.b
        )
    }

    /// リニア Display P3 -> XYZ (D65)
    static func xyz(fromLinearP3 color: RGBComponents) -> RGBComponents {
        RGBComponents(
            r: 0.4865709 * color.r + 0.2656677 * color.g + 0.1982173 * color.b,
            g: 0.2289746 * color.r + 0.6917385 * color.g + 0.0792869 * color.b,
            b: 0.0000000 * color.r + 0.0451134 * color.g + 1.0439444 * color.b
        )
    }

    // MARK: CIELAB

    static func lab(fromXYZ xyz: RGBComponents) -> LabColor {
        let fx = pivot(xyz.r / whiteX)
        let fy = pivot(xyz.g / whiteY)
        let fz = pivot(xyz.b / whiteZ)
        return LabColor(l: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz))
    }

    static func xyz(fromLab lab: LabColor) -> RGBComponents {
        let fy = (lab.l + 16) / 116
        let fx = fy + lab.a / 500
        let fz = fy - lab.b / 200
        return RGBComponents(r: inversePivot(fx) * whiteX,
                             g: inversePivot(fy) * whiteY,
                             b: inversePivot(fz) * whiteZ)
    }

    private static func pivot(_ t: Double) -> Double {
        t > epsilon ? cbrt(t) : (kappa * t + 16) / 116
    }

    private static func inversePivot(_ t: Double) -> Double {
        let cube = t * t * t
        return cube > epsilon ? cube : (116 * t - 16) / kappa
    }

    static func lab(fromSRGB color: RGBComponents) -> LabColor {
        let linear = RGBComponents(r: linearize(color.r), g: linearize(color.g), b: linearize(color.b))
        return lab(fromXYZ: xyz(fromLinearSRGB: linear))
    }

    static func srgb(fromLab lab: LabColor) -> RGBComponents {
        let linear = linearSRGB(fromXYZ: xyz(fromLab: lab))
        return RGBComponents(r: delinearize(linear.r), g: delinearize(linear.g), b: delinearize(linear.b))
    }

    /// 写真の画素（Display P3）から CIELAB へ。鮮やかな色を丸めずに測る。
    static func lab(fromDisplayP3 color: RGBComponents) -> LabColor {
        let linear = RGBComponents(r: linearize(color.r), g: linearize(color.g), b: linearize(color.b))
        return lab(fromXYZ: xyz(fromLinearP3: linear))
    }

    // MARK: 分光反射率

    /// 分光反射率（36 バンド）から CIELAB。Y=100 基準の重みを 0-1 に戻して渡す。
    static func lab(fromReflectance reflectance: [Double]) -> LabColor {
        var x = 0.0
        var y = 0.0
        var z = 0.0
        let count = SpectralData.weightsX.count
        for index in 0..<count {
            let r = reflectance[index]
            x += r * SpectralData.weightsX[index]
            y += r * SpectralData.weightsY[index]
            z += r * SpectralData.weightsZ[index]
        }
        return lab(fromXYZ: RGBComponents(r: x / 100, g: y / 100, b: z / 100))
    }

    /// Kubelka-Munk: K/S 比から反射率。R = 1 + K/S - sqrt((K/S)^2 + 2K/S)
    static func reflectance(fromKS ratio: Double) -> Double {
        let k = max(0, ratio)
        return 1 + k - (k * k + 2 * k).squareRoot()
    }

    /// Kubelka-Munk: 反射率から K/S 比。K/S = (1-R)^2 / 2R
    static func ks(fromReflectance reflectance: Double) -> Double {
        let r = min(max(reflectance, 0.0001), 0.9999)
        return (1 - r) * (1 - r) / (2 * r)
    }

    // MARK: 色差

    /// CIEDE2000（Sharma et al. 2005 の実装に沿う）。
    static func deltaE2000(_ first: LabColor, _ second: LabColor) -> Double {
        let c1 = first.chroma
        let c2 = second.chroma
        let cBar = (c1 + c2) / 2
        let cBar7 = pow(cBar, 7)
        let g = 0.5 * (1 - (cBar7 / (cBar7 + pow(25, 7))).squareRoot())

        let a1p = (1 + g) * first.a
        let a2p = (1 + g) * second.a
        let c1p = (a1p * a1p + first.b * first.b).squareRoot()
        let c2p = (a2p * a2p + second.b * second.b).squareRoot()

        let h1p = hueAngle(a: a1p, b: first.b)
        let h2p = hueAngle(a: a2p, b: second.b)

        let dLp = second.l - first.l
        let dCp = c2p - c1p

        var dhp = 0.0
        if c1p * c2p != 0 {
            let difference = h2p - h1p
            if abs(difference) <= 180 {
                dhp = difference
            } else if difference > 180 {
                dhp = difference - 360
            } else {
                dhp = difference + 360
            }
        }
        let dHp = 2 * (c1p * c2p).squareRoot() * sin(radians(dhp / 2))

        let lBar = (first.l + second.l) / 2
        let cpBar = (c1p + c2p) / 2

        var hpBar = 0.0
        if c1p * c2p == 0 {
            hpBar = h1p + h2p
        } else if abs(h1p - h2p) <= 180 {
            hpBar = (h1p + h2p) / 2
        } else if h1p + h2p < 360 {
            hpBar = (h1p + h2p + 360) / 2
        } else {
            hpBar = (h1p + h2p - 360) / 2
        }

        let t = 1
            - 0.17 * cos(radians(hpBar - 30))
            + 0.24 * cos(radians(2 * hpBar))
            + 0.32 * cos(radians(3 * hpBar + 6))
            - 0.20 * cos(radians(4 * hpBar - 63))

        let dTheta = 30 * exp(-pow((hpBar - 275) / 25, 2))
        let cpBar7 = pow(cpBar, 7)
        let rc = 2 * (cpBar7 / (cpBar7 + pow(25, 7))).squareRoot()
        let lTerm = (lBar - 50) * (lBar - 50)
        let sl = 1 + (0.015 * lTerm) / (20 + lTerm).squareRoot()
        let sc = 1 + 0.045 * cpBar
        let sh = 1 + 0.015 * cpBar * t
        let rt = -sin(radians(2 * dTheta)) * rc

        let termL = dLp / sl
        let termC = dCp / sc
        let termH = dHp / sh
        return (termL * termL + termC * termC + termH * termH + rt * termC * termH).squareRoot()
    }

    private static func hueAngle(a: Double, b: Double) -> Double {
        if a == 0 && b == 0 { return 0 }
        let degrees = atan2(b, a) * 180 / .pi
        return degrees >= 0 ? degrees : degrees + 360
    }

    private static func radians(_ degrees: Double) -> Double {
        degrees * .pi / 180
    }
}
