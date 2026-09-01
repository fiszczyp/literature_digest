# /// script
# dependencies = ["beautifulsoup4"]
# ///

import os
import re
import sys
import shutil
import tomllib
import argparse
import subprocess
from pathlib import Path
from datetime import date
from bs4 import BeautifulSoup

# --- UTILS ---


def get_iso_date():
    return date.today().isoformat()


def clean_authors(text, journal_key):
    """Standardizes author lists: targets and removes messy clusters like ', ;,'."""
    if not text:
        return ""

    # 1. Remove "BY " prefix often found in Science/Nature news
    text = re.sub(r"^BY\s+", "", text, flags=re.IGNORECASE)

    # 2. Target the specific mess: replace semicolons with commas to normalize
    text = text.replace(";", ",")

    # 3. Use Regex to find any sequence of commas and spaces and turn them into a single ', '
    # This fixes "Name, ;," -> "Name, "
    text = re.sub(r"[,\s]{2,}", ", ", text)

    # 4. Clean up any trailing/leading punctuation
    return text.strip(", ")


def get_html_template(body_content, page_header_text):
    """Standardized white layout. DOI is now a link but styled to match text."""
    return f"""<html><head><meta charset="UTF-8"><title>{page_header_text}</title><style>
        @media print {{
            @page {{ size: A4 portrait; margin: 1cm; }}
            header, footer {{ display: none !important; }}
        }}
        body {{
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            margin: 0 auto; padding: 20px; color: #1a1a1a;
            max-width: 850px; background-color: white;
        }}
        .section-label {{
            border-bottom: 2px solid #002f65; color: #002f65;
            font-size: 18px; font-weight: bold; margin: 30px 0 10px 0;
            text-transform: uppercase;
        }}
        .article-row {{
            display: flex; align-items: center;
            border-bottom: 1px solid #eee; padding: 8px 0;
            page-break-inside: avoid;
        }}
        .text-content {{ flex: 1; padding-right: 20px; }}
        .title {{ font-size: 11.5px; font-weight: 800; line-height: 1.25; color: #002f65; margin-bottom: 3px; }}

        .authors, .doi {{
            font-size: 9.5px;
            color: #444;
            margin-bottom: 3px;
            display: block;
            line-height: 1.3;
        }}
        .authors {{ font-style: italic; }}
        .doi {{
            font-family: monospace;
            text-decoration: none;
        }}
        .doi:hover {{ text-decoration: underline; }}

        .img-container {{ flex: 0 0 42%; text-align: right; }}
        img {{ max-width: 100%; max-height: 135px; object-fit: contain; border: 1px solid #f0f0f0; }}
    </style></head><body>
        <div class="section-label">{page_header_text}</div>
        {body_content}
    </body></html>"""


# --- SCRAPER ---


