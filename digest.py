#!/usr/bin/env python3
"""Daily startup funding digest — Series A/B/C in AI & SaaS (US & Europe)."""

import feedparser
import anthropic
import smtplib
import json
import os
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Configuration ────────────────────────────────────────────────────────────

RECIPIENT_EMAIL = "rhepworth@gmail.com"
SENDER_EMAIL    = os.environ["GMAIL_ADDRESS"]
APP_PASSWORD    = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]

RSS_FEEDS = [
    ("TechCrunch",       "https://techcrunch.com/feed/"),
    ("Crunchbase News",  "https://news.crunchbase.com/feed/"),
    ("StrictlyVC",       "https://strictlyvc.com/feed/"),
    ("Tech.eu",          "https://tech.eu/feed/"),
    ("Sifted",           "https://sifted.eu/feed"),
    ("EU-Startups",      "https://eu-startups.com/feed/"),
    ("Business Wire",    "https://www.businesswire.com/rss/home/?rss=g7"),
]

# Quick keyword pre-filter (keeps Claude costs low)
FUNDING_KEYWORDS = [
    "series a", "series b", "series c",
    "funding round", "lead investor",
    "raises $", "raised $", "secures $",
]

# ── Step 1: Fetch articles from the last 24 h ────────────────────────────────

def fetch_recent_articles() -> list[dict]:
    cutoff   = datetime.now(timezone.utc) - timedelta(hours=72)
    articles = []

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                if published and published > cutoff:
                    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                    if any(kw in text for kw in FUNDING_KEYWORDS):
                        articles.append({
                            "title":     entry.get("title", ""),
                            "summary":   entry.get("summary", "")[:600],
                            "link":      entry.get("link", ""),
                            "published": published.isoformat(),
                            "source":    source_name,
                        })
        except Exception as e:
            print(f"  Warning: could not fetch {source_name}: {e}")

    # Deduplicate by link
    seen  = set()
    deduped = []
    for a in articles:
        if a["link"] not in seen:
            seen.add(a["link"])
            deduped.append(a)

    return deduped


# ── Step 2: Filter & extract with Claude ─────────────────────────────────────

SYSTEM_PROMPT = """You are a startup funding analyst. Extract qualifying funding rounds from news articles.

Qualifying criteria:
- Stage: Series A, B, or C ONLY (exclude Seed, Pre-Seed, Series D+, debt, grants, acquisitions, IPOs)
- Sector: AI, artificial intelligence, machine learning, SaaS, or B2B software
- Geography: United States OR Europe (UK, Germany, France, Netherlands, Sweden, Spain, etc.)

Return ONLY a valid JSON array. Each element:
{
  "company":   "Company name",
  "stage":     "Series A" | "Series B" | "Series C",
  "amount":    "$25M" or "Undisclosed",
  "sector":    "e.g. AI infrastructure, B2B SaaS",
  "location":  "City, Country",
  "investors": "Lead investor(s) or Unknown",
  "summary":   "One sentence: what the company does and why they raised",
  "link":      "Article URL"
}

If no articles qualify, return []. Do not include markdown fences."""


def filter_and_extract(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    client  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    payload = json.dumps(articles, indent=2)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role":    "user",
            "content": f"Analyze these articles and return qualifying funding rounds:\n\n{payload}",
        }],
    )

    raw = message.content[0].text.strip()
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        rounds = json.loads(raw)
        return [r for r in rounds if isinstance(r, dict)]
    except json.JSONDecodeError as e:
        print(f"  Warning: could not parse Claude response: {e}")
        return []


# ── Step 3: Format HTML email ─────────────────────────────────────────────────

STAGE_COLOURS = {
    "Series A": "#4a90d9",
    "Series B": "#7b5ea7",
    "Series C": "#e07b39",
}

def card(r: dict) -> str:
    colour = STAGE_COLOURS.get(r.get("stage", ""), "#888")
    return f"""
    <div style="margin:16px 0;padding:18px;background:#f9f9f9;border-radius:8px;
                border-left:5px solid {colour}">
      <div style="font-size:17px;font-weight:700;color:#1a1a2e">{r.get('company','?')}</div>
      <div style="margin:6px 0;color:#555;font-size:14px">
        <strong>{r.get('amount','?')}</strong> &nbsp;·&nbsp;
        {r.get('sector','')} &nbsp;·&nbsp;
        {r.get('location','')}
      </div>
      <div style="margin:6px 0;color:#333;font-size:14px">{r.get('summary','')}</div>
      <div style="margin:4px 0;color:#888;font-size:13px">
        Investors: {r.get('investors','Unknown')}
      </div>
      <a href="{r.get('link','#')}" style="color:{colour};font-size:13px;text-decoration:none">
        Read more →
      </a>
    </div>"""


def format_email(rounds: list[dict]) -> str:
    today = datetime.now().strftime("%B %d, %Y")

    if not rounds:
        body = "<p style='color:#666'>No qualifying Series A/B/C rounds found in AI &amp; SaaS (US &amp; Europe) in the last 24 hours.</p>"
    else:
        body = ""
        for stage in ["Series A", "Series B", "Series C"]:
            items = [r for r in rounds if r.get("stage") == stage]
            if not items:
                continue
            colour = STAGE_COLOURS[stage]
            body += f"""
            <h2 style="margin:28px 0 4px;color:#1a1a2e;font-size:16px;
                        border-bottom:2px solid {colour};padding-bottom:6px">
              {stage} &nbsp;<span style="color:#888;font-weight:400">({len(items)})</span>
            </h2>"""
            for r in items:
                body += card(r)

    return f"""
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                 max-width:660px;margin:auto;padding:24px;color:#333;background:#fff">

      <div style="background:#1a1a2e;color:#fff;padding:20px 24px;border-radius:10px;margin-bottom:8px">
        <div style="font-size:20px;font-weight:700">Startup Funding Digest</div>
        <div style="margin-top:4px;opacity:.65;font-size:13px">
          {today} &nbsp;·&nbsp; Series A / B / C &nbsp;·&nbsp; AI &amp; SaaS &nbsp;·&nbsp; US &amp; Europe
        </div>
      </div>

      {body}

      <p style="margin-top:32px;color:#bbb;font-size:12px;border-top:1px solid #eee;padding-top:16px">
        Sources: TechCrunch · Crunchbase News · StrictlyVC · VentureBeat<br>
        Filtered &amp; summarised by Claude AI
      </p>

    </body>
    </html>"""


# ── Step 4: Send email ────────────────────────────────────────────────────────

def send_email(html: str, num_rounds: int) -> None:
    today   = datetime.now().strftime("%b %d")
    subject = f"Funding Digest {today}: {num_rounds} new round{'s' if num_rounds != 1 else ''}"

    msg              = MIMEMultipart("alternative")
    msg["Subject"]   = subject
    msg["From"]      = SENDER_EMAIL
    msg["To"]        = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())

    print(f"Email sent — {num_rounds} rounds · subject: {subject}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("1/4  Fetching RSS feeds…")
    articles = fetch_recent_articles()
    print(f"     {len(articles)} candidate articles found")

    print("2/4  Filtering with Claude…")
    rounds = filter_and_extract(articles)
    print(f"     {len(rounds)} qualifying rounds")

    print("3/4  Formatting email…")
    html = format_email(rounds)

    print("4/4  Sending email…")
    send_email(html, len(rounds))
    print("Done.")


if __name__ == "__main__":
    main()
