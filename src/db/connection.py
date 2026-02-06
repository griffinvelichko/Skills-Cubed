import os

from neo4j import AsyncGraphDatabase

from src.utils.config import EMBEDDING_DIM

_driver = None


async def get_driver():
    global _driver
    if _driver is None:
        uri = os.environ["NEO4J_URI"]
        user = os.environ.get("NEO4J_USERNAME") or os.environ["NEO4J_USER"]
        password = os.environ["NEO4J_PASSWORD"]
        _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    return _driver


async def close_driver():
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def health_check() -> dict:
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run("RETURN 1 AS ok")
        record = await result.single()

        # Get server info
        server_info = await driver.get_server_info()
        return {
            "status": "ok",
            "neo4j_version": server_info.agent,
            "result": record["ok"],
        }


async def initialize_indexes():
    driver = await get_driver()
    async with driver.session() as session:
        # Vector index for semantic search
        result = await session.run(
            f"""
            CREATE VECTOR INDEX skill_embedding IF NOT EXISTS
            FOR (s:Skill)
            ON (s.embedding)
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {EMBEDDING_DIM},
                `vector.similarity_function`: 'cosine'
            }}}}
            """
        )
        await result.consume()

        # Full-text index for keyword search
        # DROP first — IF NOT EXISTS won't update an existing index with old fields
        result = await session.run(
            "DROP INDEX skill_keywords IF EXISTS"
        )
        await result.consume()
        result = await session.run(
            """
            CREATE FULLTEXT INDEX skill_keywords IF NOT EXISTS
            FOR (n:Skill)
            ON EACH [n.title, n.problem, n.resolution_md, n.keywords]
            """
        )
        await result.consume()

        # One-time data migration: rename legacy resolution → resolution_md
        result = await session.run(
            """
            MATCH (s:Skill) WHERE s.resolution IS NOT NULL AND s.resolution_md IS NULL
            SET s.resolution_md = s.resolution
            REMOVE s.resolution
            """
        )
        await result.consume()
