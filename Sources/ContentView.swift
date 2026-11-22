import PhotosUI
import SwiftUI
import UIKit

/// 写真から拾った 1 点。
struct Sample: Identifiable {
    let id = UUID()
    /// 写真パネル内の位置（マーカー表示用）
    let point: CGPoint
    let lab: LabColor
    /// 拾った色。Display P3 のまま保持して、鮮やかな色も潰さない。
    let color: Color
    /// sRGB に直した表記
    let hex: String
}

/// 画面から開くシート。同時に 1 枚だけ出す。
private enum ActiveSheet: Identifiable {
    case palette
    case paint(Paint)

    var id: String {
        switch self {
        case .palette: return "palette"
        case .paint(let paint): return "paint-\(paint.id)"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var pro: ProStore

    @State private var pickerItem: PhotosPickerItem?
    @State private var source: SampledImage?
    @State private var sample: Sample?
    @State private var recipes: [MixRecipe] = []
    @State private var selectedRecipeID: Int?
    @State private var paletteKind: PaletteKind = .oil
    @State private var scope: PaletteScope = .catalogue
    @State private var palettePigments = MixSolver.pigments(for: PaletteData.oil)
    @State private var sheet: ActiveSheet?
    @State private var fiveIDs = PaletteKind.oil.defaultFiveIDs
    @State private var fivePigments = MixSolver.pigments(for: PaletteData.oil.filter { PaletteKind.oil.defaultFiveIDs.contains($0.id) })
    @State private var limitedMode = false
    @State private var finger: CGPoint?
    @State private var isWorking = false
    @State private var loadFailed = false
    @State private var solveToken = 0
    @State private var lastQuickLab: LabColor?
    @State private var lastQuickTime: CFTimeInterval = 0

    // 仕上がりプレビュー
    @State private var kuwaharaLevel: KuwaharaLevel?
    @State private var gamutOn = false
    @State private var preview: PreviewFrame?
    @State private var isPreparingPreview = false
    @State private var showingOriginal = false
    @State private var lut: ColorLUT?
    @State private var lutKey = ""

    var body: some View {
        GeometryReader { proxy in
            let photoHeight = proxy.size.height * 0.60
            VStack(spacing: 0) {
                PhotoPanel(
                    display: activePhoto,
                    sample: sample,
                    finger: finger,
                    size: CGSize(width: proxy.size.width, height: photoHeight),
                    isLoading: isWorking && source == nil,
                    hasPreview: preview != nil,
                    isPreparing: isPreparingPreview,
                    showingOriginal: $showingOriginal,
                    pickerItem: $pickerItem,
                    onDrag: { location in handleDrag(location, in: CGSize(width: proxy.size.width, height: photoHeight)) },
                    onEnd: finishDrag
                )
                .frame(height: photoHeight)

                Rectangle()
                    .fill(Color.line)
                    .frame(height: 1)

                RecipePanel(
                    sample: sample,
                    recipes: recipes,
                    selectedRecipeID: selectedRecipeID,
                    paletteKind: paletteKind,
                    isWorking: isWorking,
                    pro: pro,
                    limitedMode: limitedMode,
                    fiveIDs: fiveIDs,
                    scope: scope,
                    kuwaharaLevel: kuwaharaLevel,
                    gamutOn: gamutOn,
                    isPreparingPreview: isPreparingPreview,
                    onSelectPalette: changePalette,
                    onSelectScope: selectScope,
                    onToggleLimited: toggleLimited,
                    onOpenPalette: { sheet = .palette },
                    onShowPaint: { sheet = .paint($0) },
                    onPreset: applyPreset,
                    onKuwahara: setKuwahara,
                    onGamut: setGamut,
                    onSelectRecipe: { selectedRecipeID = $0 },
                    onPurchase: { Task { await pro.purchase() } }
                )
                .frame(height: proxy.size.height - photoHeight - 1)
            }
        }
        .background(Color.paper.ignoresSafeArea())
        .safeAreaInset(edge: .bottom, spacing: 0) { banner }
        .task(id: previewKey) {
            await rebuildPreview()
        }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            loadPhoto(item)
        }
        .alert("写真を読み込めませんでした", isPresented: $loadFailed) {
            Button("閉じる", role: .cancel) {}
        } message: {
            Text("別の写真でお試しください。HEIF や RAW の一部は読み込めないことがあります。")
        }
        .sheet(item: $sheet) { item in
            switch item {
            case .palette:
                PaletteSheet(kind: paletteKind,
                             fiveIDs: fiveIDs,
                             onToggle: { toggleFive($0) },
                             onClose: { sheet = nil })
            case .paint(let paint):
                PaintDetailSheet(paint: paint)
            }
        }
    }

    // MARK: - 表示する写真

    /// 仕上がりを見ているときは変換後の写真、それ以外は元の写真。
    private var activePhoto: (any PhotoDisplay)? {
        if let preview, !showingOriginal {
            return preview
        }
        return source.map { $0 as any PhotoDisplay }
    }

    private struct PreviewKey: Equatable {
        var imageID: UUID?
        var palette: String
        var five: [Int]
        var kuwahara: Int
        var gamut: Bool
    }

    private var previewKey: PreviewKey {
        PreviewKey(imageID: source?.id,
                   palette: paletteKind.rawValue,
                   five: fiveIDs.sorted(),
                   kuwahara: kuwaharaLevel?.rawValue ?? -1,
                   gamut: gamutOn)
    }

    // MARK: - バナー

    @ViewBuilder
    private var banner: some View {
        if pro.isPro == false {
            VStack(spacing: 0) {
                BannerAdView()
                    .frame(width: 320, height: 50)
                    .padding(.top, 6)
                    .padding(.bottom, 2)
            }
            .frame(maxWidth: .infinity)
            .background(Color.paper)
            .overlay(alignment: .top) {
                Rectangle().fill(Color.line).frame(height: 1)
            }
        }
    }

    // MARK: - スポイト

    private func handleDrag(_ location: CGPoint, in size: CGSize) {
        guard let photo = activePhoto else { return }
        let rect = ImageGeometry.fittedRect(imageSize: photo.displaySize, in: size)
        let pixel = ImageGeometry.pixelPoint(for: location,
                                             in: rect,
                                             imageWidth: photo.width,
                                             imageHeight: photo.height)
        let lab = photo.lab(x: pixel.x, y: pixel.y)

        let marker = CGPoint(x: min(max(location.x, rect.minX), rect.maxX),
                             y: min(max(location.y, rect.minY), rect.maxY))
        let kept = Sample(point: marker,
                          lab: lab,
                          color: photo.displayColor(x: pixel.x, y: pixel.y),
                          hex: ColorScience.srgb(fromLab: lab).hexString)

        finger = location
        sample = kept

        // 指を動かしている間は 2 色までで軽く回す（確定時に 3 色まで探す）。
        // 画素が変わったときだけ、80ms 間隔で。
        let now = CACurrentMediaTime()
        let changed = lastQuickLab != lab
        guard changed, now - lastQuickTime > 0.08 || lastQuickLab == nil else { return }
        lastQuickLab = lab
        lastQuickTime = now

        let quick = MixSolver.solve(target: lab, pigments: searchPigments, maxPaints: 2)
        recipes = quick
        if !quick.contains(where: { $0.id == selectedRecipeID }) {
            selectedRecipeID = quick.first?.id
        }
    }

    private func finishDrag() {
        finger = nil
        lastQuickLab = nil
        guard let sample else { return }
        solve(target: sample.lab, maxPaints: 3)
    }

    // MARK: - 絵具の範囲

    private var searchPigments: [MixPigment] {
        limitedMode ? fivePigments : palettePigments
    }

    private var selectedPaints: [Paint] {
        let ids = Set(fiveIDs)
        return paletteKind.paints.filter { ids.contains($0.id) }
    }

    private func changePalette(_ kind: PaletteKind) {
        guard kind != paletteKind else { return }
        paletteKind = kind
        scope = .catalogue
        palettePigments = MixSolver.pigments(for: kind.paints(in: scope))
        fiveIDs = kind.defaultFiveIDs
        fivePigments = MixSolver.pigments(for: kind.paints.filter { fiveIDs.contains($0.id) })
        recipes = []
        selectedRecipeID = nil
        showingOriginal = false
        if let sample {
            solve(target: sample.lab, maxPaints: 3)
        }
    }

    private func selectScope(_ new: PaletteScope) {
        guard new != scope else { return }
        scope = new
        palettePigments = MixSolver.pigments(for: paletteKind.paints(in: new))
        resolveAgain()
    }

    private func toggleLimited() {
        limitedMode.toggle()
        if !limitedMode {
            gamutOn = false
        }
        showingOriginal = false
        resolveAgain()
    }

    private func toggleFive(_ id: Int) {
        if let index = fiveIDs.firstIndex(of: id) {
            guard fiveIDs.count > 1 else { return }
            fiveIDs.remove(at: index)
        } else if fiveIDs.count < 5 {
            fiveIDs.append(id)
        } else {
            fiveIDs.removeFirst()
            fiveIDs.append(id)
        }
        fivePigments = MixSolver.pigments(for: selectedPaints)
        showingOriginal = false
        resolveAgain()
    }

    private func applyPreset(_ preset: PalettePreset) {
        fiveIDs = preset.ids(in: paletteKind.paints)
        fivePigments = MixSolver.pigments(for: selectedPaints)
        showingOriginal = false
        resolveAgain()
    }

    private func setKuwahara(_ level: KuwaharaLevel?) {
        kuwaharaLevel = level
        showingOriginal = false
    }

    private func setGamut(_ on: Bool) {
        gamutOn = on
        if on && !limitedMode {
            limitedMode = true
            resolveAgain()
        }
        showingOriginal = false
    }

    private func resolveAgain() {
        guard let sample else { return }
        solve(target: sample.lab, maxPaints: 3)
    }

    private func solve(target: LabColor, maxPaints: Int) {
        solveToken += 1
        let token = solveToken
        let pigments = searchPigments
        isWorking = true

        Task.detached(priority: .userInitiated) {
            let result = MixSolver.solve(target: target, pigments: pigments, maxPaints: maxPaints)
            await MainActor.run {
                guard token == solveToken else { return }
                recipes = result
                isWorking = false
                if !result.contains(where: { $0.id == selectedRecipeID }) {
                    selectedRecipeID = result.first?.id
                }
            }
        }
    }

    // MARK: - 5 色プレビュー

    @MainActor
    private func rebuildPreview() async {
        guard let source else {
            preview = nil
            isPreparingPreview = false
            return
        }
        let level = kuwaharaLevel
        let wantGamut = gamutOn
        guard level != nil || wantGamut else {
            preview = nil
            isPreparingPreview = false
            return
        }

        isPreparingPreview = true
        let paints = selectedPaints
        let key = lutCacheKey(for: paints)
        let cached = (key == lutKey) ? lut : nil

        let result = await Task.detached(priority: .userInitiated) { () -> (ColorLUT?, PreviewFrame?) in
            var built = cached
            if wantGamut, built == nil {
                let pigments = MixSolver.pigments(for: paints)
                built = PreviewEngine.buildLUT(samples: MixSolver.gamutSamples(pigments: pigments))
            }
            let frame = PreviewEngine.render(source: source, level: level, lut: wantGamut ? built : nil)
            return (wantGamut ? built : nil, frame)
        }.value

        guard !Task.isCancelled else { return }
        if let built = result.0 {
            lut = built
            lutKey = key
        }
        preview = result.1
        isPreparingPreview = false
    }

    private func lutCacheKey(for paints: [Paint]) -> String {
        paletteKind.rawValue + ":" + paints.map { String($0.id) }.joined(separator: ",")
    }

    // MARK: - 写真の読み込み

    private func loadPhoto(_ item: PhotosPickerItem) {
        isWorking = true
        Task {
            let data = try? await item.loadTransferable(type: Data.self)
            let sampled = data.flatMap { SampledImage(imageData: $0) }
            await MainActor.run {
                isWorking = false
                guard let sampled else {
                    loadFailed = true
                    return
                }
                source = sampled
                sample = nil
                lastQuickLab = nil
                recipes = []
                selectedRecipeID = nil
                finger = nil
                preview = nil
                showingOriginal = false
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(ProStore())
}
