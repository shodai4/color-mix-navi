import CoreGraphics
import Foundation
import SwiftUI

/// 面の塊にする強さ。半径はプレビュー画像の画素で数える。
enum KuwaharaLevel: Int, CaseIterable, Identifiable {
    case weak
    case medium
    case strong

    var id: Int { rawValue }

    var label: String {
        switch self {
        case .weak: return "弱"
        case .medium: return "中"
        case .strong: return "強"
        }
    }

    var radius: Int {
        switch self {
        case .weak: return 2
        case .medium: return 3
        case .strong: return 5
        }
    }
}

/// 選んだ 5 色で作れる色のサンプル。
struct GamutSample {
    let lab: LabColor
    let rgb: RGBComponents
}

/// sRGB の 3D LUT。格子点には「その色に最も近い、選んだ 5 色の混色」の番号が入る。
///
/// 3 次補間は速いが、補間した色が 5 色の色域の外へ出ることがある
/// （実測で ΔE 17.8 まで外れた）。ここでは格子のまわりの候補から
/// Lab 距離で最も近い色を選ぶので、出てくる色は必ず 5 色で作れる色になる。
struct ColorLUT {
    let size: Int
    let samples: [RGBComponents]
    private let sampleLabs: [LabColor]
    private let indices: [UInt16]

    var gridPoints: Int { size * size * size }

    init(size: Int, samples: [GamutSample], indices: [UInt16]) {
        self.size = size
        self.samples = samples.map { $0.rgb }
        self.sampleLabs = samples.map { $0.lab }
        self.indices = indices
    }

    /// その色に一番近い、選んだ 5 色で作れる色。
    func lookup(_ red: Double, _ green: Double, _ blue: Double) -> RGBComponents {
        guard size >= 2, !samples.isEmpty, indices.count >= size * size * size else {
            return RGBComponents(r: red, g: green, b: blue).clamped
        }
        let maxIndex = size - 1
        let x = min(max(red, 0), 1) * Double(maxIndex)
        let y = min(max(green, 0), 1) * Double(maxIndex)
        let z = min(max(blue, 0), 1) * Double(maxIndex)
        let x0 = min(Int(x.rounded(.down)), maxIndex - 1)
        let y0 = min(Int(y.rounded(.down)), maxIndex - 1)
        let z0 = min(Int(z.rounded(.down)), maxIndex - 1)

        let lab = ColorScience.lab(fromSRGB: RGBComponents(r: min(max(red, 0), 1),
                                                          g: min(max(green, 0), 1),
                                                          b: min(max(blue, 0), 1)))
        var best = 0
        var bestDistance = Double.infinity
        for di in 0...1 {
            let i = x0 + di
            for dj in 0...1 {
                let j = y0 + dj
                for dk in 0...1 {
                    let k = z0 + dk
                    let index = Int(indices[(i * size + j) * size + k])
                    guard index < sampleLabs.count else { continue }
                    let candidate = sampleLabs[index]
                    let dl = lab.l - candidate.l
                    let da = lab.a - candidate.a
                    let db = lab.b - candidate.b
                    let distance = dl * dl + da * da + db * db
                    if distance < bestDistance {
                        bestDistance = distance
                        best = index
                    }
                }
            }
        }
        return samples[best]
    }
}

/// 変換した写真。読み出しは sRGB の画素から。
struct PreviewFrame: Identifiable, PhotoDisplay {
    let id = UUID()
    let image: CGImage
    let width: Int
    let height: Int
    private let bytes: [UInt8]

    var displayImage: CGImage { image }
    var displaySize: CGSize { CGSize(width: width, height: height) }

    init?(image: CGImage, width: Int, height: Int, bytes: [UInt8]) {
        guard width > 0, height > 0, bytes.count >= width * height * 4 else { return nil }
        self.image = image
        self.width = width
        self.height = height
        self.bytes = bytes
    }

    func components(x: Int, y: Int) -> RGBComponents {
        let cx = min(max(x, 0), width - 1)
        let cy = min(max(y, 0), height - 1)
        let offset = (cy * width + cx) * 4
        return RGBComponents(r: Double(bytes[offset]) / 255.0,
                             g: Double(bytes[offset + 1]) / 255.0,
                             b: Double(bytes[offset + 2]) / 255.0)
    }

    func lab(x: Int, y: Int) -> LabColor {
        ColorScience.lab(fromSRGB: components(x: x, y: y))
    }

    func displayColor(x: Int, y: Int) -> Color {
        let color = components(x: x, y: y)
        return Color(.sRGB, red: color.r, green: color.g, blue: color.b)
    }

