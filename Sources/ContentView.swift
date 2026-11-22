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

struct ContentView: View {
    @EnvironmentObject private var pro: ProStore

    @State private var pickerItem: PhotosPickerItem?
    @State private var source: SampledImage?
    @State private var sample: Sample?
    @State private var recipes: [MixRecipe] = []
    @State private var selectedRecipeID: Int?
    @State private var paletteKind: PaletteKind = .oil
    @State private var pigments = MixSolver.pigments(for: PaletteData.oil)
    @State private var finger: CGPoint?
    @State private var isWorking = false
    @State private var loadFailed = false
    @State private var solveToken = 0

    var body: some View {
        GeometryReader { proxy in
            let photoHeight = proxy.size.height * 0.60
            VStack(spacing: 0) {
                PhotoPanel(
                    source: source,
                    sample: sample,
                    finger: finger,
                    size: CGSize(width: proxy.size.width, height: photoHeight),
                    isLoading: isWorking && source == nil,
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
                    onSelectPalette: changePalette,
                    onSelectRecipe: { selectedRecipeID = $0 },
                    onPurchase: { Task { await pro.purchase() } }
                )
                .frame(height: proxy.size.height - photoHeight - 1)
            }
        }
        .background(Color.paper.ignoresSafeArea())
        .safeAreaInset(edge: .bottom, spacing: 0) { banner }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            loadPhoto(item)
        }
        .alert("写真を読み込めませんでした", isPresented: $loadFailed) {
            Button("閉じる", role: .cancel) {}
        } message: {
            Text("別の写真でお試しください。HEIF や RAW の一部は読み込めないことがあります。")
        }
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
        guard let source else { return }
        let rect = ImageGeometry.fittedRect(imageSize: source.displaySize, in: size)
        let pixel = ImageGeometry.pixelPoint(for: location,
                                             in: rect,
                                             imageWidth: source.width,
                                             imageHeight: source.height)
        let lab = source.lab(x: pixel.x, y: pixel.y)

        let marker = CGPoint(x: min(max(location.x, rect.minX), rect.maxX),
                             y: min(max(location.y, rect.minY), rect.maxY))
        let kept = Sample(point: marker,
                          lab: lab,
                          color: source.displayColor(x: pixel.x, y: pixel.y),
                          hex: ColorScience.srgb(fromLab: lab).hexString)

        finger = location
        sample = kept

        // 指を動かしている間は 2 色までで軽く回す（確定時に 3 色まで探す）
        let quick = MixSolver.solve(target: lab, pigments: pigments, maxPaints: 2)
        recipes = quick
        if !quick.contains(where: { $0.id == selectedRecipeID }) {
            selectedRecipeID = quick.first?.id
        }
    }

    private func finishDrag() {
        finger = nil
        guard let sample else { return }
        solve(target: sample.lab, maxPaints: 3)
    }

    private func changePalette(_ kind: PaletteKind) {
        guard kind != paletteKind else { return }
        paletteKind = kind
        pigments = MixSolver.pigments(for: kind.paints)
        recipes = []
        selectedRecipeID = nil
        if let sample {
            solve(target: sample.lab, maxPaints: 3)
        }
    }

    private func solve(target: LabColor, maxPaints: Int) {
        solveToken += 1
        let token = solveToken
        let pigments = self.pigments
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

    private func loadPhoto(_ item: PhotosPickerItem) {
        isWorking = true
        Task {
            let data = try? await item.loadTransferable(type: Data.self)
            let decoded = data.flatMap { UIImage(data: $0) }
            let sampled = decoded.flatMap { SampledImage(uiImage: $0) }
            await MainActor.run {
                isWorking = false
                guard let sampled else {
                    loadFailed = true
                    return
                }
                source = sampled
                sample = nil
                recipes = []
                selectedRecipeID = nil
                finger = nil
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(ProStore())
}
