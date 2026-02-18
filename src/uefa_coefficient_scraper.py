"""
Scrape UEFA country coefficients from the official UEFA rankings page.

The script fetches association coefficient data for a given year and saves it
to a CSV file. The coefficient represents the strength of each national
association based on their clubs' performance in UEFA competitions.

Usage:
    # Fetch coefficients for default year (2026)
    python src/uefa_coefficient_scraper.py
    
    # Fetch coefficients for a specific year
    python src/uefa_coefficient_scraper.py 2025
    
    # Use programmatically
    from src.uefa_coefficient_scraper import fetch_uefa_coefficients, get_coefficient_for_association
    
    df = fetch_uefa_coefficients(2026)
    england_coeff = get_coefficient_for_association(df, "England")

Note:
    Uses Playwright (headless Chromium) to fetch the page so UEFA's JS-rendered
    content and connection behavior are handled reliably. Install with:
      pip install playwright && python -m playwright install chromium
"""

from pathlib import Path
import re
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

# Base directory for all CSV output (relative to where the script is run).
# Files are written under data/{year}/, e.g. data/2026/uefa_coefficients_2026.csv
DATA_DIR = Path("data")

# Default year to fetch (can be overridden via command line or function parameter)
# Page shows e.g. 2026; we use year - 1 for output paths (e.g. 2025 for data/2025/).
DEFAULT_YEAR = 2026

