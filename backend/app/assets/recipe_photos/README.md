# Photorealistic recipe photo corpus

Shared stock/AI-photoreal images matched to recipes that lack cookbook-extracted art.

## Layout

```
manifest.json     # array of { id, file, tags[], cuisine?[] }
photos/{id}.jpg   # image files (gitignored; keep locally or via LFS)
```

## Manifest entry

```json
{
  "id": "risotto_01",
  "file": "photos/risotto_01.jpg",
  "tags": ["risotto", "rice", "arborio"],
  "cuisine": ["italian"]
}
```

- `file` is relative to this directory.
- Recipes store `image_path` as `corpus/photos/….jpg` and `image_source=corpus`.
- Matching scores title tokens highest, then recipe tags, then cuisine.

## Adding photos

1. Drop licensed JPGs/WebPs into `photos/`.
2. Tag them in `manifest.json`.
3. Run `python -m app.scripts.backfill_recipe_images`.

## Licensing

Prefer Adobe Stock / Shutterstock / Unsplash+ (or your own AI photoreal pack) with rights that cover a multi-user web app. Do **not** scrape Google Images or publisher cookbooks into this shared corpus.
