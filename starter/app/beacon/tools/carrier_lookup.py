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

    # TODO(exercise 6): Open an AgentCore Browser sandbox session, connect Playwright
    # to it over CDP, navigate to `url`, and read the page's visible text into `text`.
    #
    #   with browser_session(REGION) as client:
    #       ws_url, headers = client.generate_ws_headers()
    #       with sync_playwright() as playwright:
    #           browser = playwright.chromium.connect_over_cdp(ws_url, headers=headers)
    #           # get/create a context+page, page.goto(url, wait_until="domcontentloaded"),
    #           # give client-rendered banners a moment (page.wait_for_timeout), then
    #           # text = page.inner_text("body"). Always browser.close() when done.
    #
    # Wrap the whole thing in try/except and return an "AGENTCORE_ERROR: ..." string
    # (not a raised exception) if the sandbox or the page is unreachable.
    raise NotImplementedError("TODO: drive a real browser session and extract page text")

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
