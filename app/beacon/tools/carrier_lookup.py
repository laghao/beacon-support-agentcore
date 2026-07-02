"""Live carrier delay lookup via the AgentCore Browser tool (row 9 of the capability table).

Carriers don't offer a clean delay API for a workshop to call, and that's the
point: this is the tool that justifies a managed browser instead of another
mocked-up REST endpoint. It drives a real Chromium session in a Bedrock
AgentCore Browser sandbox over CDP and reads whatever the carrier's public
service-alerts page says right now.
"""

import logging
import os

from bedrock_agentcore.tools.browser_client import browser_session
from playwright.sync_api import sync_playwright
from strands import tool

logger = logging.getLogger(__name__)

REGION = os.getenv("AWS_REGION", "us-west-2")

# Public service-alert pages. No auth, no API key — exactly the kind of
# source a support agent would otherwise have to check by hand.
CARRIER_ALERT_PAGES = {
    "ups": "https://www.ups.com/us/en/service-alerts.page",
    "fedex": "https://www.fedex.com/en-us/service-alerts.html",
    "usps": "https://about.usps.com/newsroom/service-alerts",
}


@tool
def check_carrier_service_alerts(carrier: str) -> str:
    """Check a shipping carrier's public service-alerts page for active delays.

    Args:
        carrier: One of "ups", "fedex", "usps".

    Returns:
        The visible page text most likely to mention regional delays (best-effort
        extraction — carrier pages aren't structured data), or an AGENTCORE_ERROR
        string if the browser sandbox or the page itself is unreachable.
    """
    url = CARRIER_ALERT_PAGES.get(carrier.lower())
    if not url:
        return f"Unknown carrier '{carrier}'. Expected one of: {', '.join(CARRIER_ALERT_PAGES)}."

    try:
        with browser_session(REGION) as client:
            ws_url, headers = client.generate_ws_headers()
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(ws_url, headers=headers)
                try:
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(1500)  # let client-rendered alert banners load
                    text = page.inner_text("body")
                finally:
                    browser.close()
    except Exception as e:
        logger.error("Browser session failed for %s: %s", carrier, e)
        return f"AGENTCORE_ERROR: carrier lookup unavailable ({e})"

    # Carrier pages are long; keep only lines that look like they're about delays,
    # plus a fallback so an empty match doesn't read as "definitely no delays".
    delay_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and any(kw in line.lower() for kw in ("delay", "disruption", "severe weather", "alert"))
    ]
    if not delay_lines:
        return f"No delay language found on {carrier.upper()}'s service-alerts page as of this check."
    return "\n".join(delay_lines[:15])
