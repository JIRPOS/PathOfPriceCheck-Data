# Status of the generated data

The code in this repository is MIT licensed (see `LICENSE`). The **data it generates** is
not ours to license.

Path of Exile and all associated game content are © Grinding Gear Games. The published
bundles contain derived textual metadata — item names, stat wordings, and the identifiers
GGG's own public trade API uses to index them — redistributed to support a free,
non-commercial fan tool.

**No game assets are redistributed.** Item icons are stored as URL strings pointing at GGG's
CDN; no image, sound, or model data is copied into a release.

## poewiki

`en-unique-mods.ndjson` uses one fact the game files do not state: which modifiers each unique
item can roll. That grouping comes from the [Path of Exile Wiki](https://www.poewiki.net)'s
`item_mods` cargo table, whose content is licensed
**[CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/)** — attribution required,
non-commercial use only, which this project is.

What is taken is a mapping between identifiers GGG published: unique item name → GGG mod id,
with the wiki's `is_random` / `is_implicit` flags and the prose it renders for a pool ("Two or
Three random aura modifiers"). Every stat, range and trade hash attached to those ids is
derived from the game files and GGG's trade API, not from the wiki. Attribution: *modifier
groupings from poewiki.net, CC BY-NC 3.0.*

This project is not affiliated with or endorsed by Grinding Gear Games.

If you are from GGG and would like a change made or the releases taken down, open an issue
or see `CONTACT.md` and it will be actioned.
