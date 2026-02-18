import json
from pathlib import Path

import pandas as pd
import requests

# Use Understat's JSON league endpoint instead of scraping HTML.
# Adjust `SEASON_START_YEAR` if you want a different starting season.
# The script will automatically grab data for the last 5 seasons
# (inclusive of `SEASON_START_YEAR`) and place each season in its
# own set of columns in a single wide DataFrame.
SEASON_START_YEAR = 2025

# Leagues that correspond to the tabs on understat.com:
#   - EPL
#   - La liga
#   - Bundesliga
#   - Serie A
#   - Ligue 1
#
# Understat's internal league codes (used in the JSON endpoint) are:
#   EPL, La_liga, Bundesliga, Serie_A, Ligue_1
LEAGUE_CODES = {
    "EPL": "EPL",
    "La_liga": "La liga",
    "Bundesliga": "Bundesliga",
    "Serie_A": "Serie A",
    "Ligue_1": "Ligue 1",
}

# Base directory for all CSV output (relative to where the script is run).
# Files are written under data/{year}/, e.g. data/2025/EPL_players_2025.csv
DATA_DIR = Path("data")

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    # This header makes Understat return JSON payloads (as used by the
    # official `understat` Python package) instead of full HTML.
    "X-Requested-With": "XMLHttpRequest",
}


