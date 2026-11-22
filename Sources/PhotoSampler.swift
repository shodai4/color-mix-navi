import CoreGraphics
import Foundation
import ImageIO
import SwiftUI

/// 画面に出している写真。元の写真（Display P3）と、変換した仕上がり（sRGB）の
/// どちらでも同じようにスポイトできるようにする。
protocol PhotoDisplay {
    var displayImage: CGImage { get }
    var width: Int { get }
    var height: Int { get }
    var displaySize: CGSize { get }
    func components(x: Int, y: Int) -> RGBComponents
    func lab(x: Int, y: Int) -> LabColor
    func displayColor(x: Int, y: Int) -> Color
    func crop(centerX: Int, centerY: Int, side: Int) -> CGImage?
}

/// 写真を Display P3 のビットマップに展開し、画素の色を正確に読む。
///
/// CIImage ではなく、Display P3 の CGContext に描いてから読む。
/// 端末で撮った写真は P3 で記録されているので、sRGB に落としてから読むと
/// 鮮やかな色ほどずれる。
///
/// 写真の向き（EXIF の Orientation）もここで一度だけ焼き込む。表示・スポイト・
/// ルーペ・仕上がりはすべてこの 1 枚を共有するので、見えている写真と拾う色の
/// 向き・座標は必ず一致する。
struct SampledImage: Identifiable, PhotoDisplay {
    let id = UUID()
    /// 正規化済み（回転を適用済み）の P3 画像。
    let image: CGImage
    let width: Int
    let height: Int
    private let bytes: [UInt8]

    var displayImage: CGImage { image }
    var displaySize: CGSize { CGSize(width: width, height: height) }

    /// 写真ファイルをそのまま受け取る。向きは EXIF の値（1〜8）から決める。
    /// UIImage の imageOrientation は使わない（UIImage 経由の描画が上下反転の
    /// 原因だったので、ImageIO で読んで EXIF の値のまま扱う）。
    init?(imageData: Data) {
        guard let source = CGImageSourceCreateWithData(imageData as CFData, nil),
              let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            return nil
        }
        let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
        let exif = (properties?[kCGImagePropertyOrientation] as? NSNumber)?.uint32Value ?? 1
        self.init(cgImage: cgImage, orientationEXIF: exif)
    }

    /// EXIF の向き（1〜8）を焼き込んで、上向き・左上原点の P3 画像にする。
    ///
    /// CGContext は左下原点なので、UIImage の draw ではなく CGImage を
    /// 変換つきで直接描く。変換は `ImageGeometry.orientationTransform` の
    /// 表だけで決まり、描き終えた絵は「表示したときの向き」そのものになる。
    init?(cgImage: CGImage, orientationEXIF exif: UInt32 = 1) {
        let sourceWidth = cgImage.width
        let sourceHeight = cgImage.height
        guard sourceWidth > 0, sourceHeight > 0 else { return nil }

        let swaps = ImageGeometry.swapsDimensions(exif: exif)
        let pixelWidth = swaps ? sourceHeight : sourceWidth
        let pixelHeight = swaps ? sourceWidth : sourceHeight

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
        context.setFillColor(gray: 1, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: pixelWidth, height: pixelHeight))

        context.saveGState()
        context.concatenate(ImageGeometry.orientationTransform(exif: exif,
                                                              width: sourceWidth,
                                                              height: sourceHeight))
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: sourceWidth, height: sourceHeight))
        context.restoreGState()

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

    // MARK: - 写真の向き

    /// 90 度回す向き（EXIF 5〜8）は、縦横が入れ替わる。
    static func swapsDimensions(exif value: UInt32) -> Bool {
        (5...8).contains(value)
    }

    /// EXIF の Orientation（1〜8）を、元画像を描くときの変換にする。
    ///
    /// CGContext に変換なしで描くと、画素 (i, j)（左から i 列・上から j 行）は
    /// 左下原点のユーザー座標 (i + 0.5, 高さ - j - 0.5) に置かれる。
    /// そこへこの変換をかけると、表示したときに EXIF の向きどおりに見える画素へ
    /// 移る（1 は無変換、6 は時計回りに 90 度、8 は反時計回りに 90 度）。
    /// 表そのものは scripts/verify_color_math.py が読み出して検算する。
    static func orientationTransform(exif value: UInt32, width: Int, height: Int) -> CGAffineTransform {
        let w = CGFloat(width)
        let h = CGFloat(height)
        switch value {
        case 1: return CGAffineTransform(a: 1, b: 0, c: 0, d: 1, tx: 0, ty: 0)
        case 2: return CGAffineTransform(a: -1, b: 0, c: 0, d: 1, tx: w, ty: 0)
        case 3: return CGAffineTransform(a: -1, b: 0, c: 0, d: -1, tx: w, ty: h)
        case 4: return CGAffineTransform(a: 1, b: 0, c: 0, d: -1, tx: 0, ty: h)
        case 5: return CGAffineTransform(a: 0, b: -1, c: -1, d: 0, tx: h, ty: w)
        case 6: return CGAffineTransform(a: 0, b: -1, c: 1, d: 0, tx: 0, ty: w)
        case 7: return CGAffineTransform(a: 0, b: 1, c: 1, d: 0, tx: 0, ty: 0)
        case 8: return CGAffineTransform(a: 0, b: 1, c: -1, d: 0, tx: h, ty: 0)
        default: return .identity
        }
    }

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
