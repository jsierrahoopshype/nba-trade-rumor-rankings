import pandas as pd
import re
from pathlib import Path

CSV_PATH = Path("trade_rumors.csv")
PLAYERS_TXT = Path("nba_players.txt")
PLACEHOLDER = "PLAYER"


def load_players(path: Path):
    """
    Load player names from nba_players.txt (one full name per line).
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Could not find {path}. Make sure nba_players.txt is in the repo root."
        )

    names = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name:
                continue
            # Skip any accidental header line
            if name.lower().startswith("player"):
                continue
            names.append(name)
    return names


def build_last_name_index(names):
    """
    Map last name -> set of full names, so we can fall back on last-name matches.
    """
    last_map = {}
    for full in names:
        parts = full.split()
        if len(parts) < 2:
            continue
        last = parts[-1].lower()
        last_map.setdefault(last, set()).add(full)
    return last_map


def infer_player_for_row(row, full_names, last_to_names):
    """
    For a single CSV row, infer the player name from title + snippet
    if the current value is 'PLAYER' or blank.
    """
    current = str(row.get("player", "")).strip()

    # If it's already a real name (not the placeholder), keep it.
    if current and current.upper() != PLACEHOLDER:
        return current

    title = str(row.get("title", "") or "")
    snippet = str(row.get("snippet", "") or "")
    text = f"{title} {snippet}".lower()

    # --- 1) Full-name matches ------------------------------------
    full_matches = []
    for name in full_names:
        n = name.lower()
        # Require word boundaries so we don't match partial words
        if re.search(r"\b" + re.escape(n) + r"\b", text):
            full_matches.append(name)

    if len(full_matches) == 1:
        return full_matches[0]
    elif len(full_matches) > 1:
        # If multiple, pick the longest name as a rough heuristic
        return max(full_matches, key=len)

    # --- 2) Last-name fallback -----------------------------------
    last_matches = set()
    for last, names in last_to_names.items():
        # Avoid super-short last names (Lee, May, etc.) to reduce false positives
        if len(last) < 4:
            continue
        if re.search(r"\b" + re.escape(last) + r"\b", text):
            last_matches.update(names)

    if len(last_matches) == 1:
        return next(iter(last_matches))
    elif len(last_matches) > 1:
        # Again, pick longest if more than one
        return max(last_matches, key=len)

    # If we still can't infer, keep the placeholder
    return PLACEHOLDER


def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Could not find {CSV_PATH}. Make sure you're running this from the repo root."
        )

    df = pd.read_csv(CSV_PATH)

    if "player" not in df.columns:
        raise ValueError("CSV does not have a 'player' column; cannot fix players.")

    before_placeholder = (df["player"].astype(str).str.upper() == PLACEHOLDER).sum()
    empty_before = (df["player"].astype(str).str.strip() == "").sum()
    print(f"Rows with placeholder '{PLACEHOLDER}' before fix: {before_placeholder}")
    print(f"Rows with empty player before fix: {empty_before}")

    full_names = load_players(PLAYERS_TXT)
    last_to_names = build_last_name_index(full_names)

    df["player"] = df.apply(
        lambda row: infer_player_for_row(row, full_names, last_to_names),
        axis=1,
    )

    # Ensure we never leave empty strings — if something ends up empty, put PLACEHOLDER
    df["player"] = df["player"].fillna("").astype(str)
    df.loc[df["player"].str.strip() == "", "player"] = PLACEHOLDER

    after_placeholder = (df["player"].astype(str).str.upper() == PLACEHOLDER).sum()
    empty_after = (df["player"].astype(str).str.strip() == "").sum()

    print(f"Rows with placeholder '{PLACEHOLDER}' after fix: {after_placeholder}")
    print(f"Rows with empty player after fix: {empty_after}")
    print(f"Resolved {before_placeholder - after_placeholder} placeholder rows.")

    df.to_csv(CSV_PATH, index=False)
    print(f"Saved updated CSV back to {CSV_PATH}")


if __name__ == "__main__":
    main()
