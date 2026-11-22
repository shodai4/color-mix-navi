import CoreGraphics
import SwiftUI
import UIKit

/// 写真を Display P3 のビットマップに展開し、画素の色を正確に読む。
///
/// UIImage の CIImage ではなく、Display P3 の CGContext に描いてから読む。
/// 端末で撮った写真は P3 で記録されているので、sRGB に落としてから読むと
/// 鮮やかな色ほどずれる。
struct SampledImage {
    /// 正規化済み（回転を適用済み）の P3 画像。
    let image: CGImage
    let width: Int
    let height: Int
    private let bytes: [UInt8]

    var displaySize: CGSize { CGSize(width: width, height: height) }

    init?(uiImage: UIImage) {
        // EXIF の回転を反映した UIImage を用意する（CGImage を直接描くと回らない）
        let upright: UIImage
        if let cgImage = uiImage.cgImage {
            upright = UIImage(cgImage: cgImage, scale: 1, orientation: uiImage.imageOrientation)
        } else {
            let format = UIGraphicsImageRendererFormat.default()
            format.scale = 1
            format.opaque = false
            let renderer = UIGraphicsImageRenderer(size: uiImage.size, format: format)
            guard let rendered = renderer.image(actions: { _ in uiImage.draw(at: .zero) }).cgImage else {
                return nil
            }
            upright = UIImage(cgImage: rendered, scale: 1, orientation: .up)
        }

        let pixelWidth = Int(upright.size.width.rounded())
        let pixelHeight = Int(upright.size.height.rounded())
        guard pixelWidth > 0, pixelHeight > 0 else { return nil }

        guard let colorSpace = CGColorSpace(name: CGColorSpace.displayP3),
              let context = CGContext(
                data: nil,
                width: pixelWidth,
                height: pixelHeight,
                bitsPerComponent: 8,
                bytesPerRow: pixelWidth * 4,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
              ) else { return nil }

        context.interpolationQuality = .high
        context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: pixelWidth, height: pixelHeight))

        UIGraphicsPushContext(context)
        upright.draw(in: CGRect(x: 0, y: 0, width: pixelWidth, height: pixelHeight))
        UIGraphicsPopContext()

        guard let drawn = context.makeImage(), let data = context.data else { return nil }
        let count = pixelWidth * pixelHeight * 4
        let pointer = data.bindMemory(to: UInt8.self, capacity: count)
        self.bytes = Array(UnsafeBufferPointer(start: pointer, count: count))
        self.image = drawn
        self.width = pixelWidth
        self.height = pixelHeight
    }

    /// 画素の色（Display P3、0-1）。座標は左上原点。
    func components(x: Int, y: Int) -> RGBComponents {
        let cx = min(max(x, 0), width - 1)
        let cy = min(max(y, 0), height - 1)
        let offset = (cy * width + cx) * 4
        return RGBComponents(
            r: Double(bytes[offset]) / 255.0,
            g: Double(bytes[offset + 1]) / 255.0,
            b: Double(bytes[offset + 2]) / 255.0
        )
    }

    func lab(x: Int, y: Int) -> LabColor {
        ColorScience.lab(fromDisplayP3: components(x: x, y: y))
    }

    /// 表示用の色（Display P3 のまま渡すと、鮮やかな色も潰れない）。
    func displayColor(x: Int, y: Int) -> Color {
        let color = components(x: x, y: y)
        return Color(.displayP3, red: color.r, green: color.g, blue: color.b)
    }

    /// ルーペ用に 9×9 画素を切り出す。端では内側に寄せる。
    func crop(centerX: Int, centerY: Int, side: Int) -> CGImage? {
        guard side > 0, width >= side, height >= side else { return nil }
        let half = side / 2
        let x = min(max(centerX - half, 0), width - side)
        let y = min(max(centerY - half, 0), height - side)
        return image.cropping(to: CGRect(x: x, y: y, width: side, height: side))
    }
}

/// 写真のアスペクト比を保った表示位置と、タッチ位置から画素への変換。
enum ImageGeometry {
    /// .scaledToFit と同じ配置。
    static func fittedRect(imageSize: CGSize, in bounds: CGSize) -> CGRect {
        guard imageSize.width > 0, imageSize.height > 0,
              bounds.width > 0, bounds.height > 0 else {
            return CGRect(origin: .zero, size: bounds)
        }
        let scale = min(bounds.width / imageSize.width, bounds.height / imageSize.height)
        let size = CGSize(width: imageSize.width * scale, height: imageSize.height * scale)
        return CGRect(x: (bounds.width - size.width) / 2,
                      y: (bounds.height - size.height) / 2,
                      width: size.width,
                      height: size.height)
    }

    /// 表示矩形内のタッチ位置から画素座標へ。矩形の外は端に丸める。
    static func pixelPoint(for location: CGPoint,
                           in rect: CGRect,
                           imageWidth: Int,
                           imageHeight: Int) -> (x: Int, y: Int) {
        guard rect.width > 0, rect.height > 0 else { return (0, 0) }
        let u = (location.x - rect.minX) / rect.width
        let v = (location.y - rect.minY) / rect.height
        let x = Int((u * CGFloat(imageWidth)).rounded(.down))
        let y = Int((v * CGFloat(imageHeight)).rounded(.down))
        return (min(max(x, 0), imageWidth - 1), min(max(y, 0), imageHeight - 1))
    }
}