    func crop(centerX: Int, centerY: Int, side: Int) -> CGImage? {
        guard side > 0, width >= side, height >= side else { return nil }
        let half = side / 2
        let x = min(max(centerX - half, 0), width - side)
        let y = min(max(centerY - half, 0), height - side)
        return image.cropping(to: CGRect(x: x, y: y, width: side, height: side))
    }
}

/// 写真全体の仕上がりを作る。
///
/// 1. 長辺 800px に縮小（sRGB に直す）
/// 2. 面化（Kuwahara）: 4 象限の平均と分散を積分画像で出し、分散が最小の象限の平均を採る
/// 3. 5色再現: sRGB 33×33×33 の格子点ごとに、選んだ 5 色の混色から Lab 最近傍の色の
///    番号を先に求めておき（3D LUT）、画素ごとは格子のまわりの候補から選ぶ
enum PreviewEngine {
    static let maxSide = 800

    // MARK: - まとめ

    static func render(source: SampledImage, level: KuwaharaLevel?, lut: ColorLUT?) -> PreviewFrame? {
        guard let scaled = downscaled(source.image, maxSide: maxSide) else { return nil }
        var bytes = scaled.bytes

        if let level {
            bytes = kuwahara(bytes, width: scaled.width, height: scaled.height, radius: level.radius)
        }
        if let lut {
            apply(lut, to: &bytes, pixelCount: scaled.width * scaled.height)
        }
        guard let image = makeImage(from: bytes, width: scaled.width, height: scaled.height) else {
            return nil
        }
        return PreviewFrame(image: image, width: scaled.width, height: scaled.height, bytes: bytes)
    }

    // MARK: - 3D LUT

    /// 格子点ごとに、選んだ色の混色（1〜3 色・10% 刻み）で最も近い色の番号を入れる。
    /// 距離は Lab のユークリッド距離（Lab 最近傍）。
    static func buildLUT(samples: [GamutSample], size: Int = 33) -> ColorLUT {
        guard !samples.isEmpty, size >= 2 else {
            return ColorLUT(size: max(size, 2), samples: samples, indices: [])
        }

        let gridCount = size * size * size
        var indices = [UInt16](repeating: 0, count: gridCount)
        let sampleL = samples.map { $0.lab.l }
        let sampleA = samples.map { $0.lab.a }
        let sampleB = samples.map { $0.lab.b }
        let denominator = Double(size - 1)
        var offset = 0
        for redIndex in 0..<size {
            let red = Double(redIndex) / denominator
            for greenIndex in 0..<size {
                let green = Double(greenIndex) / denominator
                for blueIndex in 0..<size {
                    let blue = Double(blueIndex) / denominator
                    let lab = ColorScience.lab(fromSRGB: RGBComponents(r: red, g: green, b: blue))
                    var best = 0
                    var bestDistance = Double.infinity
                    for index in samples.indices {
                        let dl = lab.l - sampleL[index]
                        let da = lab.a - sampleA[index]
                        let db = lab.b - sampleB[index]
                        let distance = dl * dl + da * da + db * db
                        if distance < bestDistance {
                            bestDistance = distance
                            best = index
                        }
                    }
                    indices[offset] = UInt16(min(best, Int(UInt16.max)))
                    offset += 1
                }
            }
        }
        return ColorLUT(size: size, samples: samples, indices: indices)
    }

    private static func apply(_ lut: ColorLUT, to bytes: inout [UInt8], pixelCount: Int) {
        var index = 0
        for _ in 0..<pixelCount {
            let rgb = lut.lookup(Double(bytes[index]) / 255.0,
                                 Double(bytes[index + 1]) / 255.0,
                                 Double(bytes[index + 2]) / 255.0)
            bytes[index] = UInt8((rgb.r * 255).rounded())
            bytes[index + 1] = UInt8((rgb.g * 255).rounded())
            bytes[index + 2] = UInt8((rgb.b * 255).rounded())
            bytes[index + 3] = 255
            index += 4
        }
    }

    // MARK: - 面化（Kuwahara）

