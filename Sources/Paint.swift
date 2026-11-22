import Foundation

/// カタログ（ホルベイン公式・2026年11月2日現在）の 1 色ぶんの情報。
struct PaintMeta: Hashable {
    /// 20ml（6号チューブ）の品番。単色の掲載がない色は nil。
    let ref: String?
    /// 系統（赤・橙・黄・緑・青・紫・茶黒・灰・金銀・アンティーク・白）
    let group: String
    /// 価格のシリーズ記号（A〜L）
    let series: String
    /// 耐光性（＊の数、0〜4）
    let permanency: Int
    /// 乾燥所要日数（1: 2日前後 〜 4: 5日前後）
    let drying: Int
    /// 透明性（透明・半透明・半不透明・不透明）
    let opacity: String
    /// 混色記号。N は硫化物を含む色。
    let admixing: String?
    /// 20ml の税込参考価格。0 は掲載なし。
    let price20: Int
    /// 金属色（ゴールド・シルバー）。混色の予測は目安。
    let metallic: Bool

    /// 乾燥所要日数の目安。
    var dryingLabel: String {
        switch drying {
        case 1: return "2日前後"
        case 2: return "3日前後"
        case 3: return "4日前後"
        default: return "5日前後"
        }
    }

    /// 耐光性の記号。0 は無印。
    var permanencyLabel: String {
        String(repeating: "＊", count: max(0, min(4, permanency)))
    }

    /// 混色の注意。N 印は硫化物を含む色で、鉛系の白（シルバーホワイト）との混色を避ける。
    var admixingNote: String? {
        guard admixing == "N" else { return nil }
        return "硫化物を含む色。鉛系の白（シルバーホワイト）との混色は避ける。"
    }

    /// 20ml の参考価格（税込）。
    var priceLabel: String? {
        guard price20 > 0 else { return nil }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.groupingSeparator = ","
        let text = formatter.string(from: NSNumber(value: price20)) ?? "\(price20)"
        return "¥\(text)"
    }
}

/// 1 本の絵具。分光反射率は 36 バンド、散乱係数は 2定数 Kubelka-Munk 用。
struct Paint: Identifiable, Hashable {
    let id: Int
    let name: String
    /// 顔料記号（PW6 など）。絵具の裏のラベルと同じ表記。
    let pigment: String
    /// 散乱係数（パーマネントホワイトSF = 1.0）
    let scatter: Double
    let lab: LabColor
    let reflectance: [Double]
    /// 従来の定番 18 色に含まれるか。
    let classic: Bool
    /// カタログの情報。カタログ外の色は nil。
    let meta: PaintMeta?

    init(id: Int,
         name: String,
         pigment: String,
         scatter: Double,
         lab: LabColor,
         reflectance: [Double],
         classic: Bool = false,
         meta: PaintMeta? = nil) {
        self.id = id
        self.name = name
        self.pigment = pigment
        self.scatter = scatter
        self.lab = lab
        self.reflectance = reflectance
        self.classic = classic
        self.meta = meta
    }

    /// RGB（sRGB）。表示と外部連携用に Lab から起こす。
    var srgb: RGBComponents { ColorScience.srgb(fromLab: lab).clamped }

    /// 隠ぺい力の目安。カタログの透明性があればそれを使う。
    var opacityLabel: String {
        if let meta { return meta.opacity }
        if scatter >= 0.5 { return "不透明" }
        if scatter >= 0.2 { return "半透明" }
        return "透明"
    }

    /// 一覧の 1 行に添える補足（品番・乾燥・透明性）。
    var summaryLine: String {
        guard let meta else { return pigment }
        return [meta.ref, meta.dryingLabel, meta.opacity].compactMap { $0 }.joined(separator: " ・ ")
    }

    var isSulfide: Bool { meta?.admixing == "N" }
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

/// 配合を探しにいく範囲。
enum PaletteScope: String, CaseIterable, Identifiable {
    case catalogue
    case classic

    var id: String { rawValue }

    var label: String {
        switch self {
        case .catalogue: return "全色"
        case .classic: return "定番18色"
        }
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
        case .oil: return "ホルベインの油絵具 \(PaletteData.oil.count) 色。カタログ全色から、乾燥日数と透明性つきで選べる。"
        case .watercolor: return "ホルベインの透明水彩 18 色。水で薄めて重ねる前提で。"
        }
    }

    var paints: [Paint] {
        switch self {
        case .oil: return PaletteData.oil
        case .watercolor: return PaletteData.watercolor
        }
    }

    /// カタログに並ぶ順の系統。選択シートの見出しに使う。
    var groups: [String] {
        var order: [String] = []
        for paint in paints {
            guard let group = paint.meta?.group else { continue }
            if !order.contains(group) { order.append(group) }
        }
        return order
    }

    /// 定番 18 色（従来のパレット）。
    var classicPaints: [Paint] {
        let classic = paints.filter(\.classic)
        return classic.isEmpty ? paints : classic
    }

    func paints(in scope: PaletteScope) -> [Paint] {
        switch scope {
        case .catalogue: return paints
        case .classic: return classicPaints
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
