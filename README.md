# スポイト混色ナビ

写真の色をスポイトで拾い、手持ちの絵具の配合を逆算するiOSアプリ。

写真の上に指を置くと、指の少し上にルーペが出て、その場所の色を正確に読む。拾った色に近い配合を、油絵具18色・透明水彩18色それぞれから3案まで提示する。混色は加算（RGBの平均）ではなく、絵具の吸収と散乱を扱う減法混色（Kubelka-Munk）で予測するので、混ぜたときの濁りや明度の低下がそのまま出る。

## 画面

- 上部 58%：写真。ドラッグ中は指の40pt上に直径108ptの円形ルーペ（9×9画素の拡大＋十字照準＋色の表記）。
- 下部：拾った色と配合予測色のスウォッチ、色差（CIEDE2000）、絵具の切り替え、配合案3件（水平分割バー＋絵具名・顔料記号・比率）。
- 最下部：AdMobバナー（テストID）。レシピはバナーの上に64ptの余白を取ってスクロールする。

## 構成

| パス | 内容 |
| --- | --- |
| `project.yml` | XcodeGen 定義（Bundle ID: `com.shodai4.colormixnavi`、iOS 17.0+、Team `86WNUS2875`） |
| `Sources/ColorMixNaviApp.swift` | エントリポイント。AdMob の初期化 |
| `Sources/ContentView.swift` | 状態と画面構成、スポイト操作、探索の起動 |
| `Sources/PhotoPanel.swift` | 写真表示、ルーペ、空の状態 |
| `Sources/RecipePanel.swift` | 色の比較、配合案のカード |
| `Sources/PhotoSampler.swift` | Display P3 での画素読み出しと座標変換 |
| `Sources/ColorScience.swift` | sRGB / Display P3 / 分光 ↔ XYZ ↔ CIELAB、CIEDE2000、K/S |
| `Sources/MixSolver.swift` | 2定数 Kubelka-Munk の混合と、配合の探索 |
| `Sources/PaletteData.swift` | 絵具36色の分光反射率（生成物） |
| `Sources/SpectralData.swift` | CIE 1931 2度視野 × D65 の重み（生成物） |
| `Sources/ProStore.swift` | Pro 買い切りの土台（StoreKit 2） |
| `Sources/BannerAdView.swift` | AdMob バナー |
| `Resources/Info.plist` | 写真の利用目的、暗号化の申告、AdMob アプリID |
| `Resources/PrivacyInfo.xcprivacy` | プライバシーマニフェスト（UserDefaults: CA92.1） |
| `Resources/Assets.xcassets` | アプリアイコン（1024px） |
| `scripts/ci-testflight.sh` | アーカイブ・書き出し・TestFlight アップロード |
| `scripts/*.py` | パレット生成と数値検証（下記） |

## 色の扱い

1. **読み出し**：`PhotosPicker` で受け取った `UIImage` を、Display P3 の `CGContext` に描き直してから画素を読む。端末の写真は P3 で記録されているため、sRGB に落としてから読むと鮮やかな色ほどずれる。EXIF の回転もここで吸収する。
2. **座標**：`.scaledToFit` の表示矩形を自前で計算し、タッチ位置 → 画素座標を変換する（`ImageGeometry`）。
3. **Lab**：Display P3 → リニア RGB（sRGB と同じ伝達関数）→ XYZ（D65）→ CIELAB。行列と白色点は CIE の定義値。
4. **混色**：各絵具のマスストーン反射率から K/S を出し、散乱係数 S を掛けて吸収 K とする。混合は K と S を別々に線形結合し、`K/S` から反射率を戻す（2定数 Kubelka-Munk）。白の散乱が強いことを表現できるので、白で淡くした色が暗く転ばない。
5. **予測色**：混合した 36 バンドの反射率を、CIE 1931 2度視野＋D65 の重みで XYZ に積分し、Lab に直す。
6. **探索**：1色（100%）・2色（10%刻み9通り）・3色（10%刻み36通り）を総当たりし、CIEDE2000 が小さい順に上位3案（同じ絵具の組み合わせは1案に統合）。1パレットで約 30,771 通りの評価。指を動かしている間は2色までで軽く回し、指を離したときに3色まで探す。

