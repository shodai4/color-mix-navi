import SwiftUI

/// 下部の比較・レシピエリア。広告に隠れないよう下に余白を確保してスクロールする。
struct RecipePanel: View {
    let sample: Sample?
    let recipes: [MixRecipe]
    let selectedRecipeID: Int?
    let paletteKind: PaletteKind
    let isWorking: Bool
    @ObservedObject var pro: ProStore
    let limitedMode: Bool
    let fiveIDs: [Int]
    let kuwaharaLevel: KuwaharaLevel?
    let gamutOn: Bool
    let isPreparingPreview: Bool
    let onSelectPalette: (PaletteKind) -> Void
    let onToggleLimited: () -> Void
    let onToggleFive: (Int) -> Void
    let onPreset: (PalettePreset) -> Void
    let onKuwahara: (KuwaharaLevel?) -> Void
    let onGamut: (Bool) -> Void
    let onSelectRecipe: (Int) -> Void
    let onPurchase: () -> Void

    private var selectedRecipe: MixRecipe? {
        if let selectedRecipeID, let recipe = recipes.first(where: { $0.id == selectedRecipeID }) {
            return recipe
        }
        return recipes.first
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if let sample {
                    comparison(sample)
                } else {
                    guide
                }

                paletteTabs
                    .padding(.top, 18)

                divider
                    .padding(.top, 16)

                fiveSection
                    .padding(.top, 16)

                divider
                    .padding(.top, 16)

                previewSection
                    .padding(.top, 16)

                if sample != nil {
                    recipesSection
                        .padding(.top, 18)
                }

                proFooter
                    .padding(.top, 22)
            }
            .padding(.horizontal, 22)
            .padding(.top, 16)
            .padding(.bottom, 64)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(Color.paper)
    }

    private var divider: some View {
        Rectangle()
            .fill(Color.line)
            .frame(height: 1)
    }

    // MARK: - 案内

    private var guide: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("拾った色と、作る配合")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color.ink)
            Text("写真の上で指を置くと、その場所の色に近い配合を 3 案まで探します。絵具の切り替えは下の 2 つから。")
                .font(.system(size: 11))
                .foregroundStyle(Color.inkSoft)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - 色の比較

    private func comparison(_ sample: Sample) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 14) {
                swatch(title: "写真の色", color: sample.color, caption: sample.hex)

                Rectangle()
                    .fill(Color.line)
                    .frame(width: 1, height: 92)

                swatch(title: "配合の予測",
                       color: selectedRecipe?.lab.displayColor ?? Color.white,
                       caption: selectedRecipe.map { String(format: "ΔE %.1f", $0.deltaE) } ?? " ")
            }

            if let recipe = selectedRecipe {
                Text(matchNote(recipe.deltaE))
                    .font(.system(size: 11))
                    .foregroundStyle(Color.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if sample.lab.l < 15 {
                Text("影の色を拾っています。明るい側で拾い直すと、配合が安定します。")
                    .font(.system(size: 10.5))
                    .foregroundStyle(Color.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func swatch(title: String, color: Color, caption: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 10))
                .foregroundStyle(Color.inkSoft)
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(color)
                .frame(height: 56)
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(Color.ink.opacity(0.08), lineWidth: 1)
                )
            Text(caption)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(Color.inkSoft)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func matchNote(_ deltaE: Double) -> String {
        let value = String(format: "%.1f", deltaE)
        switch deltaE {
        case ..<1.5:
            return "色差 ΔE \(value)。肉眼ではほぼ同じ色。"
        case ..<3:
            return "色差 ΔE \(value)。並べても見分けにくい差。"
        case ..<6:
            return "色差 ΔE \(value)。近い色だが、少し濁る。"
        case ..<12:
            return "色差 ΔE \(value)。明度か彩度がずれる。混ぜる量を変えてみる。"
        default:
            return "色差 ΔE \(value)。この範囲では届きにくい色。近い別案を見る。"
        }
    }

    // MARK: - 絵具の切り替え

    private var paletteTabs: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 20) {
                ForEach(PaletteKind.allCases) { kind in
                    Button {
                        onSelectPalette(kind)
                    } label: {
                        VStack(spacing: 5) {
                            Text(kind.label)
                                .font(.system(size: 13, weight: kind == paletteKind ? .semibold : .regular))
                                .foregroundStyle(kind == paletteKind ? Color.ink : Color.inkSoft)
                            Rectangle()
                                .fill(kind == paletteKind ? Color.accent : Color.clear)
                                .frame(height: 1)
                        }
                        .fixedSize()
                    }
                    .buttonStyle(.plain)
                }
                Spacer(minLength: 0)
            }

            Text(paletteKind.note)
                .font(.system(size: 10))
                .foregroundStyle(Color.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - 5 色で作る

    private var fiveSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center) {
                Text("5色で作る")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(1)
                    .foregroundStyle(Color.ink)

                Spacer(minLength: 8)

                chipButton(title: limitedMode ? "オン" : "オフ", isOn: limitedMode) {
                    onToggleLimited()
                }
            }

            Text("18 色のうち 5 色を選ぶと、その 5 色だけで配合を探します。")
                .font(.system(size: 10.5))
                .foregroundStyle(Color.inkSoft)
                .fixedSize(horizontal: false, vertical: true)

            if limitedMode {
                HStack(spacing: 10) {
                    ForEach(paletteKind.presets) { preset in
                        Button {
                            onPreset(preset)
                        } label: {
                            Text(preset.name)
                                .font(.system(size: 10.5))
                                .foregroundStyle(Color.ink.opacity(0.86))
                                .padding(.horizontal, 9)
                                .padding(.vertical, 5)
                                .background(Capsule().fill(Color.white.opacity(0.6)))
                                .overlay(Capsule().strokeBorder(Color.line, lineWidth: 1))
                        }
                        .buttonStyle(.plain)
                    }

                    Spacer(minLength: 4)

                    Text("\(fiveIDs.count)/5")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(fiveIDs.count == 5 ? Color.inkSoft : Color.accent)
                }

                LazyVGrid(columns: [GridItem(.flexible(), spacing: 10),
                                    GridItem(.flexible(), spacing: 10),
                                    GridItem(.flexible(), spacing: 10)],
                          spacing: 8) {
                    ForEach(paletteKind.paints) { paint in
                        paintCell(paint)
                    }
                }
                .padding(.top, 2)
            }
        }
    }

    private func paintCell(_ paint: Paint) -> some View {
        let order = fiveIDs.firstIndex(of: paint.id)
        return Button {
            onToggleFive(paint.id)
        } label: {
            HStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(paint.swatchColor)
                    .frame(width: 14, height: 14)
                    .overlay(
                        RoundedRectangle(cornerRadius: 2, style: .continuous)
                            .strokeBorder(Color.ink.opacity(0.12), lineWidth: 1)
                    )

                Text(paint.name)
                    .font(.system(size: 10))
                    .foregroundStyle(order == nil ? Color.inkSoft : Color.ink)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)

                Spacer(minLength: 0)

                if let order {
                    Text("\(order + 1)")
                        .font(.system(size: 8, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Color.paper)
                        .frame(width: 14, height: 14)
                        .background(Circle().fill(Color.ink.opacity(0.7)))
                }
            }
            .padding(.horizontal, 5)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 5, style: .continuous)
                    .fill(order == nil ? Color.white.opacity(0.28) : Color.white.opacity(0.72))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 5, style: .continuous)
                    .strokeBorder(order == nil ? Color.line : Color.accent.opacity(0.5), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(paint.name)
    }

    // MARK: - 仕上がり

    private var previewSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center) {
                Text("仕上がり")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(1)
                    .foregroundStyle(Color.ink)

                Spacer(minLength: 8)

                if isPreparingPreview {
                    Text("作成中")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.inkSoft)
                }
            }

            Text("写真全体を、選んだ 5 色で塗ったらどう見えるか。元の写真とは写真の左上で切り替えられます。")
                .font(.system(size: 10.5))
                .foregroundStyle(Color.inkSoft)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                chipButton(title: "面化", isOn: kuwaharaLevel != nil) {
                    onKuwahara(kuwaharaLevel == nil ? .medium : nil)
                }
                chipButton(title: "5色再現", isOn: gamutOn) {
                    onGamut(!gamutOn)
                }
                Spacer(minLength: 0)
            }

            if kuwaharaLevel != nil {
                HStack(spacing: 6) {
                    Text("面の大きさ")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.inkSoft)

                    ForEach(KuwaharaLevel.allCases) { level in
                        Button {
                            onKuwahara(level)
                        } label: {
                            Text(level.label)
                                .font(.system(size: 10, weight: kuwaharaLevel == level ? .semibold : .regular))
                                .foregroundStyle(kuwaharaLevel == level ? Color.ink : Color.inkSoft)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(
                                    Capsule().fill(kuwaharaLevel == level ? Color.white.opacity(0.8) : Color.clear)
                                )
                                .overlay(
                                    Capsule().strokeBorder(kuwaharaLevel == level ? Color.line : Color.clear,
                                                           lineWidth: 1)
                                )
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            Text("面化は細部を省いて色の塊にします。5色再現と重ねると、面のまま 5 色の範囲に収まります。")
                .font(.system(size: 10))
                .foregroundStyle(Color.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func chipButton(title: String, isOn: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 11, weight: isOn ? .semibold : .regular))
                .foregroundStyle(isOn ? Color.ink : Color.inkSoft)
                .padding(.horizontal, 11)
                .padding(.vertical, 6)
                .background(
                    Capsule().fill(isOn ? Color.white.opacity(0.9) : Color.white.opacity(0.3))
                )
                .overlay(
                    Capsule().strokeBorder(isOn ? Color.accent.opacity(0.55) : Color.line, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }

    // MARK: - レシピ

    private var recipesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("配合案")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(1)
                    .foregroundStyle(Color.ink)

                Spacer(minLength: 8)

                Text(recipesNote)
                    .font(.system(size: 10))
                    .foregroundStyle(Color.inkSoft)
            }

            ForEach(Array(recipes.enumerated()), id: \.element.id) { index, recipe in
                RecipeCard(index: index + 1,
                           recipe: recipe,
                           selected: recipe.id == selectedRecipeID) {
                    onSelectRecipe(recipe.id)
                }
            }

            if recipes.isEmpty && !isWorking {
                Text("この色に近い配合は見つかりませんでした。写真の別の場所で拾い直してみてください。")
                    .font(.system(size: 11))
                    .foregroundStyle(Color.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var recipesNote: String {
        if isWorking {
            return "計算中"
        }
        return limitedMode ? "5色の範囲" : "比率は容量比"
    }

    // MARK: - Pro

    @ViewBuilder
    private var proFooter: some View {
        if let product = pro.product, !pro.isPro {
            Button(action: onPurchase) {
                HStack(spacing: 10) {
                    Text("Pro")
                        .font(.system(size: 11, weight: .semibold))
                        .tracking(1)
                    Text("広告を消す")
                        .font(.system(size: 11))
                    Spacer(minLength: 8)
                    Text(product.displayPrice)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Color.inkSoft)
                }
                .foregroundStyle(Color.ink)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.white.opacity(0.55)))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Color.line, lineWidth: 1)
                )
            }
            .buttonStyle(.plain)
            .disabled(pro.isPurchasing)
        } else if let message = pro.message {
            Text(message)
                .font(.system(size: 10.5))
                .foregroundStyle(Color.inkSoft)
        }
    }
}