def scrape_journal_body(input_files, journal_key):
    seen_ids = set()
    rows_html = ""
    total = 0

    base_urls = {
        "jacs": "https://pubs.acs.org",
        "acie": "https://onlinelibrary.wiley.com",
        "chem": "https://www.cell.com",
        "trends": "https://www.cell.com",
        "nature": "https://www.nature.com",
        "nchem": "https://www.nature.com",
        "science": "https://www.science.org",
        "rsc": "https://pubs.rsc.org",
    }

    # Base URL selector
    lookup_key = journal_key.lower()
    if lookup_key.startswith("nature") or lookup_key == "nchem":
        base_url = base_urls["nature"]
    elif lookup_key in ["chem", "joule", "matter"]:
        base_url = base_urls["chem"]
    else:
        base_url = base_urls.get(lookup_key, "")

    for input_file in input_files:
        with open(input_file, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        # Added 'articleCitation' for Cell Press
        items = soup.find_all(
            ["div", "article", "li"],
            class_=[
                "al-article-item-wrap",
                "issue-item",
                "teaser__content",
                "toc__item",
                "article-item",
                "c-card",
                "app-article-list-row__item",
                "card",
                "articleCitation",
            ],
        )

        for art in items:
            try:
                # 1. Title
                t_node = art.find(
                    ["h2", "h3", "h4", "a", "span"],
                    class_=[
                        "item-title",
                        "issue-item__title",
                        "toc__item__title",
                        "article-title",
                        "c-card__title",
                        "related-item__content",
                    ],
                )
                if not t_node:
                    t_node = art.find(attrs={"itemprop": "name headline"})
                title = t_node.get_text(strip=True) if t_node else ""

                # Filter noise
                if (
                    not title
                    or len(title) < 15
                    or any(
                        x in title
                        for x in ["Correction", "Publisher's Note", "Issue cover"]
                    )
                ):
                    continue

                # 2. DOI / ID Extraction
                item_id = ""
                # Try standard DOI link
                doi_link = art.find("a", href=re.compile(r"doi\.org/10\."))
                if doi_link:
                    item_id = doi_link["href"].split("doi.org/")[-1]

                # FALLBACK FOR WILEY (ACIE/JACS/RSC relative paths)
                if not item_id:
                    w_link = art.find("a", href=re.compile(r"/doi/(abs/|full/|epdf/)?10\."))
                    if w_link:
                        # Extracts the part after /doi/ and removes potential prefixes
                        path = w_link['href'].split('/doi/')[-1]
                        item_id = re.sub(r"^(abs/|full/|epdf/)", "", path)

                # Fallback for Nature paths
                if not item_id:
                    n_link = art.find("a", href=re.compile(r"/articles/s"))
                    if n_link:
                        item_id = f"10.1038/{n_link['href'].split('/')[-1]}"

                # Fallback for Cell Press (Chem) paths
                if not item_id:
                    c_link = art.find("a", href=re.compile(r"/fulltext/S"))
                    if c_link:
                        item_id = c_link["href"].split("/")[-1]

                if not item_id:
                    continue
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                # 3. Authors
                a_node = art.find(
                    ["ul", "div", "p", "span"],
                    class_=[
                        "al-authors-list",
                        "author-info",
                        "toc__item__authors",
                        "app-author-list",
                        "authors",
                        "article-authors",
                        "loa-authors-trunc",
                        "c-author-list",
                        "loa",
                    ],
                )
                raw_authors = a_node.get_text(", ", strip=True) if a_node else ""
                authors = clean_authors(raw_authors, journal_key)

                # 4. Image
                img_tag = art.find("img")
                if not img_tag:
                    continue
                img_url = (
                    img_tag.get("src")
                    or img_tag.get("data-src")
                    or img_tag.get("data-original-src")
                )

                if not img_url or any(
                    x in img_url for x in ["gif", "lock", "spacer", "cov200h"]
                ):
                    continue

                if img_url.startswith("//"):
                    img_url = "https:" + img_url
                if img_url.startswith("/"):
                    img_url = base_url + img_url

                # Resolution Fixes
                if journal_key == "jacs":
                    img_url = img_url.replace("m_ja", "ja")
                if journal_key == "acie":
                    img_url = img_url.replace("-m.", "-l.")
                if "cell.com" in base_url:
                    img_url = img_url.replace(
                        ".sml", ".lrg"
                    )  # Get large images for Chem

                # Create clickable DOI link (or PII link for Cell Press)
                link_url = (
                    f"https://doi.org/{item_id}"
                    if item_id.startswith("10.")
                    else f"{base_url}/chem/fulltext/{item_id}"
                )
                doi_display = (
                    f'<a class="doi" href="{link_url}" target="_blank">{item_id}</a>'
                )

                rows_html += f'''
                <div class="article-row">
                    <div class="text-content">
                        <div class="title">{title}</div>
                        <div class="authors">{authors}</div>
                        {doi_display}
                    </div>
                    <div class="img-container"><img src="{img_url}"></div>
                </div>'''
                total += 1
            except:
                continue
    return rows_html, total


# --- MODES ---


def mode_weekly(journals, raw_dir, output_dir):
    print(f"🚀 Scanning Weekly Files...")
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    today = get_iso_date()
    combined_body = ""
    total_found = 0

    for journal in journals:
        files = sorted([str(f) for f in Path(raw_dir).glob(f"{journal}*.html")])
        if not files:
            continue

        print(f"  Processing {journal.upper()}...")
        body, count = scrape_journal_body(files, journal)

        if count > 0:
            # 1. Individual HTML (Kept in output folder)
            indiv_name = f"{today}-{journal}_digest.html"
            header_text = f"{today} {journal.upper()} Digest"
            with open(output_path / indiv_name, "w", encoding="utf-8") as f:
                f.write(get_html_template(body, header_text))

            combined_body += f'<div class="section-label">{journal.upper()}</div>'
            combined_body += body
            total_found += count

    if total_found > 0:
        combined_name = f"{today}-Weekly_digest.html"
        header_text = f"{today} Weekly Digest"
        with open(combined_name, "w", encoding="utf-8") as f:
            f.write(get_html_template(combined_body, header_text))
        print(f"✅ Created Combined HTML: {combined_name}")
    else:
        print("❌ No articles found.")


def is_pdf_readable(pdf_path):
    """Returns True if the PDF is not fundamentally corrupted (Exit code 0 or 3)."""
    res = subprocess.run(["qpdf", "--check", str(pdf_path)], capture_output=True)
    # 0 = Good, 3 = Warnings, 2 = Fatal/Corrupted
    return res.returncode in [0, 3]


def mode_monthly(raw_dir):
    print(f"📂 Ripping Front Pages from {raw_dir}...")
    today = get_iso_date()
    pdfs = sorted(list(Path(raw_dir).glob("*.pdf")))

    if not pdfs:
        print(f"❌ No PDFs found in {raw_dir}")
        return

    final_pdf = f"{today}-Monthly_digest.pdf"
    valid_args = []

    # Filter out files that are fundamentally broken (Status 2)
    for pdf in pdfs:
        if is_pdf_readable(pdf):
            valid_args.extend([str(pdf), "1"])
        else:
            print(f"⚠️  Skipping corrupted file: {pdf.name}")

    if not valid_args:
        print("❌ No valid PDFs found to merge.")
        return

    # --warning-exit-0: Treats warnings as success
    # --no-warn: Keeps the console output clean
    cmd = (
        ["qpdf", "--warning-exit-0", "--no-warn", "--empty", "--pages"]
        + valid_args
        + ["--", final_pdf]
    )

    result = subprocess.run(cmd, capture_output=True)

    if result.returncode == 0:
        print(f"✅ Created: {final_pdf}")
    else:
        print(f"❌ Error: {result.stderr.decode()}")


if __name__ == "__main__":
    if not os.path.exists("config.toml"):
        print("Error: config.toml not found.")
        sys.exit(1)

    with open("config.toml", "rb") as f:
        config = tomllib.load(f)

    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["weekly", "monthly"])
    args = parser.parse_args()

    if args.mode == "weekly":
        mode_weekly(
            config["weekly"]["journals"],
            config["paths"]["weekly_raw"],
            config["paths"]["output_dir"],
        )
    elif args.mode == "monthly":
        mode_monthly(config["paths"]["monthly_raw"])