### パレット

油絵具18色（チタニウムホワイト、レモンイエロー、カドミウムイエロー、イエローオーカー、カドミウムオレンジ、カドミウムレッド、キナクリドンレッド、アリザリンクリムゾン、ローシエナ、バーントシエナ、バーントアンバー、ウルトラマリン、コバルトブルー、セルリアンブルー、プルシアンブルー、ビリジアン、サップグリーン、アイボリーブラック）と、透明水彩18色（オペラ、ペインズグレーを含む）。

- 分光反射率は 380-730nm / 10nm の 36 バンド。各顔料の代表的なマスストーン色（L\*a\*b\*）に合うよう、平滑な基底関数で当てはめた**近似値**で、実測の分光データではない。
- 散乱係数はチタニウムホワイトを 1.0 とし、隠ぺい力の目安から与えている（ウルトラマリン 0.05、プルシアンブルー 0.03 など）。
- 反射率と Lab は同じ反射率から出しているので、スウォッチの色と「その絵具100%」の予測色は必ず一致する。

## 生成と検証

```sh
python3 scripts/extract_cie_data.py        # CIE の等色関数・D65 を 10nm に切り出す
python3 scripts/generate_spectral_data.py  # Sources/SpectralData.swift
python3 scripts/generate_palette.py        # Sources/PaletteData.swift
python3 scripts/generate_icon.py           # Resources/.../AppIcon.png
python3 scripts/verify_color_math.py       # 数値検証
```

`verify_color_math.py` は Swift 実装と同じ式を Python で書き直して突き合わせる。直近の結果:

| 項目 | 結果 |
| --- | --- |
| sRGB 白 / 赤 / 緑 / 青 → Lab | 基準値と一致（±0.02） |
| sRGB → Lab → sRGB の往復 | 最大誤差 1.8e-07 |
| 分光 R=1 → XYZ | D65 白色（10nm 近似で 95.01 / 100 / 108.82） |
| CIEDE2000（Sharma 2005 の34ペア） | 最大誤差 5.0e-05 |
| 白+黒 50:50 | L\* 49（線形平均 57 より暗い＝濁りが出る） |
| 赤30 + 白70 | L\* 63・a\* 52 の淡いピンク |
| 黄50 + 青50 | 緑（a\* −2、b\* +25） |
| 36色すべてを目標に | 全色 ΔE 0.01 以下で配合が見つかる |
| 反射率から再計算した Lab | 埋め込んだ値と ΔE 0.01 以下 |

Swift 側はこの環境に Xcode がないため、数値は上記の 1:1 ミラーで確認し、コンパイルは GitHub Actions の `Build Check` で確認する。

## ビルド

```sh
xcodegen generate
xcodebuild build -project ColorMixNavi.xcodeproj -scheme ColorMixNavi \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```

## TestFlight 配信

`main` へ push すると `iOS TestFlight` が `scripts/ci-testflight.sh` を実行し、アーカイブ → 書き出し → TestFlight へアップロードする。ビルド番号は `github.run_number`。

必要なリポジトリ Secrets:

| 名前 | 内容 |
| --- | --- |
| `APP_STORE_CONNECT_KEY_ID` | App Store Connect API キーの Key ID |
| `APP_STORE_CONNECT_ISSUER_ID` | Issuer ID |
| `APP_STORE_CONNECT_PRIVATE_KEY` | AuthKey_\*.p8 の中身 |
| `APPLE_TEAM_ID` | チーム ID |

App Store Connect: App ID `6837945734` / Bundle ID `com.shodai4.colormixnavi` / 内部グループ「開発テスト」。

## 広告と Pro

- バナーは AdMob のテストID（アプリID `ca-app-pub-3940256099942544~1458002511`、枠 `ca-app-pub-3940256099942544/2934735716`）。本番では差し替える。
- Pro 買い切り（300〜500円を想定）の土台を `ProStore` に用意した。商品 `com.shodai4.colormixnavi.pro` を App Store Connect に登録すると、レシピ下部に購入導線が出て、購入後はバナーが消える。商品が未登録のあいだは何も表示しない。
