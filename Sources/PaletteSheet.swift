import SwiftUI

/// カタログ全色から 5 色を選ぶシート。系統で絞り、色名・品番で検索できる。
struct PaletteSheet: View {
    let kind: PaletteKind
    let fiveIDs: [Int]
    let onToggle: (Int) -> Void
    let onClose: () -> Void

    @State private var query = ""
    @State private var group = "すべて"

    private var groups: [String] {
        ["すべて"] + kind.groups
    }

    private var results: [Paint] {
        let needle = query.trimmingCharacters(in: .whitespaces)
        return kind.paints.filter { paint in
            if group != "すべて", paint.meta?.group != group { return false }
            guard !needle.isEmpty else { return true }
            if paint.name.localizedCaseInsensitiveContains(needle) { return true }
            if paint.pigment.localizedCaseInsensitiveContains(needle) { return true }
            if let ref = paint.meta?.ref, ref.localizedCaseInsensitiveContains(needle) { return true }
            return false
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            searchField
                .padding(.horizontal, 18)
                .padding(.bottom, 10)
            groupChips
            Rectangle()
                .fill(Color.line)
                .frame(height: 1)
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(results) { paint in
                        PaintPickRow(paint: paint, order: fiveIDs.firstIndex(of: paint.id)) {
                            onToggle(paint.id)
                        }
                        Rectangle()
                            .fill(Color.line.opacity(0.6))
                            .frame(height: 1)
                            .padding(.leading, 56)
                    }
                }
                .padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.immediately)
        }
        .background(Color.paper.ignoresSafeArea())
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text("色を選ぶ")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Color.ink)
                Text("\(kind.paints.count)色のうち \(fiveIDs.count)色を選んでいます。")
                    .font(.system(size: 10))
                    .foregroundStyle(Color.inkSoft)
            }
            Spacer(minLength: 12)
            Button(action: onClose) {
                Text("閉じる")
                    .font(.system(size: 12))
                    .foregroundStyle(Color.ink)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Capsule().fill(Color.white.opacity(0.7)))
                    .overlay(Capsule().strokeBorder(Color.line, lineWidth: 1))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 18)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 12))
                .foregroundStyle(Color.inkSoft)
            TextField("色名・品番で探す", text: $query)
                .font(.system(size: 12))
                .foregroundStyle(Color.ink)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            if !query.isEmpty {
                Button {
                    query = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(Color.inkSoft)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 9)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.white.opacity(0.7)))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Color.line, lineWidth: 1)
        )
    }

    private var groupChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(groups, id: \.self) { name in
                    Button {
                        group = name
                    } label: {
                        Text(name)
                            .font(.system(size: 11, weight: group == name ? .semibold : .regular))
                            .foregroundStyle(group == name ? Color.ink : Color.inkSoft)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .background(
                                Capsule().fill(group == name ? Color.white.opacity(0.95) : Color.white.opacity(0.3))
                            )
                            .overlay(
                                Capsule().strokeBorder(group == name ? Color.accent.opacity(0.5) : Color.line,
                                                       lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
        }
    }
}

/// 選択シートの 1 行。押すと選ぶ・外す。選んだ順番を丸に出す。
struct PaintPickRow: View {
    let paint: Paint
    let order: Int?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(paint.swatchColor)
                    .frame(width: 30, height: 30)
                    .overlay(
                        RoundedRectangle(cornerRadius: 4, style: .continuous)
                            .strokeBorder(Color.ink.opacity(0.12), lineWidth: 1)
                    )

                VStack(alignment: .leading, spacing: 2) {
                    Text(paint.name)
                        .font(.system(size: 12.5))
                        .foregroundStyle(Color.ink)
                        .lineLimit(1)
                    Text(paint.summaryLine)
                        .font(.system(size: 9.5, design: .monospaced))
                        .foregroundStyle(Color.inkSoft)
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                if let order {
                    Text("\(order + 1)")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Color.paper)
                        .frame(width: 20, height: 20)
                        .background(Circle().fill(Color.ink.opacity(0.78)))
                } else {
                    Circle()
                        .strokeBorder(Color.line, lineWidth: 1)
                        .frame(width: 20, height: 20)
                }
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 9)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(paint.name)
    }
}

/// 1 色の詳細。乾燥日数・透明性・混色の注意・顔料・参考価格をまとめる。
struct PaintDetailSheet: View {
    let paint: Paint

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 14) {
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(paint.swatchColor)
                        .frame(width: 76, height: 76)
                        .overlay(
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .strokeBorder(Color.ink.opacity(0.12), lineWidth: 1)
                        )

                    VStack(alignment: .leading, spacing: 5) {
                        Text(paint.name)
                            .font(.system(size: 18, weight: .medium))
                            .foregroundStyle(Color.ink)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(identityLine)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(Color.inkSoft)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.bottom, 18)

                Rectangle()
                    .fill(Color.line)
                    .frame(height: 1)

                if let meta = paint.meta {
                    detailRow("系統", meta.group)
                    detailRow("シリーズ", meta.series.isEmpty ? "—" : meta.series)
                    detailRow("耐光性", meta.permanencyLabel.isEmpty ? "無印" : meta.permanencyLabel)
                    detailRow("乾燥", meta.dryingLabel)
                    detailRow("透明性", meta.opacity)
                    detailRow("顔料", paint.pigment)
                    if let price = meta.priceLabel {
                        detailRow("20ml 参考価格", price + "（税込）")
                    }
                } else {
                    detailRow("顔料", paint.pigment)
                    detailRow("透明性", paint.opacityLabel)
                    Text("カタログの一覧にない色。色の値は公式 TDS のもの。")
                        .font(.system(size: 10.5))
                        .foregroundStyle(Color.inkSoft)
                        .padding(.top, 12)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let meta = paint.meta, let note = meta.admixingNote {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("混色の注意")
                            .font(.system(size: 10))
                            .foregroundStyle(Color.accent)
                        Text(note)
                            .font(.system(size: 11))
                            .foregroundStyle(Color.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.white.opacity(0.7)))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .strokeBorder(Color.accent.opacity(0.35), lineWidth: 1)
                    )
                    .padding(.top, 16)
                }

                if let meta = paint.meta, meta.metallic {
                    Text("金属色。混色の予測は目安で、実際には光の当たり方で見え方が変わる。")
                        .font(.system(size: 10.5))
                        .foregroundStyle(Color.inkSoft)
                        .padding(.top, 16)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Button {
                    dismiss()
                } label: {
                    Text("閉じる")
                        .font(.system(size: 12))
                        .foregroundStyle(Color.ink)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 11)
                        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.white.opacity(0.7)))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .strokeBorder(Color.line, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .padding(.top, 22)
            }
            .padding(20)
        }
        .background(Color.paper.ignoresSafeArea())
    }

    private var identityLine: String {
        guard let meta = paint.meta else { return paint.pigment }
        return [meta.ref, meta.priceLabel].compactMap { $0 }.joined(separator: " ・ ")
    }

    private func detailRow(_ title: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(title)
                .font(.system(size: 10.5))
                .foregroundStyle(Color.inkSoft)
                .frame(width: 92, alignment: .leading)
            Text(value)
                .font(.system(size: 12))
                .foregroundStyle(Color.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.line.opacity(0.6)).frame(height: 1)
        }
    }
}
