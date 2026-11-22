# スポイト混色ナビ

写真の色をスポイトで拾い、手持ちの絵具の配合を逆算するiOSアプリ。

写真の上に指を置くと、指の少し上にルーペが出て、その場所の色を正確に読む。拾った色に近い配合を、ホルベインの油絵具18色・透明水彩18色それぞれから3案まで提示する。混色は加算（RGBの平均）ではなく、絵具の吸収と散乱を扱う減法混色（Kubelka-Munk）で予測するので、混ぜたときの濁りや明度の低下がそのまま出る。

パレットから5色を選ぶ「5色で作る」を入れると、その5色だけで配合を探す。同じ5色で写真全体を塗ったらどう見えるかを「仕上がり」で確かめられる。面化（Kuwahara）で細部を色の塊にしたうえで5色の色域へ寄せられるので、塗る前の見当をつけやすい。

## 画面

- 上部 60%：写真。ドラッグ中は指の40pt上に直径108ptの円形ルーペ（9×9画素の拡大＋十字照準＋色の表記）。仕上がりを出しているときは左上で「元の写真を見る」に切り替わる。
- 下部：拾った色と配合予測色のスウォッチ、色差（CIEDE2000）、絵具の切り替え、5色の選択、仕上がりの切り替え、配合案3件（水平分割バー＋絵具名・顔料記号・比率）。
- 最下部：AdMobバナー（テストID）。レシピはバナーの上に64ptの余白を取ってスクロールする。

## 構成

| パス | 内容 |
| --- | --- |
| `project.yml` | XcodeGen 定義（Bundle ID: `com.shodai4.colormixnavi`、iOS 17.0+、Team `86WNUS2875`） |
| `Sources/ColorMixNaviApp.swift` | エントリポイント。AdMob の初期化 |
| `Sources/ContentView.swift` | 状態と画面構成、スポイト操作、探索の起動、仕上がりの組み立て |
| `Sources/PhotoPanel.swift` | 写真表示、ルーペ、元写真との切り替え、空の状態 |
| `Sources/RecipePanel.swift` | 色の比較、絵具の切り替え、5色の選択、仕上がりの操作、配合案のカード |
| `Sources/PhotoSampler.swift` | Display P3 での画素読み出し、`PhotoDisplay`（元写真と仕上がりの共通の読み口）、座標変換 |
| `Sources/GamutPreview.swift` | 面化（Kuwahara）、5色の 3D LUT、写真全体の変換 |
| `Sources/ColorScience.swift` | sRGB / Display P3 / 分光 ↔ XYZ ↔ CIELAB、CIEDE2000、K/S |
| `Sources/MixSolver.swift` | 2定数 Kubelka-Munk の混合、配合の探索、5色の色域サンプル |
| `Sources/PaletteData.swift` | ホルベイン36色の分光反射率（生成物） |
| `Sources/SpectralData.swift` | CIE 1931 2度視野 × D65 の重み（生成物） |
| `Sources/ProStore.swift` | Pro 買い切りの土台（StoreKit 2） |
| `Sources/BannerAdView.swift` | AdMob バナー |
| `Resources/Info.plist` | 写真の利用目的、暗号化の申告、AdMob アプリID |
| `Resources/PrivacyInfo.xcprivacy` | プライバシーマニフェスト（UserDefaults: CA92.1） |
| `Resources/Assets.xcassets` | アプリアイコン（1024px） |
| `scripts/ci-testflight.sh` | アーカイブ・書き出し・TestFlight アップロード |
| `ci/build-check.yml` | 署名なしのコンパイル確認（任意で設置。理由は `ci/README.md`） |
| `scripts/*.py` | パレット生成と数値検証（下記） |

## 色の扱い