# Map UEFA association/country name to league name (top 5 leagues, matches understat codes).
ASSOCIATION_TO_LEAGUE = {
    "England": "EPL",
    "Spain": "La_liga",
    "Germany": "Bundesliga",
    "Italy": "Serie_A",
    "France": "Ligue_1",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_html_with_playwright(url: str, timeout_ms: int = 60_000) -> str:
    """
    Fetch fully-rendered HTML using Playwright (headless Chromium).
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Playwright is required. "
            "Install with: pip install playwright && python -m playwright install chromium"
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        html = page.content()
        context.close()
        browser.close()
        return html


def _add_league_column(df: pd.DataFrame) -> pd.DataFrame:
    """Add League column by mapping Association to league name (EPL, La_liga, etc.)."""
    def map_assoc(a: str) -> str:
        if pd.isna(a):
            return ""
        a = str(a).strip()
        for country, league in ASSOCIATION_TO_LEAGUE.items():
            if country.lower() in a.lower():
                return league
        return ""

    df = df.copy()
    df["League"] = df["Association"].map(map_assoc)
    return df


def fetch_uefa_coefficients(year: int = DEFAULT_YEAR) -> pd.DataFrame:
    """
    Fetch UEFA country coefficients for the given page year.

    The page displays a year (e.g. 2026); we use year - 1 for output paths
    so that data aligns with season start (e.g. 2025 for 2025/26).

    Args:
        year: The year as shown on the UEFA page (default: DEFAULT_YEAR)

    Returns:
        DataFrame with columns: Rank, Association, League, Coefficient.
    """
    url = f"https://www.uefa.com/nationalassociations/uefarankings/country/?year={year}"
    print(f"Fetching UEFA coefficients for year {year} from {url} (Playwright)...")
    html = _fetch_html_with_playwright(url)
    soup = BeautifulSoup(html, "html.parser")
    
    # UEFA country page uses AG Grid (ag-root, role="grid"); parse it first
    df_ag = _parse_ag_grid_coefficients(soup, year)
    if df_ag is not None and len(df_ag) > 0:
        return _add_league_column(df_ag)

    # Fallback: try classic HTML table
    table = None
    table_selectors = [
        "table.rankings-table",
        "table.table",
        "table",
        ".rankings-table",
        "[data-module='rankings']",
    ]
    for selector in table_selectors:
        table = soup.select_one(selector)
        if table:
            print(f"Found table using selector: {selector}")
            break
    if not table:
        tables = soup.find_all("table")
        if tables:
            print(f"Found {len(tables)} table(s), using the first one")
            table = tables[0]
    if table:
        return _add_league_column(_parse_html_table(table, year))

    # No table found: try JSON in script tags, then fail with debug file
    import json as _json
    script_patterns = [
        ("script", {"type": "application/json"}),
        ("script", {"type": "application/ld+json"}),
        ("script", {}),
    ]
    for tag_name, attrs in script_patterns:
        script_tags = soup.find_all(tag_name, attrs)
        for script in script_tags or []:
            if not script.string:
                continue
            try:
                script_content = script.string.strip()
                json_match = re.search(r'\{.*\}', script_content, re.DOTALL)
                if json_match:
                    script_content = json_match.group(0)
                data = _json.loads(script_content)
                df = _parse_json_coefficients(data, year)
                if df is not None and len(df) > 0:
                    return _add_league_column(df)
            except (_json.JSONDecodeError, KeyError, ValueError):
                continue
    output_year = year - 1
    debug_dir = DATA_DIR / str(output_year)
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_file = debug_dir / f"uefa_page_debug_{output_year}.html"
    with open(debug_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved page HTML to {debug_file} for debugging")
    raise RuntimeError(
        "Could not find coefficient table on the page. "
        f"The page structure may have changed. Saved HTML to {debug_file} for inspection."
    )


def _parse_ag_grid_coefficients(soup: "BeautifulSoup", year: int) -> Optional[pd.DataFrame]:
    """
    Parse UEFA country coefficients from the page's AG Grid (ag-root, role="grid").
    Grid has columns: position, member (association), season-YYYY, points, clubs.
    We use position, member, and points (total coefficient).
    """
    grid = soup.find("div", role="grid", class_=re.compile(r"ag-root"))
    if not grid:
        return None
    rows = grid.find_all("div", role="row", attrs={"row-index": True})
    if not rows:
        return None
    result = []
    for row in rows:
        cells = {c.get("col-id"): c for c in row.find_all("div", role="gridcell")}
        if not cells:
            continue
        pos_cell = cells.get("position")
        member_cell = cells.get("member")
        points_cell = cells.get("points")
        if not (pos_cell and member_cell and points_cell):
            continue
        pos_text = "".join(pos_cell.stripped_strings)
        pts_text = "".join(points_cell.stripped_strings)
        # Association: <div slot="primary"><span>England</span></div> or badge title
        assoc = ""
        primary = member_cell.find("div", attrs={"slot": "primary"})
        if primary:
            span = primary.find("span")
            if span:
                assoc = span.get_text(strip=True)
        if not assoc:
            badge = member_cell.find(attrs={"title": True})
            if badge:
                assoc = (badge.get("title") or "").strip()
        if not assoc:
            assoc = " ".join(member_cell.stripped_strings)
        try:
            rank = int(pos_text)
            coeff = float(pts_text.replace(",", "."))
        except (ValueError, TypeError):
            continue
        result.append({"Rank": rank, "Association": assoc, "Coefficient": coeff})
    if not result:
        return None
    df = pd.DataFrame(result).sort_values("Rank").reset_index(drop=True)
    print(f"Parsed {len(df)} associations from AG Grid")
    return df


def _parse_html_table(table, year: int) -> pd.DataFrame:
    """
    Parse coefficient data from an HTML table.
    Handles various table structures commonly used by UEFA.
    """
    rows = []
    tbody = table.find("tbody") or table
    
    # Try to identify header row to understand column structure
    header_row = table.find("thead")
    headers = []
    if header_row:
        header_cells = header_row.find_all(["th", "td"])
        headers = [" ".join(cell.stripped_strings).lower() for cell in header_cells]
    
    row_index = 0
    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        
        # Extract text from cells, handling nested elements
        cell_texts = []
        for cell in cells:
            # Get text, removing extra whitespace
            text = " ".join(cell.stripped_strings)
            # Remove common non-breaking spaces and special characters
            text = text.replace("\xa0", " ").strip()
            cell_texts.append(text)
        
        if len(cell_texts) < 2:
            continue
        
        # Try to identify columns
        # Common structure: Rank, Association/Country, Coefficient, [season columns]
        row_data = {}
        
        # Use headers if available to map columns
        if headers and len(headers) == len(cell_texts):
            for i, (header, value) in enumerate(zip(headers, cell_texts)):
                if "rank" in header or header == "#" or header == "pos":
                    try:
                        row_data["Rank"] = int(value)
                    except ValueError:
                        pass
                elif "association" in header or "country" in header or "nation" in header:
                    row_data["Association"] = value
                elif "coefficient" in header or "coeff" in header or "points" in header:
                    try:
                        # Extract number, handling commas as decimal separators
                        num_str = value.replace(",", ".").replace(" ", "")
                        match = re.search(r"\d+\.?\d*", num_str)
                        if match:
                            row_data["Coefficient"] = float(match.group())
                    except (ValueError, AttributeError):
                        pass
        
        # Fallback: try to infer columns by position and content
        if not row_data:
            # First cell is usually rank
            try:
                rank = int(cell_texts[0])
                row_data["Rank"] = rank
            except ValueError:
                # Might be a header row
                if cell_texts[0].lower() in ["rank", "position", "#", "pos", "ranking"]:
                    continue
            
            # Second cell is usually association/country name
            if len(cell_texts) > 1:
                row_data["Association"] = cell_texts[1]
            
            # Look for coefficient value (usually a decimal number)
            # Check all remaining cells
            for text in cell_texts[2:]:
                # Try to extract a decimal number
                # Handle both comma and dot as decimal separators
                num_str = text.replace(",", ".").replace(" ", "")
                match = re.search(r"\d+\.\d+|\d+", num_str)
                if match:
                    try:
                        coefficient = float(match.group())
                        # Coefficient is usually between 0 and 100 for associations
                        if 0 <= coefficient <= 200:
                            row_data["Coefficient"] = coefficient
                            break
                    except ValueError:
                        continue
        
        # If we found rank and association, add the row
        if "Rank" in row_data and "Association" in row_data:
            rows.append(row_data)
            row_index += 1
    
    if not rows:
        raise RuntimeError("Could not extract coefficient data from table.")
    
    df = pd.DataFrame(rows)
    
    # Ensure Rank column exists and sort by it
    if "Rank" in df.columns:
        df = df.sort_values("Rank").reset_index(drop=True)
    
    return df


def _parse_json_coefficients(data: dict, year: int) -> pd.DataFrame:
    """
    Parse coefficient data from JSON structure (if available).
    """
    rows = []
    
    def extract_from_dict(obj, path=""):
        """Recursively search for coefficient data in nested structures."""
        if isinstance(obj, dict):
            # Check if this dict looks like a ranking entry
            has_rank = any(k in obj for k in ["rank", "position", "ranking", "pos"])
            has_assoc = any(k in obj for k in ["association", "country", "name", "associationName", "countryName"])
            has_coeff = any(k in obj for k in ["coefficient", "coeff", "points", "score"])
            
            if has_rank and has_assoc:
                row = {}
                # Extract rank
                for key in ["rank", "position", "ranking", "pos"]:
                    if key in obj:
                        try:
                            row["Rank"] = int(obj[key])
                            break
                        except (ValueError, TypeError):
                            pass
                
                # Extract association name
                for key in ["association", "country", "name", "associationName", "countryName", "title"]:
                    if key in obj:
                        row["Association"] = str(obj[key])
                        break
                
                # Extract coefficient
                for key in ["coefficient", "coeff", "points", "score", "value"]:
                    if key in obj:
                        try:
                            row["Coefficient"] = float(obj[key])
                            break
                        except (ValueError, TypeError):
                            pass
                
                if len(row) >= 2:  # At least rank and association
                    rows.append(row)
            
            # Recursively search nested structures
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    extract_from_dict(value, f"{path}.{key}" if path else key)
        
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                extract_from_dict(item, f"{path}[{i}]" if path else f"[{i}]")
    
    # Try common JSON keys first
    if isinstance(data, dict):
        # Check top-level keys
        for key in ["rankings", "associations", "coefficients", "data", "results", "items"]:
            if key in data:
                extract_from_dict(data[key])
                if rows:
                    break
        
        # If no rows found, search entire structure
        if not rows:
            extract_from_dict(data)
    
    elif isinstance(data, list):
        extract_from_dict(data)
    
    if rows:
        df = pd.DataFrame(rows)
        # Ensure Rank column exists and sort by it
        if "Rank" in df.columns:
            df = df.sort_values("Rank").reset_index(drop=True)
        return df
    else:
        return None


def get_coefficient_for_association(
    df: pd.DataFrame, 
    association_name: str, 
    fuzzy_match: bool = True
) -> float:
    """
    Get the coefficient for a specific association/league.
    
    Args:
        df: DataFrame with coefficient data
        association_name: Name of the association/league (e.g., "England", "Spain", "Italy")
        fuzzy_match: If True, try fuzzy matching for association names
        
    Returns:
        Coefficient value for the association, or None if not found
    """
    # If DataFrame has League column and we're given a league code, use it directly
    if "League" in df.columns and association_name and (df["League"] == association_name).any():
        row = df.loc[df["League"] == association_name].iloc[0]
        return row["Coefficient"]
    # Common league to association mappings
    league_to_association = {
        "EPL": ["England", "English", "Premier League"],
        "Premier League": ["England", "English"],
        "La Liga": ["Spain", "Spanish"],
        "La_liga": ["Spain", "Spanish"],
        "Bundesliga": ["Germany", "German"],
        "Serie A": ["Italy", "Italian"],
        "Serie_A": ["Italy", "Italian"],
        "Ligue 1": ["France", "French"],
        "Ligue_1": ["France", "French"],
    }
    
    # Check if it's a league code
    if association_name in league_to_association:
        possible_names = league_to_association[association_name]
    else:
        possible_names = [association_name]
    
    # Try exact match first
    for name in possible_names:
        mask = df["Association"].str.contains(name, case=False, na=False)
        matches = df[mask]
        if len(matches) > 0:
            return matches.iloc[0]["Coefficient"]
    
    # Try fuzzy matching if enabled
    if fuzzy_match:
        from difflib import get_close_matches
        association_names = df["Association"].tolist()
        matches = get_close_matches(association_name, association_names, n=1, cutoff=0.6)
        if matches:
            mask = df["Association"] == matches[0]
            return df[mask].iloc[0]["Coefficient"]
    
    return None


def save_coefficients(df: pd.DataFrame, year: int, output_dir: Optional[Path] = None) -> Path:
    """
    Save coefficient DataFrame to CSV under data/{output_year}/.
    Uses year - 1 as output year (page year 2026 -> data/2025/).
    
    Args:
        df: DataFrame with coefficient data
        year: Page year (e.g. 2026); saved as year - 1 (e.g. 2025)
        output_dir: Override directory (default: data/{year-1}/)
        
    Returns:
        Path to the saved CSV file
    """
    output_year = year - 1
    if output_dir is None:
        output_dir = DATA_DIR / str(output_year)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"uefa_coefficients_{output_year}.csv"
    df.to_csv(filename, index=False, encoding="utf-8")
    print(f"Saved coefficients to {filename}")
    return filename


def main():
    """
    Main function to fetch and save UEFA coefficients.
    """
    import sys
    
    # Allow year to be specified as command line argument
    year = DEFAULT_YEAR
    if len(sys.argv) > 1:
        try:
            year = int(sys.argv[1])
        except ValueError:
            print(f"Invalid year: {sys.argv[1]}. Using default year {DEFAULT_YEAR}")
            year = DEFAULT_YEAR
    
    try:
        df = fetch_uefa_coefficients(year)
        output_year = year - 1
        # Display preview
        print(f"\nFound {len(df)} associations (saving as year {output_year})")
        print("\nTop 10 associations:")
        print(df.head(10).to_string(index=False))
        # Save to CSV under data/{year-1}/
        save_coefficients(df, year)
        
    except Exception as e:
        print(f"Error fetching UEFA coefficients: {e}")
        raise


if __name__ == "__main__":
    main()
