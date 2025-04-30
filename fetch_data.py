import json
import sqlite3
import time
import re
from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# === CONFIGURATION ===

# Define reforge lists
reforges = {
    "armor": [
        "Clean", "Fierce", "Heavy", "Light", "Mythic", "Pure", "Smart", "Titanic", "Wise", "Ancient", "Bustling",
        "Candied", "Cubic", "Dimensional", "Empowered", "Festive", "Hyper", "Giant", "Jaded", "Mossy", "Necrotic",
        "Perfect", "Reinforced", "Renowned", "Spiked", "Submerged", "Undead", "Loving", "Ridiculous", "Greater Spook", "Calcified"
    ],
    "weapon": [
        "Epic", "Fair", "Fast", "Gentle", "Heroic", "Legendary", "Odd", "Sharp", "Spicy", "Coldfused", "Dirty",
        "Fabled", "Gilded", "Suspicious", "Warped", "Withered", "Bulky", "Jerry's", "Fanged",
        "Awkward", "Deadly", "Fine", "Grand", "Hasty", "Neat", "Rapid", "Rich", "Unreal", "Headstrong",
        "Precise", "Spiritual"
    ],
    "misc": [
        "Stained", "Menacing", "Hefty", "Soft", "Honored", "Blended", "Astute", "Colossal", "Brilliant", "Blazing",
        "Blooming", "Fortified", "Glistening", "Rooted", "Royal", "Snowy", "Strengthened", "Waxed", "Blood-Soaked",
        "Greater Spook", "Epic", "Fair", "Fast", "Gentle", "Heroic", "Legendary", "Odd", "Sharp", "Spicy", "Salty",
        "Treacherous", "Lucky", "Stiff", "Dirty", "Chomp", "Pitchin'", "Unyielding", "Prospector's", "Excellent",
        "Sturdy", "Fortunate", "Ambered", "Auspicious", "Fleet", "Glacial", "Heated", "Lustrous", "Magnetic",
        "Mithraic", "Refined", "Scraped", "Stellar", "Fruitful", "Great", "Rugged", "Lush", "Lumberjack's",
        "Double-Bit", "Moil", "Toil", "Blessed", "Earthy", "Robust", "Zooming", "Peasant's", "Green Thumb",
        "Blessed", "Bountiful", "Beady", "Buzzing"
    ]
}

# Known special cases for duplicate reforges
special_cases = {
    "Very Wise Dragon Armor": "Wise Dragon Armor",
    "Very Strong Dragon Armor": "Strong Dragon Armor",
    "Highly Superior Dragon Armor": "Superior Dragon Armor",
    "Extremely Heavy Armor": "Heavy Armor",
    "Not So Light Armor": "Heavy Armor",
    "Thicc Heavy Armor": "Super Heavy Armor",
    "Absolutely Perfect Armor": "Perfect Armor",
    "Even More Refined Mithril Pickaxe": "Refined Mithril Pickaxe",
    "Even More Refined Titanium Pickaxe": "Refined Titanium Pickaxe",
    "Greater Greater Spook Armor": "Great Spook Armor"
}

# List of allowed unicode characters
allowed_unicode = [
    "\u2122", "\u25c6", "\u2727", "\u270e", "\u2764", "\u2618",
    "\u2742", "\u2620", "\u2741", "\u2602", "\u2748", "\u2e15",
    "\u0f15", "\u24b7", "\u00a9", "\u00ae", "\u269a", "\u00e0"
]

# Create a string of allowed unicode characters
allowed_unicode_str = ''.join(allowed_unicode)

# Allow letters, digits, space, brackets, parentheses, hyphen, apostrophe, dot, and allowed Unicode
allowed_pattern = re.compile(
    rf"[^a-zA-Z0-9 \[\]\(\)\-'\.{re.escape(allowed_unicode_str)}]",
    flags=re.UNICODE
)

ITEMS_FILE = "items.json"
DB_FILE = "prices.db"

