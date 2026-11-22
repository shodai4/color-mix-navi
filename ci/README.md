# GitHub Actions の追加定義

- TestFlight 配信（`.github/workflows/ios-build.yml`）は設置済み。`main` への push で動く。
- `build-check.yml` … 署名なしのコンパイル確認（Secrets 不要、push ごと）。設置は任意。
  このリポジトリへの push では GitHub App に `workflows` 権限がないため
  `.github/workflows/` へ置けず、ここに退避している。

設置するとき:

```sh
mkdir -p .github/workflows
cp ci/build-check.yml .github/workflows/
```

必要なリポジトリ Secrets（TestFlight 配信用）:

| Secret | 内容 |
| --- | --- |
| `APP_STORE_CONNECT_KEY_ID` | App Store Connect API キーの Key ID |
| `APP_STORE_CONNECT_ISSUER_ID` | Issuer ID |
| `APP_STORE_CONNECT_PRIVATE_KEY` | AuthKey_\*.p8 の中身 |
| `APPLE_TEAM_ID` | チーム ID（86WNUS2875） |