    static func kuwahara(_ source: [UInt8], width: Int, height: Int, radius: Int) -> [UInt8] {
        guard width > 2, height > 2, radius >= 1, source.count >= width * height * 4 else {
            return source
        }
        let stride = width + 1
        let tableSize = (width + 1) * (height + 1)
        var sumR = [Double](repeating: 0, count: tableSize)
        var sumG = [Double](repeating: 0, count: tableSize)
        var sumB = [Double](repeating: 0, count: tableSize)
        var sumL = [Double](repeating: 0, count: tableSize)
        var sumL2 = [Double](repeating: 0, count: tableSize)

        for y in 0..<height {
            var rowR = 0.0, rowG = 0.0, rowB = 0.0, rowL = 0.0, rowL2 = 0.0
            let pixelRow = y * width * 4
            let tableRow = (y + 1) * stride
            let previousRow = y * stride
            for x in 0..<width {
                let offset = pixelRow + x * 4
                let red = Double(source[offset])
                let green = Double(source[offset + 1])
                let blue = Double(source[offset + 2])
                let luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                rowR += red
                rowG += green
                rowB += blue
                rowL += luma
                rowL2 += luma * luma
                let target = tableRow + x + 1
                sumR[target] = sumR[previousRow + x + 1] + rowR
                sumG[target] = sumG[previousRow + x + 1] + rowG
                sumB[target] = sumB[previousRow + x + 1] + rowB
                sumL[target] = sumL[previousRow + x + 1] + rowL
                sumL2[target] = sumL2[previousRow + x + 1] + rowL2
            }
        }

        var output = source
        for y in 0..<height {
            for x in 0..<width {
                var bestWeight = -1.0
                var bestVariance = Double.infinity
                var bestR = 0.0, bestG = 0.0, bestB = 0.0

                // 4 象限。中心の画素はすべての象限に含める。
                for quadrant in 0..<4 {
                    let x0 = quadrant == 0 || quadrant == 2 ? max(0, x - radius) : x
                    let x1 = quadrant == 0 || quadrant == 2 ? x + 1 : min(width, x + radius + 1)
                    let y0 = quadrant < 2 ? max(0, y - radius) : y
                    let y1 = quadrant < 2 ? y + 1 : min(height, y + radius + 1)
                    let area = Double((x1 - x0) * (y1 - y0))
                    guard area > 0 else { continue }

                    let a = y0 * stride + x0
                    let b = y0 * stride + x1
                    let c = y1 * stride + x0
                    let d = y1 * stride + x1

                    let luma = sumL[d] - sumL[b] - sumL[c] + sumL[a]
                    let luma2 = sumL2[d] - sumL2[b] - sumL2[c] + sumL2[a]
                    let mean = luma / area
                    let variance = max(luma2 / area - mean * mean, 0)
                    if variance < bestVariance {
                        bestVariance = variance
                        bestWeight = area
                        bestR = (sumR[d] - sumR[b] - sumR[c] + sumR[a]) / area
                        bestG = (sumG[d] - sumG[b] - sumG[c] + sumG[a]) / area
                        bestB = (sumB[d] - sumB[b] - sumB[c] + sumB[a]) / area
                    }
                }

                guard bestWeight > 0 else { continue }
                let offset = (y * width + x) * 4
                output[offset] = UInt8(min(max(bestR, 0), 255).rounded())
                output[offset + 1] = UInt8(min(max(bestG, 0), 255).rounded())
                output[offset + 2] = UInt8(min(max(bestB, 0), 255).rounded())
                output[offset + 3] = 255
            }
        }
        return output
    }

    // MARK: - ビットマップ

    static func downscaled(_ image: CGImage, maxSide: Int) -> (image: CGImage, bytes: [UInt8], width: Int, height: Int)? {
        let width = image.width
        let height = image.height
        guard width > 0, height > 0 else { return nil }
        let scale = min(1.0, Double(maxSide) / Double(max(width, height)))
        let targetWidth = max(1, Int((Double(width) * scale).rounded()))
        let targetHeight = max(1, Int((Double(height) * scale).rounded()))
        guard let context = makeContext(width: targetWidth, height: targetHeight) else { return nil }
        context.interpolationQuality = .high
        context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: targetWidth, height: targetHeight))
        context.draw(image, in: CGRect(x: 0, y: 0, width: targetWidth, height: targetHeight))
        guard let drawn = context.makeImage(), let data = context.data else { return nil }
        let count = targetWidth * targetHeight * 4
        let pointer = data.bindMemory(to: UInt8.self, capacity: count)
        let bytes = Array(UnsafeBufferPointer(start: pointer, count: count))
        return (image: drawn, bytes: bytes, width: targetWidth, height: targetHeight)
    }

    static func makeImage(from bytes: [UInt8], width: Int, height: Int) -> CGImage? {
        guard let context = makeContext(width: width, height: height),
              let data = context.data else { return nil }
        let count = width * height * 4
        let pointer = data.bindMemory(to: UInt8.self, capacity: count)
        let buffer = UnsafeMutableBufferPointer(start: pointer, count: count)
        bytes.withUnsafeBufferPointer { source in
            guard let base = source.baseAddress else { return }
            buffer.baseAddress?.update(from: base, count: min(source.count, count))
        }
        return context.makeImage()
    }

    private static func makeContext(width: Int, height: Int) -> CGContext? {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        return CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: space,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
        )
    }
}
