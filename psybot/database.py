from motor.motor_asyncio import AsyncIOMotorClient

from psybot.config import config


mongo_client = AsyncIOMotorClient(config.mongodb_uri)
db = mongo_client[config.mongodb_db]


async def create_indexes():
    await db.ctf.create_index('channel_id', unique=True)

    await db.challenge.create_index('channel_id', unique=True)
    await db.challenge.create_index('ctf_id')

    await db.backup_category.create_index('category_id', unique=True)
    await db.backup_category.create_index('original_id')

    await db.ctf_category.create_index('name', unique=True)
