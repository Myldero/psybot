from motor.motor_asyncio import AsyncIOMotorClient

MAX_CHANNELS = 500
CATEGORY_MAX_CHANNELS = 50


GUILD_ID = 0
CTFS_CATEGORY = 0
INCOMPLETE_CATEGORY = 0
COMPLETE_CATEGORY = 0
ARCHIVE_CATEGORY = 0
CTF_ARCHIVE_CATEGORY = 0
EXPORT_CHANNEL = 0
TEAM_ROLE = 0
ADMIN_ROLE = 0
PER_CTF_ROLES = True
CATEGORIES = ["pwn", "crypto", "misc", "rev"]
BOT_TOKEN = 'bot-token'

CTFTIME_TEAM = None
BACKUPS_DIR = "../backups"

MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "psybot"
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[MONGO_DB]