1. **読み出し**：`PhotosPicker` で受け取った `UIImage` を、Display P3 の `CGContext` に描き直してから画素を読む。端末の写真は P3 で記録されているため、sRGB に落としてから読むと鮮やかな色ほどずれる。EXIF の回転もここで吸収する。仕上がりを出しているときは、変換後の sRGB の画素から読む（見えている色を拾う）。
2. **座標**：`.scaledToFit` の表示矩形を自前で計算し、タッチ位置 → 画素座標を変換する（`ImageGeometry`）。
3. **Lab**：Display P3 → リニア RGB（sRGB と同じ伝達関数）→ XYZ（D65）→ CIELAB。行列と白色点は CIE の定義値。
4. **混色**：各絵具のマスストーン反射率から K/S を出し、散乱係数 S を掛けて吸収 K とする。混合は K と S を別々に線形結合し、`K/S` から反射率を戻す（2定数 Kubelka-Munk）。白の散乱が強いことを表現できるので、白で淡くした色が暗く転ばない。
5. **予測色**：混合した 36 バンドの反射率を、CIE 1931 2度視野＋D65 の重みで XYZ に積分し、Lab に直す。
6. **探索**：1色（100%）・2色（10%刻み9通り）・3色（10%刻み36通り）を総当たりし、CIEDE2000 が小さい順に上位3案（同じ絵具の組み合わせは1案に統合）。1パレットで約 30,771 通りの評価。指を動かしている間は2色までで軽く回し、指を離したときに3色まで探す。5色モードでは、その5色だけで同じ探索をする。
7. **仕上がり**：写真を長辺800pxの sRGB に縮小し、面化 → 5色再現の順に掛ける。重い処理はバックグラウンドで回し、UIは固めない。
   - 面化：積分画像で 4 象限の平均と分散を出し、分散が最小の象限の平均を採る（Kuwahara）。半径は弱2・中3・強5画素。
   - 5色再現：sRGB 33×33×33 の格子点ごとに、選んだ5色の混色 455 通り（1〜3色・10%刻み）から Lab 最近傍の色の番号を先に求める（3D LUT）。画素ごとは格子のまわりの候補から Lab 距離で最も近い色を選ぶ。3次補間は速いが、補間した色が色域の外へ出る（実測で ΔE 17.8）ため採らず、出てくる色は必ず5色で作れる色にした。

### パレット

ホルベインの油絵具18色と透明水彩18色。色名と顔料記号は公式 Technical Data Sheet のとおり。

- 油絵具：パーマネントホワイトSF（PW6）、ジンクホワイトSF（PW4）、レモンイエロー（PY81+PW6）、カドミウムイエロー（PY35+PO20）、イエローオーカー（PY42）、カドミウムオレンジ（PO20）、バーミリオンヒュー（PY139+PO73+PR254）、カドミウムレッド（PR108）、クリムソンレーキ（PR177+PR254）、アリザリンクリムソン（PR83）、ローシェンナ（PY42+PBr7）、バーントシェンナ（PBr7）、バーントアンバー（PBr7）、ウルトラマリンディープ（PB29）、コバルトブルーヒュー（PB15+PB29+PW6）、セルリアンブルー（PB35）、ビリジャンヒュー（PG7）、アイボリブラック（PBk7+PBk9）。
- 透明水彩：チタニウムホワイト（PW6）、レモンイエロー（PY3+PW6）、カドミウムイエローペール（PY35）、イエローオーカー（PY42）、カドミウムレッドライト（PO20+PR108）、バーミリオンヒュー（PO73+PR254+PY110）、クリムソンレーキ（PR177+PR122+PV19）、オペラ（BV10+PR122）、ローシェンナ（PY42+PBr7）、バーントシェンナ（PBr7）、バーントアンバー（PBr7）、ウルトラマリンディープ（PB29）、コバルトブルー（PB28）、セルリアンブルー（PB35）、ビリジャンヒュー（PG7）、サップグリーン（PY150+PG7+PR122）、ペインズグレイ（PBk6+PB15+PR122）、アイボリブラック（PBk9）。

色データの出どころ（2026-11-22 確認）:

- 色名・顔料記号：ホルベイン公式 TDS（[HOC](https://www.holbeinartistmaterials.com/wp-content/uploads/2020/12/HOCTDS.pdf) / [HWC](https://www.holbeinartistmaterials.com/wp-content/uploads/2020/12/HWCTDS.pdf)）。
- 色：ホルベイン オンラインショップの公式カラーチャート（デジタルデータ）の各色の原色見本から、中央値を sRGB として採取。公式の注記どおり画面用のデータで、実際の絵具の色とは差がある。
- 油絵具の明度：同じ TDS のマンセル値（例：カドミウムレッド 6R 4.6/14.8）から ASTM D1535 の V-Y 式で L\* を出した値。写真の陰影で暗く写る分を補う。色相・彩度はカラーチャートの値。
- 分光反射率は 380-730nm / 10nm の 36 バンド。マスストーン色（L\*a\*b\*）に合うよう、平滑な基底関数で当てはめた**近似値**で、実測の分光データではない。
- 散乱係数はパーマネントホワイトを 1.0 とし、TDS の隠ぺい力（Opaque / Semi-Opaque / Semi-Transparent / Transparent）を目安に与えている（ウルトラマリンディープ 0.05、ビリジャンヒュー 0.10 など）。
- 反射率と Lab は同じ反射率から出しているので、スウォッチの色と「その絵具100%」の予測色は必ず一致する。

### 作例（油絵具18色での上位案）

| 拾った色 | 1位 | 色差 |
| --- | --- | --- |
| 空の青 `#6E9BC5` | パーマネントホワイトSF10% + ジンクホワイトSF60% + セルリアンブルー30% | ΔE 2.8 |
| 若葉 `#7FA05A` | パーマネントホワイトSF40% + カドミウムイエロー30% + ビリジャンヒュー30% | ΔE 2.0 |
| 肌の明部 `#E8C4A8` | パーマネントホワイトSF80% + カドミウムイエロー10% + バーントシェンナ10% | ΔE 4.5 |
| テラコッタ `#B96A47` | ジンクホワイトSF40% + バーミリオンヒュー10% + ローシェンナ50% | ΔE 1.4 |
| 夕暮れの紫 `#6B5B8E` | ジンクホワイトSF40% + クリムソンレーキ10% + セルリアンブルー50% | ΔE 0.5 |

## 生成と検証

```sh
python3 scripts/extract_cie_data.py        # CIE の等色関数・D65 を 10nm に切り出す
python3 scripts/generate_spectral_data.py  # Sources/SpectralData.swift
python3 scripts/generate_palette.py        # Sources/PaletteData.swift
python3 scripts/generate_icon.py           # Resources/.../AppIcon.png
python3 scripts/verify_color_math.py       # 数値検証
```

`verify_color_math.py` は Swift 実装と同じ式を Python で書き直して突き合わせる。直近の結果（2026-11-22、build 8）:

| 項目 | 結果 |
| --- | --- |
| sRGB 白 / 赤 / 緑 / 青 → Lab | 基準値と一致（±0.02） |
| sRGB → Lab → sRGB の往復 | 最大誤差 1.8e-07 |
| 分光 R=1 → XYZ | D65 白色（10nm 近似で 95.01 / 100 / 108.82） |
| CIEDE2000（Sharma 2005 の34ペア） | 最大誤差 5.0e-05 |
| 白+黒 50:50 | L\* 51.8（線形平均 59.2 より暗い＝濁りが出る） |
| 赤30 + 白70 | L\* 59.5・a\* 67.5 の淡いピンク |
| 黄50 + 青50 | 緑（a\* −9.2、b\* +6.0、L\* 40.1） |
| 36色すべてを目標に | 全色 ΔE 0.03 以下で配合が見つかる |
| 反射率から再計算した Lab | 埋め込んだ値と ΔE 0.03 以下 |
| 5色限定の探索 | 5色以外は混ざらず、18色の最良より悪くならない |
| 5色の 3D LUT | 格子点・変換後の色はすべて5色の混色（455通り）そのもの |
| 色域外の純色（緑・マゼンタ・青・シアン） | 彩度が下がり、色域の内側に収まる |
| 面化 | 一様な面は不変、エッジは中間色を作らず、ムラが減る |
| 面化＋5色再現 | 出力はすべて5色の混色そのもの |

Swift 側はこの環境に Xcode がないため、数値は上記の 1:1 ミラーで確認し、コンパイルは GitHub Actions で確認する。

## ビルド

```sh
xcodegen generate
xcodebuild build -project ColorMixNavi.xcodeproj -scheme ColorMixNavi \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```

`CURRENT_PROJECT_VERSION` は CI が `github.run_number` で上書きする。build 8 がホルベイン実色・5色モード・仕上がり（面化＋5色再現）の版。

## TestFlight 配信

`.github/workflows/ios-build.yml` が `main` への push で `scripts/ci-testflight.sh` を実行し、アーカイブ → 書き出し → TestFlight へアップロードする。ビルド番号は `github.run_number`。

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
