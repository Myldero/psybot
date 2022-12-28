from psybot.config import config

from mongoengine import connect

client = connect(db=config.mongodb_db, host=config.mongodb_uri)
db = client[config.mongodb_db]
