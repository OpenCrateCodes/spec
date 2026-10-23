#!/usr/bin/env python3
"""Validate occ.toml against the Open Crate Codes rules and write occ.json.

Usage: python3 tools/build.py [path/to/occ.toml]

Exits 1 and lists every problem if the file breaks a rule; occ.json is only written when it's clean.
Standard library only.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

# The Album grammar from the spec: family, code, optional style, optional energy, name.
ALBUM = re.compile(r"^(\d{2}) ([A-Z0-9]{2,4})(?:\.([A-Z0-9]{2,4}))?(?: E(\d))? (.+)$")
CODE = re.compile(r"^[A-Z]{3}$")
TAG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
HEX = re.compile(r"^#[0-9A-F]{6}$")
BPM = re.compile(r"^(\d{2,3})–(\d{2,3})(\+?)$")
REFERENCE = re.compile(r"^.+ – .+ \(([1-5])\)$")
# Tools have no energy, so their references don't carry one.
TOOL_REFERENCE = re.compile(r"^.+ – .+$")
SOURCES = {"discogs", "musicbrainz", "everynoise"}
PRIVATE_FAMILIES = range(90, 100)


def bpm_span(text):
    m = BPM.match(text or "")
    return (int(m[1]), int(m[2]), m[3] == "+") if m else None


def album(family, code, level, name):
    energy = f"E{level}" if level else ""
    return " ".join(f"{family:02d} {code} {energy} {name}".split())


def build(path):
    data = tomllib.loads(path.read_text())
    errors = []
    err = errors.append

    for key in ("standard", "version", "license"):
        if not data.get(key):
            err(f"top level: `{key}` is missing")

    # Energy: exactly levels 1–5, each with a colour. Unrated tracks have no energy part.
    energies = data.get("energy", [])
    levels = [e["level"] for e in energies]
    if sorted(levels) != [1, 2, 3, 4, 5]:
        err(f"energy: levels must be exactly 1–5, found {sorted(levels)}")
    for e in energies:
        if not HEX.match(e.get("hex", "")):
            err(f"energy {e['level']}: `hex` must look like #1A2B3C")
        if not e.get("description"):
            err(f"energy {e['level']}: needs a description")

    # Families.
    families = data.get("family", [])
    by_name = {}
    for f in families:
        n = f["number"]
        if not 1 <= n <= 89:
            err(f"family {f['name']}: number {n} must be 1–89 (90–99 are private)")
        if f["name"] in by_name:
            err(f"family {f['name']} is defined twice")
        if any(o["number"] == n for o in by_name.values()):
            err(f"family number {n} is used twice")
        if not HEX.match(f.get("hex", "")):
            err(f"family {f['name']}: `hex` must look like #1A2B3C")
        by_name[f["name"]] = f

    # Genres and styles.
    genres = data.get("genre", [])
    genre_codes = [g["code"] for g in genres]
    labels = {l["tag"] for l in data.get("label", [])}
    codes = {}  # "DNB" or "DNB.LIQ" -> (genre, style or None)
    for g in genres:
        c = g["code"]
        if not CODE.match(c) or c.startswith("X"):
            err(f"genre {c}: codes are 3 capital letters and don't start with X (private)")
        if genre_codes.count(c) > 1:
            err(f"genre code {c} is used twice")
        if g.get("family") not in by_name:
            err(f"genre {c}: there's no family \"{g.get('family')}\"")
        if not g.get("definition"):
            err(f"genre {c}: needs a definition")
        codes[c] = (g, None)
        seen = set()
        for s in g.get("styles", []):
            sc = s["code"]
            if not CODE.match(sc) or sc.startswith("X"):
                err(f"style {c}.{sc}: codes are 3 capital letters and don't start with X")
            if sc in seen:
                err(f"style {c}.{sc} is listed twice")
            seen.add(sc)
            codes[f"{c}.{sc}"] = (g, s)

    # Cross-references, crosswalk, references, BPM.
    spans = {}
    for g in genres:
        c = g["code"]
        for other in g.get("not", []):
            if other not in genre_codes or other == c:
                err(f"genre {c}: `not` lists {other}, which isn't another genre")
        for item in [g] + g.get("styles", []):
            label = c if item is g else f"{c}.{item['code']}"
            if item.get("deprecated"):
                use = item.get("use", "")
                ok = use in codes or (use.startswith("#") and use[1:] in labels)
                if not ok:
                    err(f"{label}: deprecated, but `use = \"{use}\"` isn't a code or #label")
        for source, names in g.get("match", {}).items():
            if source not in SOURCES:
                err(f"genre {c}: unknown crosswalk `match.{source}`")
            if len(set(names)) != len(names) or not all(names):
                err(f"genre {c}: `match.{source}` has empty or repeated names")
        for ref in g.get("references", []):
            tool = g.get("family") == "Utility"
            if not (REFERENCE.match(ref) or (tool and TOOL_REFERENCE.match(ref))):
                want = "Artist – Title" if tool else "Artist – Title (1–5)"
                err(f"genre {c}: reference \"{ref}\" should be \"{want}\"")
        if "bpm" in g:
            span = bpm_span(g["bpm"])
            if not span or span[0] > span[1]:
                err(f"genre {c}: bpm \"{g['bpm']}\" should look like 120–126")
            else:
                spans.setdefault(g["family"], []).append(span)

    for name, f in by_name.items():
        got = spans.get(name)
        if not got:
            if "bpm" in f:
                err(f"family {name}: has a bpm but none of its genres do")
            continue
        lo, hi = min(s[0] for s in got), max(s[1] for s in got)
        want = f"{lo}–{hi}{'+' if any(s[2] and s[1] == hi for s in got) else ''}"
        if f.get("bpm") != want:
            err(f"family {name}: bpm should be \"{want}\", the span of its genres")
        if not any(g.get("family") == name for g in genres):
            err(f"family {name} has no genres")

    # Album values: round-trip through the grammar, and stay findable by anchored search.
    albums = []  # (code, level, album)
    for code, (g, s) in codes.items():
        fam = by_name.get(g.get("family"))
        if not fam:
            continue
        name = g["name"] + (f" ({s['name']})" if s else "")
        if "(" in g["name"] + (s["name"] if s else "") or ")" in g["name"] + (s["name"] if s else ""):
            err(f"{code}: names can't contain brackets; the only brackets in a tag are the style's")
        if re.search(r"e[0-9]", name, re.I):
            err(f"{code}: name \"{name}\" contains E and a digit, which reads as an energy")
        for level in [0] + levels:
            a = album(fam["number"], code, level, name)
            m = ALBUM.match(a)
            parsed = m and (int(m[1]), m[2] + (f".{m[3]}" if m[3] else ""), int(m[4] or 0))
            if parsed != (fam["number"], code, level):
                err(f"{code} at E{level}: \"{a}\" doesn't read back as itself")
            albums.append((code, level, a))

    for code, (g, s) in codes.items():
        fam = by_name.get(g.get("family"))
        if not fam:
            continue
        anchor = f"{fam['number']:02d} {code}".lower()
        mine = (lambda c: c == code) if s else (lambda c: c == code or c.startswith(code + "."))
        for other, _, a in albums:
            if not mine(other) and anchor in a.lower():
                err(f"searching Album for \"{anchor.upper()}\" would also find \"{a}\"")
                break
    for level in range(1, 6):
        needle = f"e{level}"
        for code, lv, a in albums:
            if lv != level and needle in a.lower():
                err(f"searching Album for E{level} would also find \"{a}\"")
                break

    # Labels.
    groups = {}
    for l in data.get("label", []):
        if not TAG.match(l["tag"]):
            err(f"label {l['tag']}: tags are lowercase letters, digits, - or _")
        if sum(1 for o in data["label"] if o["tag"] == l["tag"]) > 1:
            err(f"label {l['tag']} is defined twice")
        groups.setdefault(l.get("group"), []).append(l["tag"])

    if errors:
        return errors, None

    out = {
        "standard": data["standard"],
        "version": data["version"],
        "license": data["license"],
        "grammar": ALBUM.pattern,
        "energy": sorted(energies, key=lambda e: e["level"]),
        "families": [
            {**f, "genres": [g for g in genres if g.get("family") == f["name"]]}
            for f in sorted(families, key=lambda f: f["number"])
        ],
        "labels": data.get("label", []),
    }
    return [], out


def main():
    root = Path(__file__).resolve().parent.parent
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "occ.toml"
    errors, out = build(path)
    if errors:
        print(f"{path.name}: {len(errors)} problem(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    target = path.with_suffix(".json")
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    n = sum(len(f["genres"]) for f in out["families"])
    styles = sum(len(g.get("styles", [])) for f in out["families"] for g in f["genres"])
    print(f"{target.name}: {out['standard']} {out['version']}, {len(out['families'])} families, "
          f"{n} genres, {styles} styles, {len(out['labels'])} labels")


if __name__ == "__main__":
    main()
