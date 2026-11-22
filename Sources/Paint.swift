import Foundation

/// 1 本の絵具。分光反射率は 36 バンド、散乱係数は 2定数 Kubelka-Munk 用。
struct Paint: Identifiable, Hashable {
    let id: Int
    let name: String
    /// 顔料記号（PW6 など）。絵具の裏のラベルと同じ表記。
    let pigment: String
    /// 散乱係数（パーマネントホワイト = 1.0）
    let scatter: Double
    let lab: LabColor
    let reflectance: [Double]

    /// RGB（sRGB）。表示と外部連携用に Lab から起こす。
    var srgb: RGBComponents { ColorScience.srgb(fromLab: lab).clamped }

    /// 隠ぺい力の目安。散乱係数から導く。
    var opacityLabel: String {
        if scatter >= 0.5 { return "不透明" }
        if scatter >= 0.2 { return "半透明" }
        return "透明"
    }
}

/// 5 色で作るときの出発点。
struct PalettePreset: Identifiable, Hashable {
    let name: String
    let paintNames: [String]

    var id: String { name }

    func ids(in paints: [Paint]) -> [Int] {
        paints.filter { paintNames.contains($0.name) }.map(\.id)
    }
}

enum PaletteKind: String, CaseIterable, Identifiable {
    case oil
    case watercolor

    var id: String { rawValue }

    var label: String {
        switch self {
        case .oil: return "油絵具"
        case .watercolor: return "透明水彩"
        }
    }

    /// パレットの基準がホルベインであることが、切り替えのすぐ下で分かるようにする。
    var note: String {
        switch self {
        case .oil: return "ホルベインの油絵具 18 色。隠ぺい力のある色で、厚塗りと重ね塗りに。"
        case .watercolor: return "ホルベインの透明水彩 18 色。水で薄めて重ねる前提で。"
        }
    }

    var paints: [Paint] {
        switch self {
        case .oil: return PaletteData.oil
        case .watercolor: return PaletteData.watercolor
        }
    }

    /// 5 色モードのプリセット。
    var presets: [PalettePreset] {
        switch self {
        case .oil:
            return [
                PalettePreset(name: "三原色と白黒",
                              paintNames: ["パーマネントホワイトSF", "カドミウムレッド",
                                           "カドミウムイエロー", "ウルトラマリンディープ",
                                           "アイボリブラック"]),
                PalettePreset(name: "ゾルン風",
                              paintNames: ["パーマネントホワイトSF", "イエローオーカー",
                                           "カドミウムレッド", "バーントシェンナ",
                                           "アイボリブラック"]),
            ]
        case .watercolor:
            return [
                PalettePreset(name: "三原色と白黒",
                              paintNames: ["チタニウムホワイト", "カドミウムレッドライト",
                                           "カドミウムイエローペール", "ウルトラマリンディープ",
                                           "アイボリブラック"]),
                PalettePreset(name: "ゾルン風",
                              paintNames: ["チタニウムホワイト", "イエローオーカー",
                                           "カドミウムレッドライト", "バーントシェンナ",
                                           "アイボリブラック"]),
            ]
        }
    }

    /// 最初に選ばれている 5 色（三原色と白黒）。
    var defaultFiveIDs: [Int] {
        presets.first?.ids(in: paints) ?? paints.prefix(5).map(\.id)
    }
}
