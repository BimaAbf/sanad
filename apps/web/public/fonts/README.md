# Fonts

`IBM Plex Sans Arabic` (SIL OFL 1.1) is self-hosted and subset, per P00.

The `.woff2` files are **not committed** — they are fetched by:

```
just fonts
```

which downloads the upstream OFL release and subsets it to Arabic +
Latin digits into this directory as:

- `ibm-plex-sans-arabic-400.woff2`
- `ibm-plex-sans-arabic-600.woff2`

If the files are absent the app still renders: `src/styles/globals.css`
declares a metric-matched `IBM Plex Sans Arabic Fallback` face over
Segoe UI / Noto Sans Arabic, so text stays at 17px/1.9 and the layout
does not shift when the real font arrives.
