"""Async long-running task demo (row 17 of the capability table).

"Check with the warehouse" is the one thing in this agent that can legitimately
take a while (a real integration would page a warehouse management system and
wait for a human picker to confirm a shelf count). Wrapping it in
`@app.async_task` flips the Runtime's /ping status to HealthyBusy for the
duration, so a caller polling status knows the agent is still working instead
of assuming it hung.

`app` is constructed in main.py, so this module exposes a factory rather than
a module-level `@tool` — the decorator needs a concrete BedrockAgentCoreApp
instance to register the task against.
"""

import asyncio
import random

from strands import tool


def make_check_warehouse_stock_tool(app):
    @app.async_task
    async def _check_warehouse_stock(sku: str, warehouse: str = "WH-EAST") -> dict:
        # Simulated WMS round-trip. A real integration would call out to the
        # warehouse system here and await its response instead of sleeping.
        await asyncio.sleep(2)
        rng = random.Random(f"{sku}:{warehouse}")
        on_shelf = rng.randint(0, 40)
        return {
            "sku": sku,
            "warehouse": warehouse,
            "on_shelf_count": on_shelf,
            "confirmed": True,
        }

    @tool
    async def check_warehouse_stock(sku: str, warehouse: str = "WH-EAST") -> dict:
        """Confirm on-shelf stock for a SKU directly with the warehouse (slow; async).

        Args:
            sku: Product SKU to check.
            warehouse: Warehouse code, e.g. "WH-EAST", "WH-WEST", "WH-CENTRAL".
        """
        return await _check_warehouse_stock(sku, warehouse)

    return check_warehouse_stock
