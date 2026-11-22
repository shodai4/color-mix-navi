import Foundation

/// レシピの 1 行（絵具と配合比）。
struct MixEntry: Identifiable {
    let paint: Paint
    let fraction: Double

    var id: Int { paint.id }
    var percent: Int { Int((fraction * 100).rounded()) }
}

/// 配合案。
struct MixRecipe: Identifiable {
    let id: Int
    let entries: [MixEntry]
    let lab: LabColor
    let deltaE: Double

    var fractionSum: Double {
        entries.reduce(0) { $0 + $1.fraction }
    }
}

/// 計算用に前処理した絵具。吸収 K は散乱 S を掛けた値で持つ。
struct MixPigment {
    let paint: Paint
    let absorption: [Double]
    let scattering: Double
    let lab: LabColor
}

/// 減法混色（2定数 Kubelka-Munk）で目標色に近い配合を探す。
///
/// 1 色・2 色・3 色の組み合わせを 10% 刻みで総当たりし、
/// 予測色と目標色の CIEDE2000 色差が小さい順に上位を返す。
/// 1 パレット（18 色）で約 3 万通りの評価。
enum MixSolver {
    static func pigments(for paints: [Paint]) -> [MixPigment] {
        paints.map { paint in
            MixPigment(
                paint: paint,
                absorption: paint.reflectance.map { ColorScience.ks(fromReflectance: $0) * paint.scatter },
                scattering: max(paint.scatter, 0.02),
                lab: paint.lab
            )
        }
    }

    /// - Parameters:
    ///   - maxPaints: 2 なら 1-2 色、3 なら 3 色まで。指を動かしている間は 2 で軽く回す。
    static func solve(target: LabColor,
                      pigments: [MixPigment],
                      maxPaints: Int,
                      limit: Int = 3) -> [MixRecipe] {
        guard pigments.count >= 2 else { return [] }
        return SolverCore(target: target, pigments: pigments).run(maxPaints: min(max(maxPaints, 1), 3), limit: limit)
    }

    /// 選んだ絵具で作れる色を、1〜3 色・10% 刻みで並べる。
    /// 3D LUT（写真全体の色域再現）の候補になる。5 色なら 455 通り。
    static func gamutSamples(pigments: [MixPigment]) -> [GamutSample] {
        var samples: [GamutSample] = []
        let count = pigments.count
        guard count > 0 else { return samples }

        let bandCount = SpectralData.weightsX.count
        var buffer = [Double](repeating: 0, count: bandCount)

        func appendSample(indices: [Int], fractions: [Double]) {
            var scattering = 0.0
            for (slot, index) in indices.enumerated() {
                scattering += fractions[slot] * pigments[index].scattering
            }
            scattering = max(scattering, 0.0001)

            for band in 0..<bandCount {
                var absorption = 0.0
                for (slot, index) in indices.enumerated() {
                    absorption += fractions[slot] * pigments[index].absorption[band]
                }
                buffer[band] = ColorScience.reflectance(fromKS: absorption / scattering)
            }

            let lab = ColorScience.lab(fromReflectance: buffer)
            samples.append(GamutSample(lab: lab, rgb: ColorScience.srgb(fromLab: lab).clamped))
        }

        for index in 0..<count {
            appendSample(indices: [index], fractions: [1.0])
        }

        if count >= 2 {
            for first in 0..<count {
                for second in (first + 1)..<count {
                    for step in 1...9 {
                        let fraction = Double(step) / 10
                        appendSample(indices: [first, second], fractions: [fraction, 1 - fraction])
                    }
                }
            }
        }

        if count >= 3 {
            for first in 0..<count {
                for second in (first + 1)..<count {
                    for third in (second + 1)..<count {
                        for a in 1...8 {
                            for b in 1...(10 - a) {
                                let c = 10 - a - b
                                guard c >= 1 else { continue }
                                appendSample(indices: [first, second, third],
                                             fractions: [Double(a) / 10, Double(b) / 10, Double(c) / 10])
                            }
                        }
                    }
                }
            }
        }

        return samples
    }
}

