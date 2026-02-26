"""
preprocess.py

Preprocess raw anime dataset files and save cleaned versions to data/processed/.

Steps:
1. Load anime.csv and rating.csv from data/raw/
2. Clean anime.csv:
   - Decode HTML entities in 'name' and 'genre'
   - Convert 'episodes' to numeric (Unknown -> NaN)
   - Drop rows with missing 'rating' or 'genre'
3. Clean rating.csv:
   - Remove rows where rating == -1 (means "watched but not rated")
   - Re-encode user_id and anime_id to contiguous integers (0-indexed)
   - Only keep ratings for anime that exist in anime.csv
4. Save to data/processed/
"""

import html
import os

import pandas as pd


def main() -> None:
    raw_dir = os.path.join("data", "raw")
    processed_dir = os.path.join("data", "processed")
    os.makedirs(processed_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 1. Load raw data
    # ------------------------------------------------------------------ #
    print("Loading anime.csv ...")
    anime_df = pd.read_csv(os.path.join(raw_dir, "anime.csv"))
    print(f"  anime.csv shape: {anime_df.shape}")

    print("Loading rating.csv ...")
    rating_df = pd.read_csv(os.path.join(raw_dir, "rating.csv"))
    print(f"  rating.csv shape: {rating_df.shape}")

    # ------------------------------------------------------------------ #
    # 2. Clean anime.csv
    # ------------------------------------------------------------------ #
    print("\nCleaning anime.csv ...")

    # Decode HTML entities (e.g. &#039; -> ')
    anime_df["name"] = anime_df["name"].apply(
        lambda x: html.unescape(str(x)) if pd.notna(x) else x
    )
    anime_df["genre"] = anime_df["genre"].apply(
        lambda x: html.unescape(str(x)) if pd.notna(x) else x
    )

    # Convert 'episodes' to numeric; 'Unknown' becomes NaN
    anime_df["episodes"] = pd.to_numeric(anime_df["episodes"], errors="coerce")

    # Drop rows with missing rating or genre (these are incomplete records)
    before = len(anime_df)
    anime_df = anime_df.dropna(subset=["rating", "genre"])
    print(f"  Dropped {before - len(anime_df)} anime rows with missing rating/genre")
    print(f"  anime_df shape after cleaning: {anime_df.shape}")

    # ------------------------------------------------------------------ #
    # 3. Clean rating.csv
    # ------------------------------------------------------------------ #
    print("\nCleaning rating.csv ...")

    # Remove unrated entries (-1 means watched but not rated)
    before = len(rating_df)
    rating_df = rating_df[rating_df["rating"] != -1].copy()
    print(f"  Removed {before - len(rating_df)} unrated (-1) entries")

    # Keep only ratings for anime that exist in the cleaned anime list
    valid_anime_ids = set(anime_df["anime_id"].tolist())
    before = len(rating_df)
    rating_df = rating_df[rating_df["anime_id"].isin(valid_anime_ids)].copy()
    print(f"  Removed {before - len(rating_df)} rows with unknown anime_id")

    # Re-encode user_id and anime_id to contiguous 0-indexed integers
    user_ids = rating_df["user_id"].unique()
    anime_ids = rating_df["anime_id"].unique()

    user_id_map = {uid: idx for idx, uid in enumerate(sorted(user_ids))}
    anime_id_map = {aid: idx for idx, aid in enumerate(sorted(anime_ids))}

    rating_df["user_idx"] = rating_df["user_id"].map(user_id_map)
    rating_df["anime_idx"] = rating_df["anime_id"].map(anime_id_map)

    # Also add anime_idx to anime_df
    anime_df = anime_df[anime_df["anime_id"].isin(anime_id_map)].copy()
    anime_df["anime_idx"] = anime_df["anime_id"].map(anime_id_map)

    print(f"  rating_df shape after cleaning: {rating_df.shape}")
    print(f"  Unique users : {rating_df['user_idx'].nunique():,}")
    print(f"  Unique anime : {rating_df['anime_idx'].nunique():,}")

    # ------------------------------------------------------------------ #
    # 4. Save
    # ------------------------------------------------------------------ #
    anime_out = os.path.join(processed_dir, "anime_processed.csv")
    rating_out = os.path.join(processed_dir, "rating_processed.csv")

    print(f"\nSaving {anime_out} ...")
    anime_df.to_csv(anime_out, index=False)

    print(f"Saving {rating_out} ...")
    rating_df.to_csv(rating_out, index=False)

    print("\nDone!")
    print(f"  anime_processed.csv : {anime_df.shape}")
    print(f"  rating_processed.csv: {rating_df.shape}")

    # Save id mappings for convenience
    user_map_df = pd.DataFrame(
        list(user_id_map.items()), columns=["user_id", "user_idx"]
    )
    anime_map_df = pd.DataFrame(
        list(anime_id_map.items()), columns=["anime_id", "anime_idx"]
    )
    user_map_df.to_csv(os.path.join(processed_dir, "user_id_map.csv"), index=False)
    anime_map_df.to_csv(os.path.join(processed_dir, "anime_id_map.csv"), index=False)
    print("  user_id_map.csv and anime_id_map.csv saved.")


if __name__ == "__main__":
    main()
