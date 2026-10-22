# Open Crate Codes

A free, shared system for tagging genre and energy in a DJ library. One line in the Album tag says
what a track is and when to play it:

```
09 DNB.LIQ E4 Drum & Bass (Liquid)
```

See it on the site: https://opencratecodes.com

- `index.html`: the guide for DJs (genres, tempo map, energy, labels, searches).
- `spec.html`: the rules for software that reads and writes tags.
- `occ.toml`: the standard's data. This is the file to edit.
- `occ.json`: generated from `occ.toml`. Don't edit it by hand.
- `tools/build.py`: checks `occ.toml` against the rules and writes `occ.json`.
- `previews.json`: Deezer track ids for the reference tracks, for the page's play buttons. It's for the site only, not part of the standard.
- `tools/previews.py`: finds new reference tracks on Deezer and adds them to `previews.json`.
- `.nojekyll`: tells GitHub Pages to serve every file as is, so `CHANGELOG.md` and `occ.toml` download unchanged.

## Editing

```sh
python3 tools/build.py        # check occ.toml and regenerate occ.json
python3 tools/previews.py     # look up new reference tracks on Deezer
python3 -m http.server        # then open http://localhost:8000
```

The page loads `occ.json`, so open it through a web server rather than as a file.

`build.py` refuses a file that breaks a rule, for example:
- a code that isn't 3 capital letters, or is used twice
- a family BPM range that doesn't match its genres
- a search like `09 DNB` that would find another genre's tag
- a crosswalk source it doesn't know

Every name under `match.*` was checked against its catalogue when it was added: Discogs styles (from the Discogs data dump), the MusicBrainz genre list, and the Every Noise at Once genre pages. Leave a name out rather than guess.

The same goes for previews. `previews.py` only takes a Deezer track whose artist and title match, in the original version or a plain edit or remaster, and lists the references it couldn't match. Check what it found, then fix any by hand in `previews.json`: an id for the right track, or `null` for no preview. Hand fixes are kept when it runs again.

## License

Everything here is open. The data (`occ.toml`, `occ.json`) and `tools/build.py` are public domain under CC0 1.0. The spec, the site and the logo (`brand/`) are CC BY 4.0. See `LICENSE`.
