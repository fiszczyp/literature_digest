# Literature digest

***Disclaimer:*** *this was fully vibe coded. I take zero responsibility over any of code.*

## Installation

Make sure to have `qpdf` installed.

## Use

### Weekly digests

Those are TOCs with graphics only. Go to the publisher websites, save the HTML pages of the TOCs. For ACIE that will be multiple ones. Then just specify what you want in your digest in `config.toml`. Finally run:

```
uv run make_digest.py weekly
```

The generated HTML is best printed through Firefox/Chrome.

### Monthly digests

Those are meant for full front pages of each article. Easiest workflow is probably to go to current issue on desired publisher website, use Zotero plugin to download all articles into a folder, then export PDFs to `monthly_raw`. Finally, just run:

```
uv run make_digest.py weekly
```
