import json
import os
import time
from datetime import datetime, timezone

RAW_FILES = ["raw_main.json", "raw_cups.json"]
OUTPUT_FILE = "quote.json"


def to_float(val):
    if val is None or isinstance(val, bool):
        return None
    try:
        num = float(str(val).replace(",", ".").strip())
        return num if 1.01 < num < 200 else None
    except ValueError:
        return None


def extract_market_rows(record):
    if not isinstance(record, dict):
        return []
    for key in ("1x2_market", "1x2", "full_time_1x2"):
        if isinstance(record.get(key), list):
            return record[key]
    for val in record.values():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            sample = val[0]
            if any(k in sample for k in ("bookmaker_name", "bookmaker", "1", "home")):
                return val
    return []


def parse_bookmaker_row(row):
    book = (
        row.get("bookmaker_name")
        or row.get("bookmaker")
        or row.get("name")
        or ""
    ).strip()
    if not book:
        return None, None

    blocked = {str(x).strip().upper() for x in (row.get("blocked_outcomes") or [])}
    o1 = None if (row.get("1_blocked") or "1" in blocked) else to_float(row.get("1") or row.get("home") or row.get("1_odd"))
    ox = None if (row.get("X_blocked") or "X" in blocked) else to_float(row.get("X") or row.get("x") or row.get("draw") or row.get("X_odd"))
    o2 = None if (row.get("2_blocked") or "2" in blocked) else to_float(row.get("2") or row.get("away") or row.get("2_odd"))

    return book, {"1": o1, "X": ox, "2": o2}


def has_any_odd(odds_dict):
    return bool(odds_dict and any(odds_dict.get(k) is not None for k in ("1", "X", "2")))


def main():
    raw_records = []
    for fname in RAW_FILES:
        if os.path.exists(fname):
            size = os.path.getsize(fname)
            print(f"Trovato {fname} ({size} byte)")
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        raw_records.extend(data)
                    elif isinstance(data, dict):
                        items = data.get("matches") or data.get("data") or data.get("items") or []
                        if isinstance(items, list):
                            raw_records.extend(items)
            except Exception as e:
                print(f"Avviso lettura {fname}: {e}")
        else:
            print(f"NON trovato: {fname}")

    print(f"Record grezzi letti in totale: {len(raw_records)}")

    seen_events = set()
    events_out = []
    all_books = set()
    skip_no_teams = 0
    skip_no_rows = 0
    skip_no_bf = 0
    skip_no_back = 0

    for rec in raw_records:
        home = (rec.get("home_team") or "").strip()
        away = (rec.get("away_team") or "").strip()
        if not home or not away:
            skip_no_teams += 1
            continue

        event_name = f"{home} - {away}"
        if event_name in seen_events:
            continue

        start_time = (
            rec.get("kickoff")
            or rec.get("match_date")
            or rec.get("start_time")
            or rec.get("local_kickoff")
        )

        rows = extract_market_rows(rec)
        if not rows:
            skip_no_rows += 1
            continue

        bf_exchange_odds = None
        bf_fallback_odds = None
        bookie_entries = []

        for row in rows:
            book, odds = parse_bookmaker_row(row)
            if not book or not odds:
                continue
            all_books.add(book)

            low = book.lower()
            if "betfair exchange" in low:
                bf_exchange_odds = odds
            elif "betfair" in low:
                bf_fallback_odds = odds
            else:
                bookie_entries.append((book, odds))

        bf_odds = (
            bf_exchange_odds
            if has_any_odd(bf_exchange_odds)
            else (bf_fallback_odds if has_any_odd(bf_fallback_odds) else None)
        )
        if not bf_odds:
            skip_no_bf += 1
            continue

        bf_runners = [
            {"name": home, "normOutcome": "1", "layOdd": bf_odds["1"], "liquidity": 0},
            {"name": "Pareggio (X)", "normOutcome": "X", "layOdd": bf_odds["X"], "liquidity": 0},
            {"name": away, "normOutcome": "2", "layOdd": bf_odds["2"], "liquidity": 0},
        ]

        back_odds = []
        for book, odds in bookie_entries:
            for outcome_key in ("1", "X", "2"):
                val = odds.get(outcome_key)
                if val is not None:
                    back_odds.append(
                        {"event": event_name, "outcome": outcome_key, "bookmaker": book, "backOdd": val}
                    )

        if back_odds:
            seen_events.add(event_name)
            events_out.append(
                {
                    "event": event_name,
                    "startTime": start_time,
                    "backOdds": back_odds,
                    "bfRunners": bf_runners,
                }
            )
        else:
            skip_no_back += 1

    print(f"Scartate -> no_teams:{skip_no_teams}, no_rows:{skip_no_rows}, no_betfair:{skip_no_bf}, no_back:{skip_no_back}")
    print(f"Bookmaker visti ({len(all_books)}): {sorted(all_books)[:25]}")

    payload = {
        "updatedAt": int(time.time() * 1000),
        "updatedIso": datetime.now(timezone.utc).isoformat(),
        "count": len(events_out),
        "events": events_out,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Generato {OUTPUT_FILE} con {len(events_out)} partite.")


if __name__ == "__main__":
    main()
