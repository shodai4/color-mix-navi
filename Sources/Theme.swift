import SwiftUI

extension Color {
    /// アイボリー〜オフホワイト。紙の白。
    static let paper = Color(red: 0.976, green: 0.973, blue: 0.961)      // #F9F8F5
    /// 写真のまわりの落ち着いた下地。
    static let paperDeep = Color(red: 0.937, green: 0.929, blue: 0.910)
    /// 墨色。
    static let ink = Color(red: 0.102, green: 0.102, blue: 0.106)        // #1A1A1B
    static let inkSoft = Color(red: 0.427, green: 0.416, blue: 0.396)
    static let line = Color(red: 0.878, green: 0.867, blue: 0.843)
    /// 差し色は 1 色だけ。朱。
    static let accent = Color(red: 0.706, green: 0.278, blue: 0.165)     // #B4472A
}

extension LabColor {
    /// 画面上の色。sRGB の範囲に収める。
    var displayColor: Color {
        let rgb = ColorScience.srgb(fromLab: self).clamped
        return Color(.sRGB, red: rgb.r, green: rgb.g, blue: rgb.b)
    }
}

extension Paint {
    var swatchColor: Color {
        Color(.sRGB, red: srgb.r, green: srgb.g, blue: srgb.b)
    }
}
