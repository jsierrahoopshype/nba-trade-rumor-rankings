import pandas as pd


def parse_players_from_snippet(snippet: str) -> list[str]:
    """
    Try to infer player names from the snippet text.

    The pattern we're exploiting is typically something like:

        "... HoopsHype Boston Celtics , Trade , Anfernee Simons , Sam Hauser"

    So we:
      1. Split on " , "
      2. Find the last "Trade" token
      3. Treat the tokens after "Trade" as candidate player names
      4. Filter out obvious non-names and dedupe
    """
    if not isinstance(snippet, str):
        return []

    # Split on the pattern used in the scraped snippets
    parts = [p.strip() for p in snippet.split(" , ")]

    # Find the *last* "Trade" token
    trade_idx = None
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].strip().upper() == "TRADE":
            trade_idx = i
            break

    if trade_idx is None:
        return []

    # Everything after "Trade" is potentially a player name
    meta_after = [p for p in parts[trade_idx + 1:] if p]

    players: list[str] = []
    for token in meta_after:
        # Require at least two words (first + last name)
        if len(token.split()) < 2:
            continue

        # Filter out obvious site names or junk
        upper = token.upper()
        if any(
            bad in upper
            for bad in [
                "HOOPSHYPE",
                "ESPN",
                "THE ATHLETIC",
                "YAHOO",
                "CBS",
                "SPORTS ILLUSTRATED",
                "FANSIDED",
                "BLEACHER REPORT",
            ]
        ):
            continue

        players.append(token)

    # De-duplicate while preserving order
    seen = set()
    unique_players: list[str] = []
    for p in players:
        if p not in seen:
            seen.add(p)
            unique_players.append(p)

    return unique_players


def fix_player_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    For rows where the 'player' column is empty or just 'Player',
    infer the player from the snippet and fill it in.

    We **do not** touch rows that already have a non-empty, non-'Player' value.
    """
    df = df.copy()

    for idx, row in df.iterrows():
        current = row.get("player", None)

        # Skip rows that already look good
        if isinstance(current, str) and current not in ("", "Player"):
            continue

        snippet = row.get("snippet", "")
        candidates = parse_players_from_snippet(snippet)

        # If we found at least one candidate, use the first one
        if candidates:
            df.at[idx, "player"] = candidates[0]

    return df


def main():
    csv_path = "trade_rumors.csv"

    print(f"Loading {csv_path}...")
    df = pd.read_csv(csv_path)

    before_missing = (
        df["player"].isna()
        | (df["player"] == "")
        | (df["player"] == "Player")
    ).sum()

    print(f"Rows with empty/'Player' before fix: {before_missing}")

    df_fixed = fix_player_names(df)

    after_missing = (
        df_fixed["player"].isna()
        | (df_fixed["player"] == "")
        | (df_fixed["player"] == "Player")
    ).sum()

    df_fixed.to_csv(csv_path, index=False)

    print(f"Rows with empty/'Player' after fix:  {after_missing}")
    print("Saved cleaned data back to trade_rumors.csv")


if __name__ == "__main__":
    main()