private struct Candidate {
    let key: Int
    let indices: [Int]
    let fractions: [Double]
    let lab: LabColor
    let deltaE: Double
}

private final class SolverCore {
    private let target: LabColor
    private let pigments: [MixPigment]
    private var buffer: [Double]
    private var candidates: [Candidate] = []
    private let capacity = 24

    init(target: LabColor, pigments: [MixPigment]) {
        self.target = target
        self.pigments = pigments
        self.buffer = [Double](repeating: 0, count: SpectralData.weightsX.count)
    }

    func run(maxPaints: Int, limit: Int) -> [MixRecipe] {
        candidates.removeAll(keepingCapacity: true)

        for index in pigments.indices {
            offer(indices: [index], fractions: [1.0])
        }

        if maxPaints >= 2 {
            for first in 0..<pigments.count {
                for second in (first + 1)..<pigments.count {
                    for step in 1...9 {
                        let fraction = Double(step) / 10
                        offer(indices: [first, second], fractions: [fraction, 1 - fraction])
                    }
                }
            }
        }

        if maxPaints >= 3 {
            for first in 0..<pigments.count {
                for second in (first + 1)..<pigments.count {
                    for third in (second + 1)..<pigments.count {
                        for a in 1...8 {
                            for b in 1...(10 - a) {
                                let c = 10 - a - b
                                guard c >= 1 else { continue }
                                offer(indices: [first, second, third],
                                      fractions: [Double(a) / 10, Double(b) / 10, Double(c) / 10])
                            }
                        }
                    }
                }
            }
        }

        var recipes: [MixRecipe] = []
        var seen = Set<Int>()
        for candidate in candidates {
            guard !seen.contains(candidate.key) else { continue }
            seen.insert(candidate.key)

            let entries = candidate.indices.enumerated()
                .map { (slot, index) in
                    MixEntry(paint: pigments[index].paint, fraction: candidate.fractions[slot])
                }
                .sorted { $0.fraction > $1.fraction }

            recipes.append(MixRecipe(id: recipes.count,
                                     entries: entries,
                                     lab: candidate.lab,
                                     deltaE: candidate.deltaE))
            if recipes.count == limit { break }
        }
        return recipes
    }

    private func offer(indices: [Int], fractions: [Double]) {
        let lab = predict(indices: indices, fractions: fractions)
        let deltaE = ColorScience.deltaE2000(target, lab)
        let candidate = Candidate(key: Self.key(indices), indices: indices, fractions: fractions,
                                  lab: lab, deltaE: deltaE)

        if candidates.count < capacity {
            candidates.append(candidate)
            candidates.sort { $0.deltaE < $1.deltaE }
        } else if let worst = candidates.last, deltaE < worst.deltaE {
            candidates[candidates.count - 1] = candidate
            candidates.sort { $0.deltaE < $1.deltaE }
        }
    }

    /// 2定数 Kubelka-Munk: 吸収 K と散乱 S を別々に混ぜ、K/S から反射率を出す。
    private func predict(indices: [Int], fractions: [Double]) -> LabColor {
        var scatteringSum = 0.0
        for (slot, index) in indices.enumerated() {
            scatteringSum += fractions[slot] * pigments[index].scattering
        }
        let scattering = max(scatteringSum, 0.0001)

        for band in buffer.indices {
            var absorptionSum = 0.0
            for (slot, index) in indices.enumerated() {
                absorptionSum += fractions[slot] * pigments[index].absorption[band]
            }
            buffer[band] = ColorScience.reflectance(fromKS: absorptionSum / scattering)
        }
        return ColorScience.lab(fromReflectance: buffer)
    }

    private static func key(_ indices: [Int]) -> Int {
        var value = 0
        for index in indices {
            value = value * 1000 + index
        }
        return value
    }
}
