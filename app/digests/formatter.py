"""Render grounded, evidence-backed regulatory digests in HTML and plain text."""

from __future__ import annotations

import html

from app.digests.models import DigestPayload


def render_digest_html(payload: DigestPayload) -> str:
    """Render an HTML digest email with clear provenance and prominent unsubscribe footer."""
    items_html: list[str] = []
    for it in payload.items:
        clean_title = html.escape(it.title or f"{it.source} Circular")
        clean_url = html.escape(it.canonical_url)
        clean_source = html.escape(it.source)
        clean_date = html.escape(it.published_date or "Date unverified")

        provisions_html: list[str] = []
        for prov in it.summary_provisions:
            provisions_html.append(f"<li style='margin-bottom: 6px;'>{html.escape(prov)}</li>")
        provisions_block = (
            "".join(provisions_html) if provisions_html else "<li>See source circular.</li>"
        )

        citations_html: list[str] = []
        for cite in it.citations:
            quote = html.escape(cite.get("quote", ""))
            span = html.escape(cite.get("chunk_id", ""))
            if quote:
                citations_html.append(
                    f"<blockquote style='border-left: 3px solid #0052cc; margin: 8px 0; padding-left: 10px; color: #444; font-size: 13px; font-style: italic;'>"
                    f'"{quote}" <span style="color: #777; font-size: 11px;">[Ref: {span[:8]}]</span>'
                    f"</blockquote>"
                )
        citations_block = "".join(citations_html)

        badge_color = "#0052cc" if it.source == "RBI" else "#00875a"
        item_card = f"""
        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                <span style="background: {badge_color}; color: #ffffff; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase;">
                    {clean_source}
                </span>
                <span style="color: #64748b; font-size: 13px;">{clean_date}</span>
            </div>
            <h3 style="margin: 0 0 12px 0; font-size: 17px; color: #1e293b; line-height: 1.4;">
                <a href="{clean_url}" style="color: #0f172a; text-decoration: none;" target="_blank">
                    {clean_title}
                </a>
            </h3>
            <div style="margin-bottom: 14px;">
                <p style="font-size: 13px; font-weight: 600; color: #475569; margin: 0 0 6px 0; text-transform: uppercase; letter-spacing: 0.5px;">Key Ingested Provisions:</p>
                <ul style="margin: 0; padding-left: 20px; color: #334155; font-size: 14px; line-height: 1.5;">
                    {provisions_block}
                </ul>
            </div>
            {citations_block}
            <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed #e2e8f0;">
                <a href="{clean_url}" style="font-size: 13px; color: #2563eb; font-weight: 500; text-decoration: none;" target="_blank">
                    &rarr; Inspect Authoritative PDF at {clean_source}
                </a>
            </div>
        </div>
        """
        items_html.append(item_card)

    cards_markup = (
        "".join(items_html)
        if items_html
        else "<p>No new circulars matched your saved topics during this window.</p>"
    )
    clean_unsub = html.escape(payload.unsubscribe_url)
    clean_name = html.escape(payload.recipient_name or "Analyst")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DocScout Regulatory Digest</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px 16px; color: #1e293b;">
    <div style="max-width: 640px; margin: 0 auto; background: transparent;">
        <!-- Header -->
        <div style="border-bottom: 2px solid #0f172a; padding-bottom: 16px; margin-bottom: 24px;">
            <h1 style="margin: 0; font-size: 22px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;">
                DocScout Regulatory Digest
            </h1>
            <p style="margin: 4px 0 0 0; font-size: 14px; color: #64748b;">
                Personalized {payload.frequency.capitalize()} Update for {clean_name} &bull; Generated {payload.generated_at}
            </p>
        </div>

        <!-- Body Items -->
        {cards_markup}

        <!-- Evidence Disclaimer & Footer -->
        <div style="margin-top: 36px; padding-top: 20px; border-top: 1px solid #cbd5e1; font-size: 12px; color: #64748b; line-height: 1.5;">
            <p style="margin: 0 0 8px 0;">
                <strong>Grounded Evidence Notice:</strong> All circular provisions in this digest are derived directly from verified documents fetched from RBI / SEBI portals. DocScout never fabricates legal obligations. This digest is for regulatory research and does not constitute formal legal counsel.
            </p>
            <p style="margin: 0 0 12px 0;">
                You received this digest because you opted in to DocScout regulatory notifications.
            </p>
            <p style="margin: 0;">
                <a href="{clean_unsub}" style="color: #64748b; text-decoration: underline;">
                    One-Click Unsubscribe
                </a>
                &bull;
                <a href="{clean_unsub}" style="color: #64748b; text-decoration: underline;">
                    Manage Topic Preferences
                </a>
            </p>
        </div>
    </div>
</body>
</html>"""


def render_digest_text(payload: DigestPayload) -> str:
    """Render a plain-text digest email."""
    lines: list[str] = [
        "DOCSCOUT REGULATORY DIGEST",
        "=" * 40,
        f"Recipient: {payload.recipient_name} ({payload.recipient_email})",
        f"Frequency: {payload.frequency.capitalize()}",
        f"Generated: {payload.generated_at}",
        "",
        "NEWLY VERIFIED REGULATORY CIRCULARS:",
        "-" * 40,
    ]

    for it in payload.items:
        lines.append(f"[{it.source}] {it.title or 'Untitled Circular'}")
        lines.append(f"Date: {it.published_date or 'Date unverified'}")
        lines.append(f"Official Source: {it.canonical_url}")
        lines.append("Key Provisions:")
        for prov in it.summary_provisions:
            lines.append(f"  * {prov}")
        for cite in it.citations:
            q = cite.get("quote", "")
            if q:
                lines.append(f'  Quote: "{q}"')
        lines.append("")

    lines.extend(
        [
            "=" * 40,
            "GROUNDED EVIDENCE NOTICE:",
            "All circulars are derived directly from authoritative RBI/SEBI documents.",
            "DocScout does not fabricate compliance requirements or legal conclusions.",
            "",
            "To unsubscribe or update preferences immediately, click:",
            f"{payload.unsubscribe_url}",
        ]
    )

    return "\n".join(lines)
