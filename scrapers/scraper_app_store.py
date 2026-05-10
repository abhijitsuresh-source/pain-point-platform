"""
Pain Point Platform — App Store Scraper
Step 07 of 17

Uses iTunes RSS API directly — no third party library needed.
Pulls low-rated reviews from App Store for relevant apps.
Writes raw records to Supabase raw_ingestion table.

Run: python scraper_app_store.py
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

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

APPS = [
    ("QuickBooks", "830566490", "accounting"),
    ("FreshBooks", "1205187423", "accounting"),
    ("Zoho Books", "1111434445", "accounting"),
    ("Asana", "489969512", "project-management"),
    ("Monday.com", "1298450641", "project-management"),
    ("Trello", "461504587", "project-management"),
    ("Jira", "1006972087", "project-management"),
    ("Salesforce", "428105816", "crm"),
    ("HubSpot", "1107711767", "crm"),
    ("Zoho CRM", "1105371921", "crm"),
    ("Slack", "618783545", "communication"),
    ("Microsoft Teams", "1113153706", "communication"),
    ("Zoom", "546505307", "communication"),
    ("Shopify", "1459148795", "ecommerce"),
    ("Square Point of Sale", "335393788", "ecommerce"),
    ("Practo", "655263069", "healthcare"),
    ("1mg", "1137191234", "healthcare"),
]

COUNTRIES = ["in", "us", "gb"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[email]', text)
    text = re.sub(r'(\+?\d[\d\s\-().]{7,}\d)', '[phone]', text)
    text = re.sub(r'https?://\S+', '[url]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def make_source_id(app_id: str, text: str) -> str:
    return hashlib.md5(f"app_store:{app_id}:{text[:150]}".encode()).hexdigest()


def insert_raw(source_id: str, raw_text: str, source_url: str):
    try:
        supabase.table("raw_ingestion").insert({
            "source_type": "app_store",
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


def scrape_app(app_name: str, app_id: str, category: str, country: str) -> int:
    inserted = 0

    for page in range(1, 6):
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"

        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                break

            data = response.json()
            entries = data.get("feed", {}).get("entry", [])

            if not entries:
                break

            reviews = entries[1:] if len(entries) > 1 else []
            if not reviews:
                break

            for review in reviews:
                try:
                    rating = int(review.get("im:rating", {}).get("label", "5"))
                except:
                    continue

                if rating > 3:
                    continue

                text = review.get("content", {}).get("label", "").strip()
                if len(text) < 30:
                    continue

                cleaned = clean_text(text)
                if len(cleaned) < 30:
                    continue

                raw_text = f"[{category}] [{app_name}] {cleaned}"
                source_id = make_source_id(app_id, cleaned)
                source_url = f"https://apps.apple.com/{country}/app/id{app_id}"

                insert_raw(source_id, raw_text, source_url)
                inserted += 1

            time.sleep(0.3)

        except Exception as e:
            log.warning(f"  [{country}] page {page} error: {e}")
            break

    return inserted


def main():
    log.info("=== Pain Point Platform — App Store Scraper ===")
    log.info(f"Started at {datetime.now().isoformat()}")

    total_inserted = 0

    for app_name, app_id, category in APPS:
        log.info(f"\n── {app_name} ({category}) ──")
        for country in COUNTRIES:
            count = scrape_app(app_name, app_id, category, country)
            log.info(f"  [{country}] inserted: {count}")
            total_inserted += count
            time.sleep(0.5)

    log.info(f"\n=== Done at {datetime.now().isoformat()} ===")
    log.info(f"Total records inserted: {total_inserted}")


if __name__ == "__main__":
    main()