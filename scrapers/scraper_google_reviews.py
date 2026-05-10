"""
Pain Point Platform — Google Reviews Scraper
Step 06 of 17

Uses Google Places API to find businesses by category,
pulls their reviews, filters for 1-3 star ratings,
and writes raw records to Supabase raw_ingestion table.

Run: python scraper_google_reviews.py
"""

import os
import re
import time
import hashlib
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# ── setup ──────────────────────────────────────────────────────────────────────
load_dotenv("../.env.local")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── business categories to search ─────────────────────────────────────────────
# These are broad categories that surface real operational pain points
SEARCH_QUERIES = [
    "accounting firm",
    "dental clinic",
    "law firm",
    "real estate agency",
    "restaurant",
    "gym fitness center",
    "salon hair",
    "plumber",
    "electrician",
    "medical clinic",
    "pharmacy",
    "auto repair shop",
    "hotel",
    "logistics company",
    "cleaning service",
]

# Major Indian cities to cover broad geographic pain points
LOCATIONS = [
    {"lat": 28.6139, "lng": 77.2090, "name": "Delhi"},
    {"lat": 19.0760, "lng": 72.8777, "name": "Mumbai"},
    {"lat": 12.9716, "lng": 77.5946, "name": "Bangalore"},
    {"lat": 17.3850, "lng": 78.4867, "name": "Hyderabad"},
    {"lat": 13.0827, "lng": 80.2707, "name": "Chennai"},
    {"lat": 22.5726, "lng": 88.3639, "name": "Kolkata"},
]


# ── helpers ────────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Strip personal details and clean whitespace."""
    if not text:
        return ""
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[email]', text)
    text = re.sub(r'(\+?\d[\d\s\-().]{7,}\d)', '[phone]', text)
    text = re.sub(r'https?://\S+', '[url]', text)
    # remove business names that might appear (words in ALL CAPS)
    text = re.sub(r'\b[A-Z]{3,}\b', '[name]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def make_source_id(text: str) -> str:
    return hashlib.md5(f"google_reviews:{text[:200]}".encode()).hexdigest()


def insert_raw(source_id: str, raw_text: str, source_url: str):
    """Insert a record into raw_ingestion, skip if duplicate."""
    try:
        supabase.table("raw_ingestion").insert({
            "source_type": "google_reviews",
            "source_id": source_id,
            "raw_text": raw_text,
            "source_url": source_url,
            "priority": "normal",
            "status": "pending",
        }).execute()
        log.info(f"  ✓ {raw_text[:80]}...")
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            log.debug("  – duplicate skipped")
        else:
            log.warning(f"  ✗ insert error: {e}")


# ── Places API calls ───────────────────────────────────────────────────────────

def search_places(query: str, lat: float, lng: float) -> list:
    """Search for places using Places API Text Search."""
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "location": f"{lat},{lng}",
        "radius": 10000,  # 10km radius
        "key": PLACES_API_KEY,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data.get("status") == "OK":
            return data.get("results", [])
        elif data.get("status") == "ZERO_RESULTS":
            return []
        else:
            log.warning(f"  Places search error: {data.get('status')} — {data.get('error_message', '')}")
            return []
    except Exception as e:
        log.warning(f"  Places search exception: {e}")
        return []


def get_place_reviews(place_id: str, place_name: str, business_type: str) -> int:
    """Fetch reviews for a place and insert low-rated ones."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "reviews,name,url",
        "key": PLACES_API_KEY,
        "reviews_sort": "newest",
    }
    inserted = 0
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if data.get("status") != "OK":
            log.warning(f"  Details error: {data.get('status')}")
            return 0

        result = data.get("result", {})
        reviews = result.get("reviews", [])
        place_url = result.get("url", f"https://maps.google.com/?place_id={place_id}")

        for review in reviews:
            rating = review.get("rating", 5)
            if rating > 3:
                continue  # skip positive reviews

            text = review.get("text", "").strip()
            if len(text) < 30:
                continue  # too short

            cleaned = clean_text(text)
            if len(cleaned) < 30:
                continue

            # prefix with business type for context
            raw_text = f"[{business_type}] {cleaned}"
            source_id = make_source_id(raw_text)

            insert_raw(source_id, raw_text, place_url)
            inserted += 1

        return inserted

    except Exception as e:
        log.warning(f"  Reviews fetch error for {place_name}: {e}")
        return 0


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Pain Point Platform — Google Reviews Scraper ===")
    log.info(f"Started at {datetime.now().isoformat()}")

    if not PLACES_API_KEY:
        log.error("GOOGLE_PLACES_API_KEY not found in environment — check .env.local")
        return

    total_inserted = 0

    for location in LOCATIONS:
        log.info(f"\n── {location['name']} ────────────────────────────────")

        for query in SEARCH_QUERIES:
            log.info(f"  Searching: {query} in {location['name']}")

            places = search_places(query, location["lat"], location["lng"])
            log.info(f"  Found {len(places)} places")

            for place in places[:5]:  # limit to 5 places per query per city
                place_id = place.get("place_id")
                place_name = place.get("name", "Unknown")

                if not place_id:
                    continue

                log.info(f"    → {place_name}")
                count = get_place_reviews(place_id, place_name, query)
                total_inserted += count

                # polite delay to respect API rate limits
                time.sleep(0.5)

            time.sleep(1)  # delay between queries

    log.info(f"\n=== Done at {datetime.now().isoformat()} ===")
    log.info(f"Total records inserted: {total_inserted}")


if __name__ == "__main__":
    main()