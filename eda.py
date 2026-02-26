# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "duckdb>=1.0",
#   "rich",
# ]
# ///

"""
Anime Dataset EDA Script

Usage:
  uv run eda.py                          # コンソール出力（デフォルト）
  uv run eda.py --report html            # HTML レポートのみ
  uv run eda.py --report both            # コンソール + HTML
  uv run eda.py --report html -o out/    # 出力先ディレクトリ指定

設計方針:
  - fetch_data()   : DuckDB でクエリを実行し、純粋な Python dict を返す（データ層）
  - render_console(): dict を受け取り Rich でターミナル表示（出力層）
  - render_html()  : dict を受け取り HTML ファイルを生成（出力層）
  → 出力形式を増やしても fetch_data() には一切触れない疎結合設計
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# ══════════════════════════════════════════════════════════
# データ層 — DuckDB クエリを実行し Python dict を返す
# ══════════════════════════════════════════════════════════

def build_view(con: duckdb.DuckDBPyConnection, data_path: str) -> None:
    """CSV を DuckDB ビューとして登録する"""
    con.execute(f"""
    CREATE OR REPLACE VIEW anime AS
    SELECT
        anime_id,
        name,
        genre,
        type,
        TRY_CAST(episodes AS DOUBLE)  AS episodes,
        TRY_CAST(rating   AS DOUBLE)  AS rating,
        members
    FROM read_csv_auto('{data_path}', header=true)
    """)


def fetch_data(con: duckdb.DuckDBPyConnection) -> dict:
    """全分析クエリを実行し、結果を dict にまとめて返す"""

    # 1. 概要
    total_rows = con.execute("SELECT COUNT(*) FROM anime").fetchone()[0]
    col_info = con.execute("DESCRIBE anime").fetchall()

    # 2. 基本統計
    stats = con.execute("""
    SELECT
        COUNT(*)                                    AS count,
        ROUND(AVG(rating),   3)                     AS rating_mean,
        ROUND(STDDEV(rating),3)                     AS rating_std,
        MIN(rating)                                 AS rating_min,
        ROUND(QUANTILE_CONT(rating, 0.25), 3)       AS rating_q1,
        ROUND(QUANTILE_CONT(rating, 0.50), 3)       AS rating_median,
        ROUND(QUANTILE_CONT(rating, 0.75), 3)       AS rating_q3,
        MAX(rating)                                 AS rating_max,
        ROUND(AVG(members),  0)                     AS members_mean,
        MIN(members)                                AS members_min,
        QUANTILE_CONT(members, 0.25)::BIGINT        AS members_q1,
        QUANTILE_CONT(members, 0.50)::BIGINT        AS members_median,
        QUANTILE_CONT(members, 0.75)::BIGINT        AS members_q3,
        MAX(members)                                AS members_max,
        ROUND(AVG(episodes), 2)                     AS episodes_mean,
        MIN(episodes)                               AS episodes_min,
        QUANTILE_CONT(episodes, 0.25)::INTEGER      AS episodes_q1,
        QUANTILE_CONT(episodes, 0.50)::INTEGER      AS episodes_median,
        QUANTILE_CONT(episodes, 0.75)::INTEGER      AS episodes_q3,
        MAX(episodes)                               AS episodes_max
    FROM anime
    """).fetchone()

    # 3. 欠損値
    missing_raw = con.execute("""
    SELECT
        COUNT(*) - COUNT(name)     AS name_null,
        COUNT(*) - COUNT(genre)    AS genre_null,
        COUNT(*) - COUNT(type)     AS type_null,
        COUNT(*) - COUNT(episodes) AS episodes_null,
        COUNT(*) - COUNT(rating)   AS rating_null,
        COUNT(*) - COUNT(members)  AS members_null
    FROM anime
    """).fetchone()
    missing_labels = ["name", "genre", "type", "episodes (Unknown→NULL)", "rating", "members"]
    missing = [{"column": lbl, "null_count": v} for lbl, v in zip(missing_labels, missing_raw)]

    # 4. タイプ別分布
    type_dist = [
        {"type": r[0], "count": r[1], "avg_rating": r[2],
         "avg_members": int(r[3]) if r[3] else None}
        for r in con.execute("""
            SELECT type, COUNT(*), ROUND(AVG(rating),2), ROUND(AVG(members),0)
            FROM anime GROUP BY type ORDER BY 2 DESC
        """).fetchall()
    ]

    # 5. 高評価 Top 10
    top_rated = [
        {"rank": i, "name": r[0], "type": r[1], "rating": r[2], "members": r[3]}
        for i, r in enumerate(con.execute("""
            SELECT name, type, rating, members FROM anime
            WHERE rating IS NOT NULL AND members >= 1000
            ORDER BY rating DESC LIMIT 10
        """).fetchall(), 1)
    ]

    # 6. 人気 Top 10（members）
    top_popular = [
        {"rank": i, "name": r[0], "type": r[1], "rating": r[2], "members": r[3]}
        for i, r in enumerate(con.execute("""
            SELECT name, type, rating, members FROM anime
            ORDER BY members DESC LIMIT 10
        """).fetchall(), 1)
    ]

    # 7. ジャンル別統計 Top 20
    genre_stats = [
        {"genre": r[0], "count": r[1], "avg_rating": r[2],
         "avg_members": int(r[3]) if r[3] else None}
        for r in con.execute("""
            WITH exploded AS (
                SELECT TRIM(g.genre_val) AS genre, anime.rating, anime.members
                FROM anime, UNNEST(str_split(anime.genre, ',')) AS g(genre_val)
                WHERE anime.genre IS NOT NULL
            )
            SELECT genre, COUNT(*), ROUND(AVG(rating),2), ROUND(AVG(members),0)
            FROM exploded GROUP BY genre ORDER BY 2 DESC LIMIT 20
        """).fetchall()
    ]

    # 8. Rating ヒストグラム
    hist_raw = con.execute("""
        SELECT FLOOR(rating) AS bucket, COUNT(*) AS cnt
        FROM anime WHERE rating IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """).fetchall()
    hist = [{"range": f"{int(r[0])}–{int(r[0])+1}", "count": r[1]} for r in hist_raw]

    # 9. 最長エピソード Top 10
    longest = [
        {"name": r[0], "type": r[1], "episodes": r[2], "rating": r[3], "members": r[4]}
        for r in con.execute("""
            SELECT name, type, episodes, rating, members FROM anime
            WHERE episodes IS NOT NULL ORDER BY episodes DESC LIMIT 10
        """).fetchall()
    ]

    # 10. 相関: rating vs log10(members)
    corr = con.execute("""
        SELECT ROUND(CORR(rating, LOG(members)), 4)
        FROM anime WHERE rating IS NOT NULL AND members > 0
    """).fetchone()[0]

    scatter_raw = con.execute("""
        SELECT rating, members, name
        FROM anime
        WHERE rating IS NOT NULL AND members > 0
        USING SAMPLE 2000 ROWS
        ORDER BY rating
    """).fetchall()
    scatter_data = [{"x": r[0], "y": r[1], "label": r[2]} for r in scatter_raw]

    # 回帰係数
    reg = con.execute("""
        SELECT
            ROUND(REGR_SLOPE(LOG(members), rating), 4)     AS slope,
            ROUND(REGR_INTERCEPT(LOG(members), rating), 4) AS intercept
        FROM anime WHERE rating IS NOT NULL AND members > 0
    """).fetchone()
    reg_slope, reg_intercept = reg[0], reg[1]

    # 回帰残差によるピックアップ（members ≥ 1000）
    outliers = con.execute("""
    WITH base AS (
        SELECT
            name, type, rating, members,
            LOG(members)  AS log_m,
            REGR_INTERCEPT(LOG(members), rating) OVER () +
            REGR_SLOPE(LOG(members), rating)     OVER () * rating AS pred_log_m
        FROM anime
        WHERE rating IS NOT NULL AND members >= 1000
    ),
    residuals AS (
        SELECT *, ROUND(log_m - pred_log_m, 4) AS residual
        FROM base
    )
    SELECT name, type, rating, members, residual,
           ABS(residual) AS abs_res
    FROM residuals
    ORDER BY abs_res
    """).fetchall()

    def _row(r):
        return {"name": r[0], "type": r[1], "rating": r[2],
                "members": r[3], "residual": r[4]}

    # 残差が小さい＝相関に沖っている
    conform = [_row(r) for r in outliers[:5]]
    # 残差が大きく負＝高評価なのに人気が低い（預想外れ）
    underperform = sorted([_row(r) for r in outliers], key=lambda x: x["residual"])[:5]
    # 残差が大きく正＝評価の割に人気が高い（隠れた名作）
    overperform  = sorted([_row(r) for r in outliers], key=lambda x: -x["residual"])[:5]

    # 11. Special Pickups (Gemini AI)
    gemini_pickups = [
        {
            "category": "知的好奇心を刺激する（あるいは物議を醸した）作品",
            "items": [
                ["Hametsu no Mars", "破滅のマルス", "「クソアニメ界の金字塔」としての圧倒的な知名度と、その酷さを確認したい好奇心。"],
                ["Pupa", "pupa", "原作の期待値とアニメの完成度のギャップ、過度な規制による「伝説のがっかり感」。"],
                ["Tenkuu Danzai Skelter+Heaven", "天空断罪スケルターヘヴン", "黎明期の拙い3DCGが醸し出すシュールさが、ネタとして愛でられているため。"],
                ["Utsu Musume Sayuri", "打つ娘サユリ", "異質なビジュアルと生理的嫌悪感が、「検索してはいけない」系のミームとして定着。"],
                ["Shitcom", "Shitcom", "あまりの不条理さと内容の無さに、困惑を共有したい視聴者が後を絶たない。"],
            ]
        },
        {
            "category": "高評価だが露出が少ない（データ上の隠れた名作）作品",
            "items": [
                ["Huyao Xiao Hongniang: Yue Hong", "縁結びの妖狐ちゃん（月紅篇）", "中国アニメという枠組みへの馴染みの薄さと、視聴者による非常に高い満足度。"],
                ["Huyao Xiao Hongniang: Wangquan Fugui", "縁結びの妖狐ちゃん（王権富貴篇）", "同上。作品の質は保証されているものの、まだ広まりきっていない「至宝」。"],
                ["Future GPX Cyber Formula Sin", "新世紀GPXサイバーフォーミュラSIN", "往年の名作の完結編。ファンのみが視聴するため高評価だが、登録数は限定的。"],
                ["Madang-Eul Naon Amtalg", "庭を出た雌鶏", "韓国アニメ映画の傑作。深いテーマ性が高く評価されているが、露出が少ない。"],
                ["Future GPX Cyber Formula Zero", "新世紀GPXサイバーフォーミュラZERO", "シリーズ途中からの視聴が難しいため、登録数は伸びにくいが、作品愛が非常に強い。"],
            ]
        }
    ]

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_rows": total_rows,
        "col_info": [{"column": c[0], "type": c[1]} for c in col_info],
        "stats": {
            "count": stats[0],
            "rating":  {"mean": stats[1], "std": stats[2], "min": stats[3], "q1": stats[4],  "median": stats[5],  "q3": stats[6],  "max": stats[7]},
            "members": {"mean": int(stats[8]), "min": int(stats[9]), "q1": int(stats[10]), "median": int(stats[11]), "q3": int(stats[12]), "max": int(stats[13])},
            "episodes":{"mean": stats[14], "min": stats[15], "q1": stats[16], "median": stats[17], "q3": stats[18], "max": stats[19]},
        },
        "missing": missing,
        "type_dist": type_dist,
        "top_rated": top_rated,
        "top_popular": top_popular,
        "genre_stats": genre_stats,
        "rating_hist": hist,
        "longest": longest,
        "rating_members_corr": corr,
        "scatter_data": scatter_data,
        "reg_slope": reg_slope,
        "reg_intercept": reg_intercept,
        "corr_conform": conform,
        "corr_underperform": underperform,
        "corr_overperform": overperform,
        "gemini_pickups": gemini_pickups,
    }


# ══════════════════════════════════════════════════════════
# 出力層 A — Rich コンソール
# ══════════════════════════════════════════════════════════

def render_console(data: dict) -> None:
    console = Console()

    console.rule("[bold cyan]1. Dataset Overview")
    rprint(f"  Total rows : [bold]{data['total_rows']:,}[/bold]")
    tbl = Table(title="Column Info", header_style="bold magenta")
    tbl.add_column("Column"); tbl.add_column("Type")
    for c in data["col_info"]:
        tbl.add_row(c["column"], c["type"])
    console.print(tbl)

    console.rule("[bold cyan]2. Basic Statistics")
    s = data["stats"]
    tbl = Table(title="Numeric Stats", header_style="bold blue")
    tbl.add_column("指標"); tbl.add_column("評価 (Rating)"); tbl.add_column("リスト登録数"); tbl.add_column("話数")
    tbl.add_row("mean",   str(s["rating"]["mean"]),   f"{s['members']['mean']:,}",   str(s["episodes"]["mean"]))
    tbl.add_row("std",    f"±{s['rating']['std']}",   "—",                           "—")
    tbl.add_row("min",    str(s["rating"]["min"]),    f"{s['members']['min']:,}",    str(s["episodes"]["min"]))
    tbl.add_row("Q1",     str(s["rating"]["q1"]),     f"{s['members']['q1']:,}",     str(s["episodes"]["q1"]))
    tbl.add_row("中央値", str(s["rating"]["median"]),  f"{s['members']['median']:,}", str(s["episodes"]["median"]))
    tbl.add_row("Q3",     str(s["rating"]["q3"]),     f"{s['members']['q3']:,}",     str(s["episodes"]["q3"]))
    tbl.add_row("max",    str(s["rating"]["max"]),    f"{s['members']['max']:,}",    str(s["episodes"]["max"]))
    console.print(tbl)

    console.rule("[bold cyan]3. Missing Values")
    tbl = Table(title="Null counts", header_style="bold yellow")
    tbl.add_column("Column"); tbl.add_column("Null count")
    for m in data["missing"]:
        color = "red" if m["null_count"] > 0 else "green"
        tbl.add_row(m["column"], f"[{color}]{m['null_count']}[/{color}]")
    console.print(tbl)

    console.rule("[bold cyan]4. Anime Type Distribution")
    tbl = Table(title="By Type", header_style="bold green")
    for col in ["Type", "Count", "Avg Rating", "Avg Members"]:
        tbl.add_column(col)
    for r in data["type_dist"]:
        tbl.add_row(str(r["type"]), str(r["count"]), str(r["avg_rating"]),
                    f"{r['avg_members']:,}" if r["avg_members"] else "N/A")
    console.print(tbl)

    console.rule("[bold cyan]5. Top 10 Highest Rated Anime")
    tbl = Table(title="Top 10 Rated", header_style="bold red")
    for col in ["#", "Name", "Type", "Rating", "Members"]:
        tbl.add_column(col)
    for r in data["top_rated"]:
        tbl.add_row(str(r["rank"]), r["name"], r["type"], str(r["rating"]), f"{r['members']:,}")
    console.print(tbl)

    console.rule("[bold cyan]6. Top 10 Most Popular Anime (by members)")
    tbl = Table(title="Top 10 Popular", header_style="bold magenta")
    for col in ["#", "Name", "Type", "Rating", "Members"]:
        tbl.add_column(col)
    for r in data["top_popular"]:
        tbl.add_row(str(r["rank"]), r["name"], r["type"], str(r["rating"]), f"{r['members']:,}")
    console.print(tbl)

    console.rule("[bold cyan]7. Genre Analysis (Top 20)")
    tbl = Table(title="Top 20 Genres", header_style="bold cyan")
    for col in ["Genre", "Count", "Avg Rating", "Avg Members"]:
        tbl.add_column(col)
    for r in data["genre_stats"]:
        tbl.add_row(r["genre"], str(r["count"]), str(r["avg_rating"]),
                    f"{r['avg_members']:,}" if r["avg_members"] else "N/A")
    console.print(tbl)

    console.rule("[bold cyan]8. Rating Distribution")
    tbl = Table(title="Rating Histogram", header_style="bold white")
    tbl.add_column("Range"); tbl.add_column("Count"); tbl.add_column("Bar")
    max_cnt = max(h["count"] for h in data["rating_hist"])
    for h in data["rating_hist"]:
        bar = "█" * int(h["count"] / max_cnt * 40)
        tbl.add_row(h["range"], str(h["count"]), bar)
    console.print(tbl)

    console.rule("[bold cyan]9. Longest Running Anime (Top 10)")
    tbl = Table(title="Top 10 Longest Series", header_style="bold yellow")
    for col in ["Name", "Type", "Episodes", "Rating", "Members"]:
        tbl.add_column(col)
    for r in data["longest"]:
        tbl.add_row(r["name"], r["type"], str(r["episodes"]), str(r["rating"]), f"{r['members']:,}")
    console.print(tbl)

    console.rule("[bold cyan]10. Correlation: Rating × Members")
    rprint(f"  Pearson correlation: [bold yellow]{data['rating_members_corr']}[/bold yellow]")

    console.rule("[bold green]EDA Complete ✓")


# ══════════════════════════════════════════════════════════
# 出力層 B — HTML レポート
# ══════════════════════════════════════════════════════════

def _html_table(headers: list[str], rows: list[list], highlight_col: int | None = None) -> str:
    """ヘッダーと行データから HTML <table> を生成する"""
    ths = "".join(f"<th>{h}</th>" for h in headers)
    trs = ""
    for row in rows:
        tds = ""
        for i, cell in enumerate(row):
            cls = ' class="highlight"' if i == highlight_col else ""
            tds += f"<td{cls}>{cell}</td>"
        trs += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"


def _bar(count: int, max_count: int, total: int, width: int = 200) -> str:
    pct = count / total * 100
    bar_w = int(count / max_count * width)
    return (
        f'<div class="bar-wrap">'
        f'<div class="bar" style="width:{bar_w}px"></div>'
        f'<span>{pct:.1f}%</span>'
        f'</div>'
    )


def render_html(data: dict, output_path: Path) -> None:
    s = data["stats"]

    # ── セクション1: Overview カード
    cards_html = f"""
    <div class="cards">
      <div class="card"><div class="card-value">{data['total_rows']:,}</div><div class="card-label">総アニメ数</div></div>
      <div class="card"><div class="card-value">{s['rating']['mean']}</div><div class="card-label">平均評価</div></div>
      <div class="card"><div class="card-value">{s['members']['mean']:,}</div><div class="card-label">平均リスト登録数</div></div>
      <div class="card"><div class="card-value">{data['rating_members_corr']}</div><div class="card-label">評価 × log(リスト登録数) 相関</div></div>
    </div>"""

    # ── セクション2: column info table
    col_table = _html_table(
        ["カラム名", "型"],
        [[c["column"], c["type"]] for c in data["col_info"]]
    )

    # ── セクション3: missing values table
    missing_rows = []
    for m in data["missing"]:
        badge = (f'<span class="badge badge-warn">{m["null_count"]}</span>'
                 if m["null_count"] > 0
                 else f'<span class="badge badge-ok">0</span>')
        missing_rows.append([m["column"], badge])
    missing_table = _html_table(["カラム名", "NULL件数"], missing_rows)

    # ── セクション4: type distribution
    type_rows = [[r["type"], r["count"],
                  r["avg_rating"] or "—",
                  f"{r['avg_members']:,}" if r["avg_members"] else "—"]
                 for r in data["type_dist"]]
    type_table = _html_table(["タイプ", "件数", "平均評価", "平均リスト登録数"], type_rows, highlight_col=1)

    # ── セクション5: top rated
    rated_rows = [[r["rank"], r["name"], r["type"], r["rating"], f"{r['members']:,}"]
                  for r in data["top_rated"]]
    rated_table = _html_table(["#", "タイトル", "タイプ", "評価", "リスト登録数"], rated_rows, highlight_col=3)

    # ── セクション6: top popular
    pop_rows = [[r["rank"], r["name"], r["type"], r["rating"], f"{r['members']:,}"]
                for r in data["top_popular"]]
    pop_table = _html_table(["#", "タイトル", "タイプ", "評価", "リスト登録数"], pop_rows, highlight_col=4)

    # ── セクション7: genre stats
    genre_rows = [[r["genre"], r["count"], r["avg_rating"],
                   f"{r['avg_members']:,}" if r["avg_members"] else "—"]
                  for r in data["genre_stats"]]
    genre_table = _html_table(["ジャンル", "件数", "平均評価", "平均リスト登録数"], genre_rows, highlight_col=1)

    # ── セクション8: histogram
    total_hist = sum(h["count"] for h in data["rating_hist"])
    max_cnt = max(h["count"] for h in data["rating_hist"])
    hist_rows = [[h["range"], h["count"], _bar(h["count"], max_cnt, total_hist)]
                 for h in data["rating_hist"]]
    hist_table = _html_table(["評価帯", "件数", "分布"], hist_rows)

    # ── セクション9: longest
    long_rows = [[r["name"], r["type"], r["episodes"], r["rating"], f"{r['members']:,}"]
                 for r in data["longest"]]
    long_table = _html_table(["タイトル", "タイプ", "話数", "評価", "リスト登録数"], long_rows, highlight_col=2)

    # ── セクション11: AI分析データの準備
    gemini_map = {}
    for category in data["gemini_pickups"]:
        for item in category["items"]:
            gemini_map[item[0]] = {"ja": item[1], "reason": item[2]}

    def _enhanced_pickup_table(items, highlight_col=None):
        headers = ["タイトル", "日本語名", "タイプ", "評価", "登録数", "残差", "AI分析・理由"]
        rows = []
        for r in items:
            g = gemini_map.get(r["name"], {})
            rows.append([
                r["name"],
                g.get("ja", "—"),
                r["type"],
                r["rating"],
                f"{r['members']:,}",
                f"{r['residual']:+.3f}",
                g.get("reason", "—")
            ])
        return _html_table(headers, rows, highlight_col=highlight_col)

    # ── JSON data (埋め込み用)
    data_json = json.dumps({
        "labels": [h["range"] for h in data["rating_hist"]],
        "counts": [h["count"] for h in data["rating_hist"]],
        "genres": [g["genre"] for g in data["genre_stats"]],
        "genre_counts": [g["count"] for g in data["genre_stats"]],
        "types": [t["type"] for t in data["type_dist"] if t["type"]],
        "type_counts": [t["count"] for t in data["type_dist"] if t["type"]],
        "scatter": data["scatter_data"],
        "reg_slope": data["reg_slope"],
        "reg_intercept": data["reg_intercept"],
    }, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>アニメデータセット EDA レポート</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    :root {{
      --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
      --accent: #7c6af7; --accent2: #56cfe1; --text: #e2e8f0;
      --muted: #8892b0; --ok: #4ade80; --warn: #f59e0b;
      --border: #2d3154;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; padding: 2rem; }}
    h1 {{ font-size: 2rem; background: linear-gradient(90deg,var(--accent),var(--accent2)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:.25rem; }}
    .meta {{ color: var(--muted); font-size:.85rem; margin-bottom:2rem; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:1rem; margin-bottom:2.5rem; }}
    .card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1.25rem; text-align:center; }}
    .card-value {{ font-size:1.8rem; font-weight:700; color:var(--accent2); }}
    .card-label {{ font-size:.8rem; color:var(--muted); margin-top:.25rem; }}
    section {{ margin-bottom:3rem; }}
    h2 {{ font-size:1.1rem; font-weight:600; color:var(--accent); margin-bottom:1rem; border-left:3px solid var(--accent); padding-left:.75rem; }}
    table {{ width:100%; border-collapse:collapse; background:var(--surface); border-radius:10px; overflow:hidden; }}
    th {{ background:var(--surface2); color:var(--accent2); font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; padding:.75rem 1rem; text-align:left; }}
    td {{ padding:.65rem 1rem; border-top:1px solid var(--border); font-size:.9rem; color:var(--text); }}
    td.highlight {{ color:var(--accent2); font-weight:600; }}
    tr:hover td {{ background:var(--surface2); }}
    .badge {{ display:inline-block; padding:.2em .6em; border-radius:999px; font-size:.8rem; font-weight:600; }}
    .badge-ok   {{ background:#14532d44; color:var(--ok); }}
    .badge-warn {{ background:#78350f44; color:var(--warn); }}
    .charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:1.5rem; margin-bottom:2.5rem; }}
    .chart-box {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1.25rem; }}
    .chart-box h3 {{ font-size:.9rem; color:var(--muted); margin-bottom:1rem; }}
    .bar-wrap {{ display:flex; align-items:center; gap:.5rem; }}
    .bar {{ height:16px; background:linear-gradient(90deg,var(--accent),var(--accent2)); border-radius:4px; }}
    .bar-wrap span {{ font-size:.78rem; color:var(--muted); white-space:nowrap; }}
    footer {{ text-align:center; color:var(--muted); font-size:.8rem; margin-top:3rem; }}
  </style>
</head>
<body>
  <h1>🎌 アニメデータセット EDA レポート</h1>
  <p class="meta">
    生成日時: {data['generated_at']} &nbsp;|&nbsp; データ: data/processed/anime_processed.csv<br>
    出典: <a href="https://www.kaggle.com/datasets/CooperUnion/anime-recommendations-database" target="_blank" rel="noopener noreferrer" style="color:var(--accent2);text-decoration:none;">MyAnimeList Dataset (Kaggle)</a>
  </p>

  {cards_html}

  <div class="charts">
    <div class="chart-box"><h3>評価スコア分布</h3><canvas id="histChart"></canvas></div>
    <div class="chart-box"><h3>アニメタイプ別件数</h3><canvas id="typeChart"></canvas></div>
    <div class="chart-box" style="grid-column:1/-1"><h3>ジャンル別件数 TOP 20</h3><canvas id="genreChart"></canvas></div>
  </div>

  <section>
    <h2>1. カラム情報</h2>
    {col_table}
  </section>

  <section>
    <h2>2. 欠損値</h2>
    {missing_table}
  </section>

  <section>
    <h2>3. 基本統計量</h2>
    <table><thead><tr><th>指標</th><th>評価 (Rating)</th><th>リスト登録数</th><th>話数</th></tr></thead><tbody>
      <tr><td>平均</td>   <td class="highlight">{s['rating']['mean']}</td><td class="highlight">{s['members']['mean']:,}</td><td class="highlight">{s['episodes']['mean']}</td></tr>
      <tr><td>標準偏差</td><td>±{s['rating']['std']}</td><td>—</td><td>—</td></tr>
      <tr><td>最小値</td> <td>{s['rating']['min']}</td><td>{s['members']['min']:,}</td><td>{s['episodes']['min']}</td></tr>
      <tr><td>Q1 (25%)</td><td class="highlight">{s['rating']['q1']}</td><td class="highlight">{s['members']['q1']:,}</td><td class="highlight">{s['episodes']['q1']}</td></tr>
      <tr><td>中央値 (Q2)</td><td class="highlight">{s['rating']['median']}</td><td class="highlight">{s['members']['median']:,}</td><td class="highlight">{s['episodes']['median']}</td></tr>
      <tr><td>Q3 (75%)</td><td class="highlight">{s['rating']['q3']}</td><td class="highlight">{s['members']['q3']:,}</td><td class="highlight">{s['episodes']['q3']}</td></tr>
      <tr><td>最大値</td> <td>{s['rating']['max']}</td><td>{s['members']['max']:,}</td><td>{s['episodes']['max']}</td></tr>
    </tbody></table>
  </section>

  <section>
    <h2>4. タイプ別分布</h2>
    {type_table}
  </section>

  <section>
    <h2>5. 高評価アニメ TOP 10</h2>
    {rated_table}
  </section>

  <section>
    <h2>6. 人気アニメ TOP 10（リスト登録数順）</h2>
    {pop_table}
  </section>

  <section>
    <h2>7. 話数が多いアニメ TOP 10</h2>
    {long_table}
  </section>

  <section>
    <h2>8. ジャンル別統計 TOP 20</h2>
    {genre_table}
  </section>

  <section>
    <h2>9. 評価 × 登録数 の相関と特筆すべき作品 (AI Pickups)</h2>
    <div style="display:grid;grid-template-columns:1fr 260px;gap:1.5rem;align-items:start">
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem">
        <p style="font-size:.85rem;color:var(--muted);margin-bottom:.5rem">散布図（最大20,000件サンプル）／Y軸は対数スケール</p>
        <p style="font-size:.82rem;font-family:monospace;color:var(--accent2);margin-bottom:.75rem">
          log₁₀(リスト登録数) = {data['reg_slope']:+} × 評価 + {data['reg_intercept']}
        </p>
        <canvas id="scatterChart" style="max-height:420px"></canvas>
      </div>
      <div style="display:flex;flex-direction:column;gap:1rem">
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.5rem;text-align:center">
          <div style="font-size:2.5rem;font-weight:700;color:var(--accent2)">{data['rating_members_corr']}</div>
          <div style="font-size:.8rem;color:var(--muted);margin-top:.5rem">ピアソン相関係数<br><span style="font-size:.75rem">(rating vs log₁₀(members))</span></div>
        </div>
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem;font-size:.85rem;color:var(--muted);line-height:1.7">
          <strong style="color:var(--text)">読み方</strong><br>
          やや正の相関。リスト登録数を対数変換することでピアソン相関が強まる (<strong style="color:var(--accent2)">{data['rating_members_corr']}</strong>)。高評価作品はより大きなコミュニティを引き付ける側面も見える。
        </div>
      </div>
    </div>

    <p style="margin-top:2rem; font-size:.85rem; color:var(--muted); border-left:4px solid var(--accent); padding-left:1rem;">
      <strong>※ AIピックアップ注記:</strong> 以下のリストは統計的な「残差（予測値からのズレ）」に基づき抽出されており、日本語タイトルおよび分析理由は Gemini AI によって生成されています。
    </p>

    <div style="display:grid;grid-template-columns:1fr;gap:2.5rem;margin-top:1.5rem">
      <div>
        <h3 style="font-size:.95rem;color:#f87171;margin-bottom:.5rem">💎 高評価なのにリスト登録数が少ない（隠れた名作）</h3>
        <p style="font-size:.8rem;color:var(--muted);margin-bottom:1rem">評価の割に登録が少ない、データ上の「知る人ぞ知る」作品群です。</p>
        {_enhanced_pickup_table(data["corr_underperform"], highlight_col=4)}
      </div>
      <div>
        <h3 style="font-size:.95rem;color:#4ade80;margin-bottom:.5rem">🔥 評価の割にリスト登録数が多い（話題性・バズ作品）</h3>
        <p style="font-size:.8rem;color:var(--muted);margin-bottom:1rem">「クソアニメ」としての知名度や、強烈な個性で評価を超えて拡散された作品群です。</p>
        {_enhanced_pickup_table(data["corr_overperform"], highlight_col=4)}
      </div>
    </div>
  </section>

  <script>
  const d = {data_json};
  const chartDefaults = {{
    plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#8892b0' }}, grid: {{ color: '#2d3154' }} }},
      y: {{ ticks: {{ color: '#8892b0' }}, grid: {{ color: '#2d3154' }} }}
    }}
  }};
  new Chart(document.getElementById('histChart'), {{
    type: 'bar',
    data: {{ labels: d.labels, datasets: [{{
      label: '件数',
      data: d.counts,
      backgroundColor: 'rgba(124,106,247,0.7)',
      borderColor: '#7c6af7', borderWidth: 1, borderRadius: 4
    }}] }},
    options: {{ ...chartDefaults, indexAxis: 'y', plugins: {{ ...chartDefaults.plugins, legend: {{ display: false }} }} }}
  }});
  new Chart(document.getElementById('typeChart'), {{
    type: 'bar',
    data: {{ labels: d.types, datasets: [{{
      label: '# Anime',
      data: d.type_counts,
      backgroundColor: ['#7c6af7','#56cfe1','#4ade80','#f59e0b','#f87171','#a78bfa'],
      borderRadius: 4
    }}] }},
    options: {{ ...chartDefaults, indexAxis: 'y', plugins: {{ ...chartDefaults.plugins, legend: {{ display: false }} }} }}
  }});
  new Chart(document.getElementById('genreChart'), {{
    type: 'bar',
    data: {{ labels: d.genres, datasets: [{{
      label: '# Anime',
      data: d.genre_counts,
      backgroundColor: 'rgba(86,207,225,0.7)',
      borderColor: '#56cfe1', borderWidth: 1, borderRadius: 4
    }}] }},
    options: {{ ...chartDefaults, indexAxis: 'y', plugins: {{ ...chartDefaults.plugins, legend: {{ display: false }} }} }}
  }});
  new Chart(document.getElementById('scatterChart'), {{
    type: 'scatter',
    data: {{ datasets: [
      {{
        label: 'アニメ',
        data: d.scatter,
        backgroundColor: 'rgba(124,106,247,0.35)',
        borderColor: 'rgba(124,106,247,0.7)',
        borderWidth: 0.5,
        pointRadius: 3,
        pointHoverRadius: 6,
      }},
      {{
        label: '回帰直線',
        data: Array.from({{length: 37}}, (_, i) => {{
          const x = 1 + i * 0.25;
          return {{ x, y: Math.pow(10, d.reg_slope * x + d.reg_intercept) }};
        }}),
        type: 'line',
        borderColor: '#f59e0b',
        borderWidth: 2,
        borderDash: [6, 3],
        pointRadius: 0,
        tension: 0,
        fill: false,
      }}
    ] }},
    options: {{
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          filter: item => item.datasetIndex === 0,
          callbacks: {{
            label: ctx => `${{ctx.raw.label}} (評価: ${{ctx.raw.x}}, リスト登録数: ${{ctx.raw.y.toLocaleString()}})`
          }}
        }}
      }},
      scales: {{
        x: {{
          title: {{ display: true, text: '評価スコア', color: '#8892b0' }},
          ticks: {{ color: '#8892b0' }}, grid: {{ color: '#2d3154' }},
          min: 1, max: 10
        }},
        y: {{
          type: 'logarithmic',
          title: {{ display: true, text: 'リスト登録数（対数）', color: '#8892b0' }},
          ticks: {{ color: '#8892b0', callback: v => v >= 1000 ? (v/1000).toFixed(0)+'K' : v }},
          grid: {{ color: '#2d3154' }}
        }}
      }}
    }}
  }});
  </script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")


# ══════════════════════════════════════════════════════════
# エントリーポイント
# ══════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Anime Dataset EDA")
    parser.add_argument(
        "--report", choices=["console", "html", "both"], default="console",
        help="出力形式 (default: console)"
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=Path("reports"),
        help="HTML レポートの出力先ディレクトリ (default: reports/)"
    )
    parser.add_argument(
        "--data", type=str, default="data/processed/anime_processed.csv",
        help="CSV ファイルパス (default: data/processed/anime_processed.csv)"
    )
    args = parser.parse_args()

    con = duckdb.connect()
    build_view(con, args.data)

    print("🔍 Fetching data...", file=sys.stderr)
    data = fetch_data(con)
    con.close()

    if args.report in ("console", "both"):
        render_console(data)

    if args.report in ("html", "both"):
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = args.output_dir / f"anime_eda_{ts}.html"
        latest_file = args.output_dir / "anime_eda_latest.html"
        render_html(data, out_file)
        latest_file.write_text(out_file.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\n✅ HTML report saved → {out_file}", file=sys.stderr)
        print(f"✅ Latest    updated → {latest_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
