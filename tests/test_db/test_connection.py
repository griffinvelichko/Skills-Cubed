import os

import pytest

pytestmark = pytest.mark.skipif(
    not all(os.getenv(v) for v in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")),
    reason="Neo4j credentials not configured (need NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)",
)


@pytest.mark.integration
async def test_driver_singleton():
    from src.db.connection import get_driver

    driver1 = await get_driver()
    driver2 = await get_driver()
    assert driver1 is driver2


@pytest.mark.integration
async def test_health_check():
    from src.db.connection import health_check

    result = await health_check()
    assert result["status"] == "ok"
    assert result["result"] == 1
    assert "neo4j_version" in result


@pytest.mark.integration
async def test_close_driver():
    from src.db.connection import close_driver, get_driver

    await get_driver()
    await close_driver()

    from src.db import connection
    assert connection._driver is None
