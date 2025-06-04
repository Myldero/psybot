import logging
import os


def parse_variable(variable: str, vartype: type, default=None, required=False):
    value = os.getenv(variable, None)
    if not value:
        if required:
            logging.fatal(f"Missing required environment variable: {variable}")
            exit(1)
        return default

    if vartype == str:
        return value
    elif vartype == bool:
        return value.lower() in ["true", "1", "t", "y", "yes"]
    elif vartype == int:
        return int(value) if value.isdigit() else default
    raise ValueError("Invalid variable type")


BACKUPS_DIR_DEFAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../backups'))

class Config:
    def __init__(self):
        # Required
        self.bot_token = parse_variable("BOT_TOKEN", str, required=True)

        # Options
        self.guild_id = parse_variable("GUILD_ID", int)
        self.mongodb_uri = parse_variable("MONGODB_URI", str, default="mongodb://localhost:27017")
        self.mongodb_db = parse_variable("MONGODB_DB", str, default="psybot")
        self.backups_dir = parse_variable("BACKUPS_DIR", str, default=BACKUPS_DIR_DEFAULT)
        self.ctftime_url = parse_variable("CTFTIME_URL", str, default="https://ctftime.org")


config = Config()
