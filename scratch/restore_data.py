import sys
import os
import datetime

# Include parent directory in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leisu_crawler import fetch_matches
from scraper import scrape_desktop_matches
from app import merge_date_matches, DATA_FILE

def main():
    # Dates we want to restore and populate fully
    target_dates = [
        "20260630",
        "20260701",
        "20260702",
        "20260703",
        "20260704",
        "20260705"
    ]
    
    print("Starting full data restoration process...")
    for date_str in target_dates:
        print(f"\nPopulating date: {date_str}...")
        try:
            # 1. Fetch mobile matches (n_values defaults to Tier 1 & 2 but we pass more to fetch all matches)
            print("Fetching mobile matches...")
            new_matches = fetch_matches(date_str, n_values=[1, 2, 3, 4, 5, 7])
            print(f"Mobile matches fetched: {len(new_matches) if new_matches else 0}")
            
            # 2. Fetch desktop fallback matches
            print("Fetching desktop matches...")
            desktop_matches = []
            try:
                desktop_matches = scrape_desktop_matches(date_str)
            except Exception as de:
                print(f"Desktop fetch warning: {de}")
            print(f"Desktop matches fetched: {len(desktop_matches)}")
            
            # 3. Merge and save
            if not new_matches and not desktop_matches:
                print(f"Skipping merge for {date_str} because both sources returned empty (preventing wipe out)")
                continue
                
            updated_list = merge_date_matches(date_str, new_matches, desktop_matches)
            print(f"Merge successful. Updated total database size: {len(updated_list)} matches.")
            
        except Exception as e:
            print(f"Failed to populate date {date_str}: {e}")
            
    print("\nData restoration complete!")

if __name__ == '__main__':
    main()