def extract_understat_teams_table(payload: dict) -> pd.DataFrame:
    """
    Extract the EPL xG league table from the Understat page.

    We call Understat's JSON API (`/getLeagueData/...`), which returns
    a structure similar to what the official `understat` library uses.
    From the payload we:

      - pull the per-team match histories
      - aggregate them to season totals that mirror the league table
        on the site.
    """
    # Different Understat deployments have used slightly different keys;
    # support both the current `teams` shape and an older `teamsData`.
    raw = None
    if isinstance(payload, dict):
        if "teams" in payload:
            raw = payload["teams"]
        elif "teamsData" in payload:
            # Some payloads may nest teams under `teamsData["teams"]`.
            td = payload["teamsData"]
            if isinstance(td, dict) and "teams" in td:
                raw = td["teams"]

    if raw is None:
        raise RuntimeError("Could not find teams data in Understat payload.")

    rows = []
    # raw is a dict keyed by team id; values hold metadata and match history
    for team in raw.values():
        history = team.get("history", [])

        matches = len(history)
        wins = sum(1 for m_ in history if m_.get("result") == "w")
        draws = sum(1 for m_ in history if m_.get("result") == "d")
        loses = sum(1 for m_ in history if m_.get("result") == "l")

        def s(field: str) -> float:
            return sum(float(m_.get(field, 0) or 0) for m_ in history)

        goals = s("scored")
        goals_against = s("missed")
        points = s("pts")
        xg = s("xG")
        npxg = s("npxG")
        xga = s("xGA")
        npxga = s("npxGA")
        xpts = s("xpts")

        row = {
            "Team": team.get("title"),
            "M": matches,
            "W": wins,
            "D": draws,
            "L": loses,
            "G": goals,
            "GA": goals_against,
            "PTS": points,
            "xG": xg,
            "NPxG": npxg,
            "xGA": xga,
            "NPxGA": npxga,
            "NPxGD": npxg - npxga,
            "xPTS": xpts,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    # Order by points like the league table
    df = df.sort_values("PTS", ascending=False).reset_index(drop=True)
    df.insert(0, "Pos", range(1, len(df) + 1))
    return df


def extract_understat_players_table(payload: dict) -> pd.DataFrame:
    """
    Extract raw per-player stats for the league and season from the
    same Understat JSON payload.

    We:
      - locate the players block in the payload
      - normalise it into a list of dicts
      - return it directly as a DataFrame (one row per player).
    """
    raw = None
    if isinstance(payload, dict):
        if "players" in payload:
            raw = payload["players"]
        elif "playersData" in payload:
            pd_block = payload["playersData"]
            if isinstance(pd_block, dict) and "players" in pd_block:
                raw = pd_block["players"]

    if raw is None:
        raise RuntimeError("Could not find players data in Understat payload.")

    # Some payloads may use a dict keyed by player id.
    if isinstance(raw, dict):
        rows = list(raw.values())
    else:
        rows = raw

    # Use json_normalize so that any nested structures (e.g. grouped or
    # per-90 stats) are flattened into separate columns, giving us every
    # available player statistic in one wide table.
    return pd.json_normalize(rows, sep=".")


def fetch_league_payload(league_code: str, season_start_year: int) -> dict:
    """
    Call Understat's JSON endpoint for a given league and season.
    """
    url = f"https://understat.com/getLeagueData/{league_code}/{season_start_year}"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return json.loads(resp.text)


def main():
    """
    Fetch xG stats for all the main Understat league tabs:
      - EPL
      - La liga
      - Bundesliga
      - Serie A
      - Ligue 1

    For each league, we:

      - fetch data for the last 5 seasons (inclusive of SEASON_START_YEAR)
      - build a single wide team-level DataFrame where:
          * rows = teams
          * columns = stats for each season, with the season year
            appended to the column name (e.g. `PTS_2025`, `xG_2025`,
            `PTS_2024`, `xG_2024`, ...)
      - also save per-season player stats as before.

    Example output paths:
      - data/2025/EPL_players_2025.csv (per-season player stats)
      - data/2025/EPL_teams_xg_last_5_seasons.csv (wide team table)
    """
    seasons = list(range(SEASON_START_YEAR, SEASON_START_YEAR - 5, -1))

    for league_code, league_label in LEAGUE_CODES.items():
        print(f"Fetching data for {league_label} ({league_code}) for seasons: {seasons}")

        wide_teams_df = None

        for season in seasons:
            print(f"  Season {season}...")
            payload = fetch_league_payload(league_code, season)
            df_teams = extract_understat_teams_table(payload)
            df_players = extract_understat_players_table(payload)

            # Save per-season player stats under data/{season}/
            season_dir = DATA_DIR / str(season)
            season_dir.mkdir(parents=True, exist_ok=True)
            players_filename = season_dir / f"{league_code}_players_{season}.csv"
            df_players.to_csv(players_filename, index=False, encoding="utf-8")

            # Prepare team DataFrame for wide format:
            # - use Team as index
            # - drop positional column (Pos) since it changes season to season
            # - append season suffix to all stat columns
            df_teams_season = df_teams.set_index("Team").drop(columns=["Pos"])
            df_teams_season = df_teams_season.add_suffix(f"_{season}")

            if wide_teams_df is None:
                wide_teams_df = df_teams_season
            else:
                # Outer join in case team membership changes between seasons
                wide_teams_df = wide_teams_df.join(df_teams_season, how="outer")

        # Once all seasons are processed for a league, save the wide team table under data/{SEASON_START_YEAR}/
        if wide_teams_df is not None:
            wide_teams_df = wide_teams_df.reset_index()  # bring Team back as a column
            start_year_dir = DATA_DIR / str(SEASON_START_YEAR)
            start_year_dir.mkdir(parents=True, exist_ok=True)
            teams_filename = start_year_dir / f"{league_code}_teams_xg_last_{len(seasons)}_seasons.csv"
            wide_teams_df.to_csv(teams_filename, index=False, encoding="utf-8")

            print(f"  Saved wide team table ({len(wide_teams_df)} rows) to {teams_filename}")
            # Show a few high-signal columns for the most recent and earliest seasons
            recent = seasons[0]
            earliest = seasons[-1]
            cols_to_preview = [
                "Team",
                f"PTS_{recent}",
                f"xG_{recent}",
                f"xGA_{recent}",
                f"xPTS_{recent}",
            ]
            for extra in [
                f"PTS_{earliest}",
                f"xG_{earliest}",
                f"xGA_{earliest}",
                f"xPTS_{earliest}",
            ]:
                if extra in wide_teams_df.columns:
                    cols_to_preview.append(extra)

            print(wide_teams_df[cols_to_preview].head())
            print("-" * 60)


if __name__ == "__main__":
    main()