/// 1 案ぶん。水平分割バーと、絵具ごとの比率。
struct RecipeCard: View {
    let index: Int
    let recipe: MixRecipe
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Text(String(format: "%02d", index))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(Color.inkSoft)

                    RecipeBar(entries: recipe.entries)

                    Text(String(format: "ΔE %.1f", recipe.deltaE))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(Color.inkSoft)
                }

                VStack(alignment: .leading, spacing: 4) {
                    ForEach(recipe.entries) { entry in
                        HStack(spacing: 6) {
                            Circle()
                                .fill(entry.paint.swatchColor)
                                .frame(width: 7, height: 7)
                            Text(entry.paint.name)
                                .font(.system(size: 11))
                                .foregroundStyle(Color.ink)
                            Text(entry.paint.pigment)
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundStyle(Color.inkSoft)
                            Spacer(minLength: 8)
                            Text("\(entry.percent)%")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(Color.ink)
                        }
                    }
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color.white.opacity(selected ? 0.9 : 0.42))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(selected ? Color.accent.opacity(0.55) : Color.line, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

/// 絵具色を配合比で並べた水平バー。
struct RecipeBar: View {
    let entries: [MixEntry]

    var body: some View {
        GeometryReader { proxy in
            HStack(spacing: 0) {
                ForEach(entries) { entry in
                    Rectangle()
                        .fill(entry.paint.swatchColor)
                        .frame(width: max(2, proxy.size.width * CGFloat(entry.fraction)))
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 2, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .strokeBorder(Color.ink.opacity(0.1), lineWidth: 1)
            )
        }
        .frame(height: 12)
    }
}
