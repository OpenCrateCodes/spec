#!/usr/bin/env python3
"""Find each reference track on Deezer and write previews.json for the site's play buttons.

Usage: python3 tools/previews.py [--all]

previews.json maps "Artist – Title" (the reference without its energy) to a Deezer track id. The
page asks Deezer for the 30-second preview's link on each visit, because those links expire.

Only a match on artist and title counts, in the original version or a plain edit or remaster;
anything else is left out rather than guessed. Entries already in the file are kept, so a hand fix
sticks: set an id to correct a match, or null to say there's no preview. For a track Deezer doesn't
have, set {"apple": track id} or {"soundcloud": track url} instead. --all looks every reference up
again, except those. It's for the site only and isn't part of the standard.
Standard library only.
"""

import json
import re
import sys
import time
import tomllib
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENERGY = re.compile(r"^(.*) \([1-5]\)$")
# "(feat. X)", or a bare "feat. X" up to the next version part.
FEAT = re.compile(r"\s*(?:[(\[](?:feat|ft|featuring)\b[^)\]]*[)\]]|\b(?:feat|ft|featuring)\.?\s.*?(?=\s-\s|\s[(\[]|$))", re.I)
# Version words that still mean the original recording.
PLAIN = {"original", "mix", "version", "album", "single", "radio", "edit", "extended", "remaster",
         "remastered", "digital", "digitally", "mono", "stereo", "explicit", "clean", "deluxe",
         "edition", "and", "the"}
# Album words for another recording: remixes, covers, live takes.
OTHER = re.compile(r"\b(?:live|(?:re)?mix(?:es)?|karaoke|tribute|covers?|acoustic|unplugged|instrumentals?)\b")
# Letters that don't decompose into a base letter and an accent.
FOLD = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "ı": "i", "ł": "l", "đ": "d"})


def norm(text):
    text = unicodedata.normalize("NFKD", text.lower().translate(FOLD))
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def plain_version(version):
    words = norm(FEAT.sub("", version)).split()
    return not words or words[0] == "from" or all(w in PLAIN or w.isdigit() for w in words)


def score(artist, title, track):
    """3 for the exact title, 2 for the plain title, 1 for an edit or remaster, else None."""
    if f" {norm(track['artist']['name'])} " not in f" {norm(artist)} " or not track.get("preview"):
        return None
    # A plain title on a remix or live album is rarely the original.
    if OTHER.search(norm(track["album"]["title"])) and not OTHER.search(norm(title)):
        return None
    if norm(FEAT.sub("", track["title"])) == norm(title):
        return 3
    # Deezer puts some versions in title_version and others after " - " in the title.
    short, _, dash = FEAT.sub("", track.get("title_short") or track["title"]).partition(" - ")
    version = track.get("title_version") or ""
    if norm(short) != norm(title) or not (plain_version(dash) and plain_version(version)):
        return None
    return 1 if norm(FEAT.sub("", dash + " " + version)) else 2


def deezer(path, **params):
    url = "https://api.deezer.com/" + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        time.sleep(0.15 if attempt == 0 else 2 * attempt)
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                body = json.load(r)
        except OSError:  # The connection to Deezer drops now and then.
            continue
        if body.get("error", {}).get("code") != 4:  # 4 is Deezer's rate limit.
            return body
    raise RuntimeError("Deezer didn't answer " + url)


def best(artist, title, tracks):
    ranked = [(s, t["rank"], t) for t in tracks if (s := score(artist, title, t))]
    return max(ranked, key=lambda x: x[:2]) if ranked else None


def find(reference):
    artist, _, title = reference.partition(" – ")
    lead = re.split(r" feat\. | vs\.? ", artist)[0]
    tracks = deezer("search", q=lead + " " + title, limit=50).get("data", [])
    hit = best(artist, title, tracks)
    if not hit or hit[0] < 3:
        # Search can bury the original under remixes; the artist's top tracks usually have it.
        for a in deezer("search/artist", q=lead, limit=5).get("data", []):
            if f" {norm(a['name'])} " in f" {norm(artist)} ":
                tracks += deezer(f"artist/{a['id']}/top", limit=100).get("data", [])
                break
        hit = best(artist, title, tracks)
    return hit and hit[2]


def main():
    data = tomllib.loads((ROOT / "occ.toml").read_text())
    refs = [ENERGY.sub(r"\1", r) for g in data["genre"] for r in g.get("references", [])]
    out = ROOT / "previews.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    if "--all" in sys.argv:
        old = {r: v for r, v in old.items() if isinstance(v, dict)}  # Apple and SoundCloud, set by hand
    previews = {r: old[r] for r in refs if r in old}
    missing = []
    try:
        for ref in refs:
            if ref in previews:
                continue
            if track := find(ref):
                previews[ref] = track["id"]
                print(f"{ref}\n    → {track['artist']['name']} – {track['title']} [{track['album']['title']}] {track['id']}")
            else:
                # A miss isn't written, so the next run tries again; null is only ever set by hand.
                missing.append(ref)
    finally:
        # Written even if Deezer stops answering, so the next run carries on from here.
        out.write_text(json.dumps({r: previews[r] for r in refs if r in previews}, ensure_ascii=False, indent=1) + "\n")
    found = sum(1 for v in previews.values() if v)
    print(f"\n{found} of {len(refs)} references have a preview. Wrote {out.name}.")
    if missing:
        print("No safe match on Deezer (add an id by hand, or null):")
        print("\n".join("  " + m for m in missing))


if __name__ == "__main__":
    main()
