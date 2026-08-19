import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


INACTIVE_RAID_STATUSES = frozenset({
    "archiviert", "archive", "archived",
    "gelöscht", "geloescht", "deleted",
    "abgesagt", "cancelled", "canceled",
})
TWENTY_PLAYER_RAIDS = frozenset({"AQ20", "ZG", "ZG-MITTWOCH", "ZG-PRIME", "ZG-LATE"})


def clean(value):
    return str(value or "").strip()


def normalize_guild_slug(value, default="lichtloot"):
    return clean(value).lower() or clean(default).lower() or "lichtloot"


def normalize_raid(value):
    text = re.sub(r"[^A-Z0-9]+", "", clean(value).upper())
    if text in {"ZGMITTWOCH", "ZULGURUBMITTWOCH"}:
        return "ZG-MITTWOCH"
    if text in {"ZGPRIME", "ZULGURUBPRIME"} or text.startswith("ZGRAIDPRIME"):
        return "ZG-PRIME"
    if text in {"ZGLATE", "ZULGURUBLATE"} or text.startswith("ZGRAIDLATE") or text.startswith("ZGLATENIGHT"):
        return "ZG-LATE"
    if text == "MOLTENCORE" or text.startswith("MOLTENCORE"):
        return "MC"
    if text == "BLACKWINGLAIR" or text.startswith("BLACKWINGLAIR"):
        return "BWL"
    if text in {"AQ", "AHNQIRAJ", "AHNQIRAJ40"}:
        return "AQ40"
    if text in {"AQ20", "AHNQIRAJ20", "RUINSOFAHNQIRAJ"} or text.startswith(("AQ20", "AHNQIRAJ20")):
        return "AQ20"
    if text in {"ZULGURUB", "ZG20"} or text.startswith(("ZGRAID", "ZG20", "ZULGURUB")):
        return "ZG"
    if text == "NAXXRAMAS" or text.startswith("NAXXRAMAS"):
        return "NAXX"
    return text or "RAID"


def canonical_raid_date(value):
    text = clean(value)
    iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if iso_match:
        return "-".join(iso_match.groups())
    german_match = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text)
    if german_match:
        day, month, year = german_match.groups()
        return f"{year}-{month}-{day}"
    js_match = re.search(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"(\d{1,2})\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if not js_match:
        return ""
    month_name, day, year = js_match.groups()
    month = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }[month_name.lower()]
    return f"{year}-{month:02d}-{int(day):02d}"


def normalize_raid_time(value):
    return re.sub(r"\s*Uhr\s*$", "", clean(value), flags=re.I)


def is_inactive_status(value):
    return clean(value).lower() in INACTIVE_RAID_STATUSES


def raid_is_stale(raid, now=None):
    raid = raid or {}
    if is_inactive_status(raid.get("status") or raid.get("raidStatus")):
        return True
    raid_date = canonical_raid_date(raid.get("raidDate") or raid.get("date") or raid.get("datum"))
    if not raid_date:
        return False
    berlin = ZoneInfo("Europe/Berlin")
    now = now or datetime.now(berlin)
    if now.tzinfo is None:
        now = now.replace(tzinfo=berlin)
    raid_kind = normalize_raid(raid.get("raid") or raid.get("raidName") or raid.get("raidType"))
    raid_time = normalize_raid_time(raid.get("raidTime") or raid.get("time") or raid.get("uhrzeit"))
    if raid_kind in TWENTY_PLAYER_RAIDS and raid_time:
        try:
            starts_at = datetime.strptime(f"{raid_date} {raid_time}", "%Y-%m-%d %H:%M").replace(tzinfo=berlin)
            return now >= starts_at + timedelta(hours=2)
        except ValueError:
            pass
    return raid_date < now.date().isoformat()


def payload_is_stale(payload, now=None):
    payload = payload or {}
    snapshots = [
        payload,
        payload.get("raidSnapshot") if isinstance(payload.get("raidSnapshot"), dict) else {},
        payload.get("combinedRaidSnapshot") if isinstance(payload.get("combinedRaidSnapshot"), dict) else {},
    ]
    return any(raid_is_stale(snapshot, now=now) for snapshot in snapshots if snapshot)


def payload_matches_guild(payload, guild_slug):
    payload = payload or {}
    actual = normalize_guild_slug(payload.get("guildSlug") or payload.get("guild"))
    return actual == normalize_guild_slug(guild_slug)

