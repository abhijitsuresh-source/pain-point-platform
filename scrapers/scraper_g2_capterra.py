"""
Pain Point Platform — G2 & Capterra Scraper
Step 05 of 17

Scrapes 1-3 star reviews from G2 and Capterra.
Writes raw records to Supabase raw_ingestion table.
Strips all personal details before storing.

Run: python scraper_g2_capterra.py
"""

import os
import re
import time
import hashlib
import logging
from datetime import datetime
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
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

# ── G2 categories ──────────────────────────────────────────────────────────────
G2_CATEGORIES = [
    "accounting",
    "project-management",
    "crm",
    "hr-software",
    "marketing-automation",
    "erp-systems",
    "help-desk",
    "time-tracking",
    "payroll",
    "inventory-management",
]

# ── Capterra categories ────────────────────────────────────────────────────────
CAPTERRA_CATEGORIES = [
    "accounting-software",
    "project-management-software",
    "crm-software",
    "human-resources-software",
    "marketing-software",
    "help-desk-software",
    "time-tracking-software",
    "payroll-software",
    "inventory-management-software",
    "invoicing-software",
]


# ── helpers ────────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Strip personal details and clean whitespace."""
    if not text:
        return ""
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[email]', text)
    text = re.sub(r'(\+?\d[\d\s\-().]{7,}\d)', '[phone]', text)
    text = re.sub(r'https?://\S+', '[url]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def make_source_id(source: str, text: str) -> str:
    """Generate a stable unique ID from source + content hash."""
    return hashlib.md5(f"{source}:{text[:200]}".encode()).hexdigest()


def insert_raw(source_type: str, source_id: str, raw_text: str, source_url: str):
    """Insert a record into raw_ingestion, skip if duplicate."""
    try:
        supabase.table("raw_ingestion").insert({
            "source_type": source_type,
            "source_id": source_id,
            "raw_text": raw_text,
            "source_url": source_url,
            "priority": "normal",
            "status": "pending",
        }).execute()
        log.info(f"  ✓ inserted: {raw_text[:80]}...")
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            log.debug(f"  – duplicate skipped")
        else:
            log.warning(f"  ✗ insert error: {e}")


def random_delay(min_s=2, max_s=5):
    """Polite delay between requests."""
    import random
    time.sleep(random.uniform(min_s, max_s))


# ── G2 scraper ─────────────────────────────────────────────────────────────────

def scrape_g2_product_reviews(page, product_name: str, product_url: str, max_pages: int = 2):
    """Scrape 1-3 star reviews for a specific G2 product."""
    reviews_url = product_url.rstrip("/") + "/reviews?filters%5Bnps_score%5D%5B%5D=1&filters%5Bnps_score%5D%5B%5D=2&filters%5Bnps_score%5D%5B%5D=3"

    for page_num in range(1, max_pages + 1):
        url = f"{reviews_url}&page={page_num}" if page_num > 1 else reviews_url
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            random_delay(2, 4)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            soup = BeautifulSoup(page.content(), "html.parser")
            reviews = soup.select("div[itemprop='review'], div.review-card, div[class*='review']")

            for review in reviews:
                dislike_el = review.select_one("[class*='dislike'], [class*='cons'], [data-test*='dislike']")
                body_el = review.select_one("p[itemprop='reviewBody'], div[class*='body'], p[class*='review-body']")

                text_parts = []
                if dislike_el:
                    text_parts.append(dislike_el.get_text(separator=" ", strip=True))
                if body_el:
                    text_parts.append(body_el.get_text(separator=" ", strip=True))

                raw_text = clean_text(" | ".join(filter(None, text_parts)))
                if len(raw_text) < 30:
                    continue

                source_id = make_source_id("g2", raw_text)
                insert_raw("g2", source_id, f"[{product_name}] {raw_text}", url)

        except PlaywrightTimeout:
            log.warning(f"  timeout for {product_name}")
            break
        except Exception as e:
            log.warning(f"  error for {product_name}: {e}")
            break


def scrape_g2_category(page, category: str, max_pages: int = 2):
    """Scrape low-rated reviews from a G2 category."""
    log.info(f"G2 → {category}")
    base_url = f"https://www.g2.com/categories/{category}?order=lowest_rated"

    for page_num in range(1, max_pages + 1):
        url = f"{base_url}&page={page_num}"
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            random_delay(3, 6)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            soup = BeautifulSoup(page.content(), "html.parser")
            products = soup.select("div.product-listing, div[class*='product-card']")

            if not products:
                break

            for product in products:
                name_el = product.select_one("a[class*='product-name'], a[href*='/products/']")
                if not name_el:
                    continue
                product_name = name_el.get_text(strip=True)
                product_href = name_el.get("href", "")
                if not product_href.startswith("http"):
                    product_href = f"https://www.g2.com{product_href}"
                scrape_g2_product_reviews(page, product_name, product_href)
                random_delay(2, 4)

        except Exception as e:
            log.warning(f"  G2 page {page_num} error: {e}")
            continue


# ── Capterra scraper ───────────────────────────────────────────────────────────

def scrape_capterra_product_reviews(page, product_name: str, product_url: str, max_pages: int = 2):
    """Scrape 1-3 star reviews for a specific Capterra product."""
    reviews_url = product_url.rstrip("/") + "/reviews/?sort=worst"

    for page_num in range(1, max_pages + 1):
        url = f"{reviews_url}&page={page_num}" if page_num > 1 else reviews_url
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            random_delay(2, 5)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            soup = BeautifulSoup(page.content(), "html.parser")
            reviews = soup.select("div[data-testid='review-card'], div[class*='review-card'], article[class*='review']")

            for review in reviews:
                cons_el = review.select_one("[data-testid='cons'], [class*='cons'], [class*='dislike']")
                body_el = review.select_one("p[class*='review-body'], div[class*='review-text']")

                text_parts = []
                if cons_el:
                    text_parts.append(cons_el.get_text(separator=" ", strip=True))
                if body_el:
                    text_parts.append(body_el.get_text(separator=" ", strip=True))

                raw_text = clean_text(" | ".join(filter(None, text_parts)))
                if len(raw_text) < 30:
                    continue

                source_id = make_source_id("capterra", raw_text)
                insert_raw("capterra", source_id, f"[{product_name}] {raw_text}", url)

        except PlaywrightTimeout:
            log.warning(f"  timeout for {product_name}")
            break
        except Exception as e:
            log.warning(f"  error for {product_name}: {e}")
            break


def scrape_capterra_category(page, category: str, max_pages: int = 2):
    """Scrape low-rated reviews from a Capterra category."""
    log.info(f"Capterra → {category}")

    for page_num in range(1, max_pages + 1):
        url = f"https://www.capterra.com/{category}/?sortOrder=WORST_REVIEWS&page={page_num}"
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            random_delay(3, 6)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            soup = BeautifulSoup(page.content(), "html.parser")
            products = soup.select("a[data-testid='listing-name'], a[class*='product-name']")

            if not products:
                break

            for product_el in products[:10]:
                product_name = product_el.get_text(strip=True)
                product_href = product_el.get("href", "")
                if not product_href.startswith("http"):
                    product_href = f"https://www.capterra.com{product_href}"
                scrape_capterra_product_reviews(page, product_name, product_href)
                random_delay(2, 4)

        except Exception as e:
            log.warning(f"  Capterra page {page_num} error: {e}")
            continue


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Pain Point Platform — G2/Capterra Scraper ===")
    log.info(f"Started at {datetime.now().isoformat()}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        log.info("\n── G2 ──────────────────────────────────────────")
        for category in G2_CATEGORIES:
            try:
                scrape_g2_category(page, category)
                random_delay(3, 7)
            except Exception as e:
                log.error(f"G2 {category} failed: {e}")

        log.info("\n── Capterra ────────────────────────────────────")
        for category in CAPTERRA_CATEGORIES:
            try:
                scrape_capterra_category(page, category)
                random_delay(3, 7)
            except Exception as e:
                log.error(f"Capterra {category} failed: {e}")

        browser.close()

    log.info(f"\n=== Done at {datetime.now().isoformat()} ===")


if __name__ == "__main__":
    main()
