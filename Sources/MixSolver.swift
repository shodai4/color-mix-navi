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

    /// 硫化物を含む色（N 印）が入っているか。混色の注意を出すのに使う。
    var hasSulfide: Bool {
        entries.contains { $0.paint.isSulfide }
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
/// 色が 24 色までは総当たり（18 色で約 3 万通り）。
/// カタログ全色（111 色）では 3 色の組み合わせが 23 万通り・評価が 850 万通りに
/// なるため、Lab 空間で目標色に近い組を先に絞ってから混色を計算する。
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

    /// これ以下の色数なら、2 色・3 色の組み合わせをすべて試す。
    private let exhaustiveLimit = 24
    /// 色が多いときに残す組み合わせの数。
    private let pairKeep = 480
    private let tripleKeep = 500
    /// 混色は 3 色の Lab の平均より暗く出るので、目標色を持ち上げた位置からも
    /// 三角形までの距離を見て、取りこぼしを減らす。
    private let tripleLifts: [Double] = [0, 8, 16]

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
            if pigments.count <= exhaustiveLimit {
                for first in 0..<pigments.count {
                    for second in (first + 1)..<pigments.count {
                        for step in 1...9 {
                            let fraction = Double(step) / 10
                            offer(indices: [first, second], fractions: [fraction, 1 - fraction])
                        }
                    }
                }
            } else {
                for pair in closestPairs() {
                    for step in 1...9 {
                        let fraction = Double(step) / 10
                        offer(indices: [pair.0, pair.1], fractions: [fraction, 1 - fraction])
                    }
                }
            }
        }

        if maxPaints >= 3 {
            if pigments.count <= exhaustiveLimit {
                for first in 0..<pigments.count {
                    for second in (first + 1)..<pigments.count {
                        for third in (second + 1)..<pigments.count {
                            offerTriple(first, second, third)
                        }
                    }
                }
            } else {
                for triple in closestTriples() {
                    offerTriple(triple.0, triple.1, triple.2)
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

    private func offerTriple(_ first: Int, _ second: Int, _ third: Int) {
        for a in 1...8 {
            for b in 1...(10 - a) {
                let c = 10 - a - b
                guard c >= 1 else { continue }
                offer(indices: [first, second, third],
                      fractions: [Double(a) / 10, Double(b) / 10, Double(c) / 10])
            }
        }
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

    // MARK: - 組み合わせの絞り込み

    /// 目標色の Lab に近い順に 2 色の組を選ぶ。
    /// 混色の結果は 2 色の Lab を結ぶ線の近くに来るので、線分までの距離で順位をつける。
    private func closestPairs() -> [(Int, Int)] {
        var best: [(distance: Double, first: Int, second: Int)] = []
        best.reserveCapacity(pairKeep + 1)
        for first in pigments.indices {
            for second in (first + 1)..<pigments.count {
                let distance = segmentDistance(target, pigments[first].lab, pigments[second].lab)
                if best.count == pairKeep, let last = best.last, distance >= last.distance {
                    continue
                }
                insert(&best, distance: distance, first: first, second: second, keep: pairKeep)
            }
        }
        return best.map { ($0.first, $0.second) }
    }

    /// 目標色の Lab に近い順に 3 色の組を選ぶ。
    /// 混色の結果は 3 色の Lab が作る三角形の近くに来るので、三角形までの距離で順位をつける。
    /// 減法混色は三角形より暗く出るため、目標色を少し持ち上げた位置からも拾う。
    private func closestTriples() -> [(Int, Int, Int)] {
        let count = pigments.count
        var merged: [Int: (distance: Double, first: Int, second: Int, third: Int)] = [:]
        for lift in tripleLifts {
            let point = LabColor(l: target.l + lift, a: target.a, b: target.b)
            var best: [(distance: Double, first: Int, second: Int, third: Int)] = []
            best.reserveCapacity(tripleKeep + 1)
            for first in 0..<count {
                for second in (first + 1)..<count {
                    for third in (second + 1)..<count {
                        let distance = triangleDistance(point, pigments[first].lab, pigments[second].lab,
                                                        pigments[third].lab)
                        if best.count == tripleKeep, let last = best.last, distance >= last.distance {
                            continue
                        }
                        insert(&best, distance: distance, first: first, second: second, third: third,
                               keep: tripleKeep)
                    }
                }
            }
            for entry in best {
                let key = entry.first * 1_000_000 + entry.second * 1_000 + entry.third
                if let existing = merged[key], existing.distance <= entry.distance { continue }
                merged[key] = entry
            }
        }
        return merged.values
            .sorted { $0.distance < $1.distance }
            .map { ($0.first, $0.second, $0.third) }
    }

    private func insert(_ list: inout [(distance: Double, first: Int, second: Int, third: Int)],
                        distance: Double, first: Int, second: Int, third: Int, keep: Int) {
        var low = 0
        var high = list.count
        while low < high {
            let middle = (low + high) / 2
            if list[middle].distance < distance { low = middle + 1 } else { high = middle }
        }
        list.insert((distance, first, second, third), at: low)
        if list.count > keep { list.removeLast() }
    }

    private func insert(_ list: inout [(distance: Double, first: Int, second: Int)],
                        distance: Double, first: Int, second: Int, keep: Int) {
        var low = 0
        var high = list.count
        while low < high {
            let middle = (low + high) / 2
            if list[middle].distance < distance { low = middle + 1 } else { high = middle }
        }
        list.insert((distance, first, second), at: low)
        if list.count > keep { list.removeLast() }
    }

    /// 点から線分までの距離（Lab をそのまま 3 次元として扱う）。
    private func segmentDistance(_ point: LabColor, _ start: LabColor, _ end: LabColor) -> Double {
        let ex = end.l - start.l
        let ey = end.a - start.a
        let ez = end.b - start.b
        let px = point.l - start.l
        let py = point.a - start.a
        let pz = point.b - start.b
        let lengthSquared = ex * ex + ey * ey + ez * ez
        var t = lengthSquared > 0 ? (px * ex + py * ey + pz * ez) / lengthSquared : 0
        t = min(max(t, 0), 1)
        let dx = px - ex * t
        let dy = py - ey * t
        let dz = pz - ez * t
        return (dx * dx + dy * dy + dz * dz).squareRoot()
    }

    /// 点から三角形までの距離（Ericson, Real-Time Collision Detection）。
    private func triangleDistance(_ point: LabColor,
                                  _ first: LabColor,
                                  _ second: LabColor,
                                  _ third: LabColor) -> Double {
        let ax = first.l, ay = first.a, az = first.b
        let bx = second.l, by = second.a, bz = second.b
        let cx = third.l, cy = third.a, cz = third.b
        let px = point.l, py = point.a, pz = point.b

        let abx = bx - ax, aby = by - ay, abz = bz - az
        let acx = cx - ax, acy = cy - ay, acz = cz - az
        let apx = px - ax, apy = py - ay, apz = pz - az

        let d1 = abx * apx + aby * apy + abz * apz
        let d2 = acx * apx + acy * apy + acz * apz
        if d1 <= 0 && d2 <= 0 {
            return (apx * apx + apy * apy + apz * apz).squareRoot()
        }

        let bpx = px - bx, bpy = py - by, bpz = pz - bz
        let d3 = abx * bpx + aby * bpy + abz * bpz
        let d4 = acx * bpx + acy * bpy + acz * bpz
        if d3 >= 0 && d4 <= d3 {
            return (bpx * bpx + bpy * bpy + bpz * bpz).squareRoot()
        }

        let vc = d1 * d4 - d3 * d2
        if vc <= 0 && d1 >= 0 && d3 <= 0 {
            let v = d1 / (d1 - d3)
            let qx = apx - abx * v, qy = apy - aby * v, qz = apz - abz * v
            return (qx * qx + qy * qy + qz * qz).squareRoot()
        }

        let cpx = px - cx, cpy = py - cy, cpz = pz - cz
        let d5 = abx * cpx + aby * cpy + abz * cpz
        let d6 = acx * cpx + acy * cpy + acz * cpz
        if d6 >= 0 && d5 <= d6 {
            return (cpx * cpx + cpy * cpy + cpz * cpz).squareRoot()
        }

        let vb = d5 * d2 - d1 * d6
        if vb <= 0 && d2 >= 0 && d6 <= 0 {
            let w = d2 / (d2 - d6)
            let qx = apx - acx * w, qy = apy - acy * w, qz = apz - acz * w
            return (qx * qx + qy * qy + qz * qz).squareRoot()
        }

        let va = d3 * d6 - d5 * d4
        if va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0 {
            let w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
            let qx = bpx - (cx - bx) * w
            let qy = bpy - (cy - by) * w
            let qz = bpz - (cz - bz) * w
            return (qx * qx + qy * qy + qz * qz).squareRoot()
        }

        // 面の内側
        let denom = va + vb + vc
        guard abs(denom) > 1e-9 else { return segmentDistance(point, first, second) }
        let v = vb / denom
        let w = vc / denom
        let nx = apx - (abx * v + acx * w)
        let ny = apy - (aby * v + acy * w)
        let nz = apz - (abz * v + acz * w)
        return (nx * nx + ny * ny + nz * nz).squareRoot()
    }
}
