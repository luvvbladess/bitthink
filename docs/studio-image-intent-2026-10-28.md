# Studio: descriptive image prompts

Studio now recognises image briefs beginning with adjectives, including the reported
«Стильный современный аниме-постер с Канеки Кеном…». Previously the detector expected
a drawing verb or an image noun as the first word and fell back to a website.

- The first requested artifact in the opening sentence determines the route:
  a poster for a website is an image; a website containing a poster stays a website.
- A new descriptive image brief starts a new image after a previous site or image.
  Short instructions such as «Сделай картинку темнее» still edit the existing image.
- The negative-prompt section does not select the output type or dimensions.
  The complete original prompt, including negative constraints, reaches the image provider.
- Explicit square, portrait and landscape requests use the provider's supported
  1024×1024, 1024×1536 and 1536×1024 sizes in Studio and ordinary chat.
  A 2:3 request therefore produces a portrait image rather than requesting a square.
  Other ratios are mapped to the nearest supported orientation, not guaranteed exactly.
- «В центре» no longer falsely matches the price-search trigger «цен…».
  Actual price inflections continue to request current data.

Regression tests cover the full reported prompt, previous site/image contexts,
negative constraints, real Studio dispatch with an isolated image-provider stub,
website/presentation intent and short edits. No image-provider traffic or user quota
is needed for these regression tests.