MAX_WORKERS = 10  # Number of threads for auctions
SLEEP_BETWEEN_CYCLES = 3600  # 1 hour

# === SETUP DATABASE ===

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS auction_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        item_id TEXT,
        price INTEGER
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS bazaar_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        product_id TEXT,
        buy_price REAL,
        sell_price REAL
    )
''')

conn.commit()

# === LOAD ITEMS ===

with open(ITEMS_FILE, "r") as f:
    items_data = json.load(f)

# Map item names to IDs
name_to_id = {info["name"]: item_id for item_id, info in items_data.items()}
all_item_ids = set(items_data.keys())

# === FETCH AUCTION PAGE ===

def fetch_page(page):
    url = f"https://api.hypixel.net/v2/skyblock/auctions?page={page}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching page {page}: {e}")
        return None

# === FETCH ALL AUCTIONS ===

def fetch_all_auctions():
    print("\nFetching auction house total pages...")
    first_page_data = fetch_page(0)
    if first_page_data is None:
        print("Failed to fetch first page.")
        return []

    total_pages = first_page_data["totalPages"]
    print(f"Total auction pages to process: {total_pages}")

    all_auctions = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_page, page) for page in range(total_pages)]

        for future in as_completed(futures):
            data = future.result()
            if data:
                all_auctions.extend(data["auctions"])

    print(f"Fetched {len(all_auctions)} auctions.")
    return all_auctions

# === PROCESS UNICODE ===
def clean_item_name(name):
    cleaned = allowed_pattern.sub("", name)
    cleaned = re.sub(' +', ' ', cleaned)
    return cleaned.strip()

# === PROCESS REFORGES ===
def strip_reforge(item_name, category):
    # Check known special cases first
    if item_name in special_cases:
        return special_cases[item_name]

    reforges_list = []
    if category == "armor":
        reforges_list = reforges["armor"]
    elif category == "weapon":
        reforges_list = reforges["weapon"]
    else:
        reforges_list = reforges["misc"]

    for prefix in reforges_list:
        if item_name.startswith(prefix + " "):
            return item_name[len(prefix) + 1:]  # Remove reforge and following space
    return item_name  # No reforge found, return unchanged

# === PROCESS PETS ===
def normalize_pet_name(item_name):
    match = re.match(r"\[Lvl \d+\] (.+)", item_name)
    if match:
        pet_name = match.group(1)
        if pet_name == "Golden Dragon Egg":
            pet_name = "Golden Dragon"
        normalized_name = f"[Lvl {{LVL}}] {pet_name}"
        return normalized_name
    return item_name  # If it doesn't match, return as-is

# === PROCESS LOWEST AUCTION PRICE ===

def process_auctions(all_auctions):
    lowest_prices = {}
    skipped_items_nb = 0
    skipped_items = []
    skipped_items.append(name_to_id)

    for auction in all_auctions:
        if not auction.get("bin"):
            continue

        item_name = clean_item_name(auction.get("item_name"))
        category = auction.get("category", "").lower()
        
        # Special handling for pets
        if item_name.startswith("[Lvl "):
            normalized_name = normalize_pet_name(item_name)

            if normalized_name in name_to_id:
                item_id = name_to_id[normalized_name]
            else:
                skipped_items_nb += 1
                skipped_items.append(item_name)
                continue

        else:
            # Remove reforge prefix
            if item_name not in name_to_id:
                item_name = strip_reforge(item_name, category)
                if item_name not in name_to_id:
                    skipped_items_nb += 1
                    skipped_items.append(item_name)
                    continue

            item_id = name_to_id[item_name]
            
        price = round(auction["starting_bid"], 1)

        if item_id not in lowest_prices or price < lowest_prices[item_id]["price"]:
            lowest_prices[item_id] = {"item_id": item_id, "price": price}
            
    with open("skipped_items.json", "w") as f:
        json.dump(skipped_items, f, indent=4)
        
    print(f"Skipped {skipped_items_nb} items (not in item database) Debug in skipped_items.json.")
    return list(lowest_prices.values())

# === SAVE AUCTION DATA ===

def save_auction_data(auctions):
    timestamp_now = int(time.time())

    for auction in auctions:
        c.execute('''
            INSERT INTO auction_prices (timestamp, item_id, price)
            VALUES (?, ?, ?)
        ''', (timestamp_now, auction["item_id"], auction["price"]))

    conn.commit()
    print(f"Inserted {len(auctions)} auction items at {datetime.fromtimestamp(timestamp_now)}.")

# === FETCH BAZAAR ===

def fetch_bazaar():
    print("\nFetching Bazaar data...")
    url = "https://api.hypixel.net/v2/skyblock/bazaar"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("products", {})
    except Exception as e:
        print(f"Error fetching Bazaar: {e}")
        return {}

# === PROCESS BAZAAR DATA ===

def process_bazaar(products):
    filtered_data = []

    for product_id, product_info in products.items():
        # Only insert products that are in your item list
        if product_id not in all_item_ids:
            continue

        buy_price = round(product_info.get("quick_status", {}).get("buyPrice"), 1)
        sell_price = round(product_info.get("quick_status", {}).get("sellPrice"), 1)

        if buy_price is not None and sell_price is not None:
            filtered_data.append({
                "product_id": product_id,
                "buy_price": buy_price,
                "sell_price": sell_price
            })

    return filtered_data

# === SAVE BAZAAR DATA ===

def save_bazaar_data(products):
    timestamp_now = int(time.time())

    for product in products:
        c.execute('''
            INSERT INTO bazaar_prices (timestamp, product_id, buy_price, sell_price)
            VALUES (?, ?, ?, ?)
        ''', (timestamp_now, product["product_id"], product["buy_price"], product["sell_price"]))

    conn.commit()
    print(f"Inserted {len(products)} Bazaar items at {datetime.fromtimestamp(timestamp_now)}.")

# === MAIN LOOP ===

def detect_price_spikes():
    print("\n=== Detecting price spikes... ===")
    # Auction house
    c.execute('''
    SELECT item_id, price, timestamp FROM auction_prices
    WHERE timestamp >= datetime('now', '-2 hours')
    ORDER BY timestamp DESC
    ''')
    rows = c.fetchall()

    latest_prices = {}
    for item_id, price, timestamp in rows:
        if item_id not in latest_prices:
            latest_prices[item_id] = price

    spikes = []
    for item_id, price in latest_prices.items():
        c.execute('''
        SELECT price FROM auction_prices
        WHERE item_id = ?
        ORDER BY timestamp DESC LIMIT 5 OFFSET 1
        ''', (item_id,))
        old_prices = c.fetchall()

        if old_prices:
            avg_old_price = sum([p[0] for p in old_prices]) / len(old_prices)
            if avg_old_price > 0:
                change = (price - avg_old_price) / avg_old_price * 100
                spikes.append((item_id, change))

    spikes.sort(key=lambda x: abs(x[1]), reverse=True)
    for item_id, change in spikes[:5]:
        print(f"{item_id}: {change:+.2f}% change")
        
def main_loop():
    while True:
        print("\n=== Starting new price fetch cycle ===")

        # Auction House
        all_auctions = fetch_all_auctions()
        if all_auctions:
            filtered_auctions = process_auctions(all_auctions)
            save_auction_data(filtered_auctions)
        else:
            print("No auctions fetched.")

        # Bazaar
        bazaar_products = fetch_bazaar()
        if bazaar_products:
            filtered_bazaar = process_bazaar(bazaar_products)
            save_bazaar_data(filtered_bazaar)
        else:
            print("No Bazaar data fetched.")
            
        # Detect price spikes
        detect_price_spikes()
        
        print(f"Sleeping for {SLEEP_BETWEEN_CYCLES/60:.0f} minutes...\n")
        time.sleep(SLEEP_BETWEEN_CYCLES)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("Stopped manually.")
    finally:
        conn.close()