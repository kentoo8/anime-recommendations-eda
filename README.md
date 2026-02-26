# anime-recommendations-eda

[MyAnimeList Dataset (Kaggle)](https://www.kaggle.com/datasets/CooperUnion/anime-recommendations-database) を使ったアニメデータの探索的データ分析（EDA）リポジトリです。

## ディレクトリ構成

```
anime-recommendations-eda/
├── data/
│   ├── raw/                  # 元データ（Kaggle からダウンロード）
│   │   ├── anime.csv
│   │   └── rating.csv
│   └── processed/            # preprocess.py が生成する前処理済みデータ
│       ├── anime_processed.csv
│       ├── rating_processed.csv
│       ├── anime_id_map.csv
│       └── user_id_map.csv
├── reports/                  # eda.py が生成する HTML レポート
├── preprocess.py             # 前処理スクリプト
├── eda.py                    # EDA スクリプト
└── pyproject.toml
```

## セットアップ

[uv](https://github.com/astral-sh/uv) を使います。

```bash
# uv のインストール（未インストールの場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存パッケージのインストール
uv sync
```

## 使い方

### 1. 前処理

raw データを `data/processed/` に生成します。

```bash
uv run preprocess.py
```

**前処理の内容：**
- `name` / `genre` の HTML エンティティをデコード
- `episodes` を数値に変換（`Unknown` → `NaN`）
- `rating` / `genre` が欠損しているアニメ行を削除
- `rating.csv` から未評価（`-1`）エントリを除去
- `user_id` / `anime_id` を 0-indexed の連番に再エンコード

### 2. EDA

```bash
# コンソール出力（デフォルト）
uv run eda.py

# HTML レポートのみ生成
uv run eda.py --report html

# コンソール + HTML 両方
uv run eda.py --report both

# 出力先ディレクトリを指定
uv run eda.py --report html -o out/

# raw データで実行（前処理前の状態を確認）
uv run eda.py --data data/raw/anime.csv
```

生成された HTML レポートは `reports/anime_eda_latest.html` で常に最新版を参照できます。

## EDA の内容

| セクション | 内容 |
|---|---|
| 1. カラム情報 | 各カラムの型 |
| 2. 欠損値 | カラムごとの NULL 件数 |
| 3. 基本統計量 | rating / members / episodes の平均・分位数など |
| 4. タイプ別分布 | TV / Movie / OVA などの件数・平均評価 |
| 5. 高評価 TOP 10 | rating 上位（members ≥ 1,000 絞り込み） |
| 6. 人気 TOP 10 | members（リスト登録数）上位 |
| 7. 話数が多い TOP 10 | episodes 上位 |
| 8. ジャンル別統計 | 件数・平均評価・平均 members（TOP 20）|
| 9. 評価 × 人気 相関 | 散布図・回帰直線・残差ピックアップ |

## raw vs processed データについて

`preprocess.py` は `rating` / `genre` が欠損している行を**削除**してから保存します。
そのため processed データで EDA を実行すると欠損値はほぼゼロになります。

| 目的 | 推奨データ |
|---|---|
| データ品質・欠損の全体把握 | `data/raw/anime.csv` |
| モデルが実際に使うデータの分析 | `data/processed/anime_processed.csv`（デフォルト）|

## 技術スタック

- [DuckDB](https://duckdb.org/) — インメモリ SQL エンジン（クエリ処理）
- [Rich](https://github.com/Textualize/rich) — ターミナル出力の整形
- [Chart.js](https://www.chartjs.org/) — HTML レポートのグラフ描画
- [uv](https://github.com/astral-sh/uv) — Python パッケージ・スクリプト管理
