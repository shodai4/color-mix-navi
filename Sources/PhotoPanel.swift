import CoreGraphics
import PhotosUI
import SwiftUI

/// 上部の写真エリア。ドラッグで色を拾い、指の 40pt 上にルーペを出す。
struct PhotoPanel: View {
    let display: (any PhotoDisplay)?
    let sample: Sample?
    let finger: CGPoint?
    let size: CGSize
    let isLoading: Bool
    let hasPreview: Bool
    let isPreparing: Bool
    @Binding var showingOriginal: Bool
    @Binding var pickerItem: PhotosPickerItem?
    let onDrag: (CGPoint) -> Void
    let onEnd: () -> Void

    private static let space = "photoPanel"
    private let loupeDiameter: CGFloat = 108

    var body: some View {
        ZStack {
            Color.paperDeep

            if let display {
                let rect = ImageGeometry.fittedRect(imageSize: display.displaySize, in: size)

                Image(decorative: display.displayImage, scale: 1)
                    .resizable()
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
                    .gesture(
                        DragGesture(minimumDistance: 0, coordinateSpace: .named(Self.space))
                            .onChanged { value in onDrag(value.location) }
                            .onEnded { _ in onEnd() }
                    )

                if let sample {
                    marker(sample)
                }

                loupe(display: display, rect: rect)
                topBar
            } else {
                emptyState
            }
        }
        .frame(width: size.width, height: size.height)
        .clipped()
        .contentShape(Rectangle())
        .coordinateSpace(.named(Self.space))
    }

    // MARK: - 仕上がりの切り替え

    private var topBar: some View {
        VStack {
            HStack(alignment: .top) {
                if hasPreview {
                    Button {
                        showingOriginal.toggle()
                    } label: {
                        Text(showingOriginal ? "仕上がりを見る" : "元の写真を見る")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(Color.ink.opacity(0.82))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(Capsule().fill(Color.paper.opacity(0.86)))
                            .overlay(Capsule().strokeBorder(Color.line, lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                } else if isPreparing {
                    Text("仕上がりを作成中")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.inkSoft)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(Capsule().fill(Color.paper.opacity(0.86)))
                }

                Spacer(minLength: 8)

                replacePicker
            }

            if showingOriginal && hasPreview {
                Text(isPreparing ? "処理しています" : "元の写真を表示中")
                    .font(.system(size: 10))
                    .foregroundStyle(Color.inkSoft)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(Color.paper.opacity(0.8)))
                    .padding(.top, 6)
            }

            Spacer()
        }
        .padding(12)
    }

    // MARK: - 写真がないとき

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "viewfinder")
                .font(.system(size: 30, weight: .ultraLight))
                .foregroundStyle(Color.inkSoft)

            VStack(spacing: 6) {
                Text("写真から色を拾う")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Color.ink)
                Text("作りたい色のところで、写真の上に指を置く。")
                    .font(.system(size: 11.5))
                    .foregroundStyle(Color.inkSoft)
            }

            PhotosPicker(selection: $pickerItem, matching: .images, photoLibrary: .shared()) {
                HStack(spacing: 6) {
                    Text("写真を選ぶ")
                        .font(.system(size: 13, weight: .medium))
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9, weight: .semibold))
                }
                .foregroundStyle(Color.ink)
                .padding(.horizontal, 18)
                .padding(.vertical, 11)
                .background(Capsule().fill(Color.white.opacity(0.72)))
                .overlay(Capsule().strokeBorder(Color.line, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .disabled(isLoading)

            if isLoading {
                ProgressView().controlSize(.small)
            }
        }
        .padding(.horizontal, 32)
    }

    // MARK: - 写真を替える

    private var replacePicker: some View {
        PhotosPicker(selection: $pickerItem, matching: .images, photoLibrary: .shared()) {
            Text("写真を替える")
                .font(.system(size: 11))
                .foregroundStyle(Color.ink.opacity(0.78))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Capsule().fill(Color.paper.opacity(0.84)))
        }
        .buttonStyle(.plain)
    }

    // MARK: - 拾った位置

    private func marker(_ sample: Sample) -> some View {
        Circle()
            .fill(sample.color)
            .frame(width: 14, height: 14)
            .overlay(Circle().strokeBorder(Color.white.opacity(0.95), lineWidth: 1.5))
            .shadow(color: Color.ink.opacity(0.25), radius: 2)
            .position(sample.point)
            .allowsHitTesting(false)
    }

    // MARK: - ルーペ

    @ViewBuilder
    private func loupe(display: any PhotoDisplay, rect: CGRect) -> some View {
        if let finger {
            let pixel = ImageGeometry.pixelPoint(for: finger,
                                                 in: rect,
                                                 imageWidth: display.width,
                                                 imageHeight: display.height)
            let radius = loupeDiameter / 2
            let x = min(max(finger.x, radius + 8), max(size.width - radius - 8, radius + 8))
            let y = max(finger.y - 40 - radius, radius + 8)

            Magnifier(
                image: display.crop(centerX: pixel.x, centerY: pixel.y, side: 9),
                hex: ColorScience.srgb(fromLab: display.lab(x: pixel.x, y: pixel.y)).hexString,
                diameter: loupeDiameter
            )
            .position(x: x, y: y)
            .allowsHitTesting(false)
        }
    }
}

/// 9×9 画素の拡大図と十字照準。
private struct Magnifier: View {
    let image: CGImage?
    let hex: String
    let diameter: CGFloat

    var body: some View {
        ZStack {
            if let image {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .interpolation(.none)
                    .scaledToFill()
                    .frame(width: diameter, height: diameter)
                    .clipped()
            } else {
                Color.ink.opacity(0.12)
            }

            Rectangle()
                .fill(Color.ink.opacity(0.5))
                .frame(width: 1, height: 26)
            Rectangle()
                .fill(Color.ink.opacity(0.5))
                .frame(width: 26, height: 1)
            Circle()
                .fill(Color.white)
                .frame(width: 5, height: 5)
            Circle()
                .strokeBorder(Color.ink.opacity(0.55), lineWidth: 1)
                .frame(width: 11, height: 11)

            VStack {
                Spacer()
                Text(hex)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Capsule().fill(Color.ink.opacity(0.55)))
                    .padding(.bottom, 9)
            }
        }
        .frame(width: diameter, height: diameter)
        .clipShape(Circle())
        .overlay(Circle().strokeBorder(Color.white, lineWidth: 2))
        .shadow(color: Color.ink.opacity(0.18), radius: 8, y: 2)
    }
}
