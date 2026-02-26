# AI Agent Instructions (AGENTS.md)

このリポジトリで作業する AI エージェント（および開発者）向けのガイドラインです。コードの自動生成やタスク実行時に、以下のルールを遵守してください。

## 1. Git Commit Guidelines

コミットメッセージは **Conventional Commits** の形式に従い、**日本語**で記述してください。
（ただし、リポジトリ作成直後の空コミットは `initial commit` のまま維持します）

### Format
```text
<type>: <description>
```

### Types
- `feat`: 新しい機能の追加 (A new feature)
- `fix`: バグ修正 (A bug fix)
- `docs`: ドキュメントのみの変更 (Documentation only changes)
- `style`: コードの意味に影響を与えない変更（空白、フォーマット、セミコロンの欠落など） (Changes that do not affect the meaning of the code)
- `refactor`: バグ修正や機能追加を行わないコードの変更 (A code change that neither fixes a bug nor adds a feature)
- `perf`: パフォーマンスを向上させるコードの変更 (A code change that improves performance)
- `test`: 不足しているテストの追加や既存のテストの修正 (Adding missing or correcting existing tests)
- `chore`: ビルドプロセスやドキュメント生成などの補助ツール、ライブラリの変更 (Changes to the build process or auxiliary tools and libraries)

### Example
- `feat: データ前処理のパイプラインを追加`
- `fix: 欠損値補完時のインデックスエラーを修正`
- `docs: README.mdにセットアップ手順を追記`

## 2. Python Development Guidelines

- **パッケージ管理**: `uv` を使用しています。ライブラリの追加・更新の際は `uv` を利用してください（例: `uv pip install` または `uv add`）。
- **コードスタイル**: 
  - メソッドや関数には適切な型ヒント (Type Hints) を付与してください。
  - 複雑なロジックには必ず Docstring (Google or NumPy style) を記述し、意図を明確にしてください。

## 3. Directory Structure Rules

以下のディレクトリは、`.gitkeep` により空ディレクトリとして Git で追跡されていますが、生成されるデータファイル自体は追跡から除外（`.gitignore`）されています：
- `data/raw/`: ダウンロード・取得した元のデータ
- `data/processed/`: 前処理済みのデータ
- `reports/`: EDA などのスクリプトから出力されるレポートや画像データなど

新しいデータ生成や保存を行う際は、これらのディレクトリ構成を維持してください。
