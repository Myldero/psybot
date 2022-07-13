import os
import sys

import discord


def parse_variable(variable, vartype, default=None, required=False):
    value = os.getenv(variable, None)
    if not value:
        if required:
            print(f"Missing required environment variable: {variable}", file=sys.stderr)
            exit(1)
        return default

    if vartype == str:
        return value
    elif vartype == bool:
        return True if value.lower() in ["true", "1", "t", "y", "yes"] else False
    elif vartype == int:
        return int(value) if value.isdigit() else default


class Config:
    def __init__(self):
        # Required
        self.bot_token = parse_variable("BOT_TOKEN", str, required=True)
        self.guild_id = parse_variable("GUILD_ID", int, required=True)

        # Options
        self.mongodb_uri = parse_variable("MONGODB_URI", str, default="mongodb://localhost:27017")
        self.mongodb_db = parse_variable("MONGODB_DB", str, default="psybot")
        self.ctftime_team = parse_variable("CTFTIME_TEAM", str)
        self.backups_dir = parse_variable("BACKUPS_DIR", str, default="../backups")
        self.enforce_categories = parse_variable("ENFORCE_CATEGORIES", bool, default=True)

        # Discord ids. These can be supplied on first run, if they already exist
        self.team_role = parse_variable("TEAM_ROLE", int)
        self.admin_role = parse_variable("ADMIN_ROLE", int)
        self.ctfs_category = parse_variable("CTFS_CATEGORY", int)
        self.incomplete_category = parse_variable("INCOMPLETE_CATEGORY", int)
        self.complete_category = parse_variable("COMPLETE_CATEGORY", int)
        self.archive_category = parse_variable("ARCHIVE_CATEGORY", int)
        self.ctf_archive_category = parse_variable("CTF_ARCHIVE_CATEGORY", int)
        self.export_channel = parse_variable("EXPORT_CHANNEL", int)

    @staticmethod
    def _discord_get(guild: discord.Guild, value, id_type):
        if id_type == "role":
            return guild.get_role(value)
        elif id_type == "channel" or id_type == "category":
            return guild.get_channel(value)

    @staticmethod
    def _discord_create(guild: discord.Guild, name, id_type):
        if id_type == "role":
            return guild.create_role(name=name)
        elif id_type == "channel":
            return guild.create_text_channel(name=name)
        elif id_type == "category":
            return guild.create_category_channel(name=name)

    async def setup_discord_ids(self, guild: discord.Guild, db):
        ids = await db.discord_ids.find_one({'guild_id': guild.id})
        ids = ids or {}

        discord_values = {
            "team_role": "Team Member",
            "admin_role": "Team Admin",
            "ctfs_category": "CTFS",
            "incomplete_category": "INCOMPLETE CHALLENGES",
            "complete_category": "COMPLETE CHALLENGES",
            "archive_category": "ARCHIVE",
            "ctf_archive_category": "ARCHIVED CTFS",
            "export_channel": "export"
        }

        # Validate ids
        for key in discord_values:
            key_type = key.rsplit("_", 1)[-1]
            value = self.__dict__[key]
            if value:
                if not self._discord_get(guild, value, key_type):
                    print(f"Invalid discord id for {key}: {value}", file=sys.stderr)
                    exit(1)
                ids[key] = value
            elif key in ids:
                if not self._discord_get(guild, ids[key], key_type):
                    del ids[key]

        # Create missing ids
        for key in discord_values:
            key_type = key.rsplit("_", 1)[-1]
            if key not in ids:
                ids[key] = (await self._discord_create(guild, discord_values[key], key_type)).id
            self.__dict__[key] = ids[key]

        # Save the ids in the database
        if (await db.discord_ids.update_one({'guild_id': guild.id}, {'$set': ids})).matched_count == 0:
            await db.discord_ids.insert_one(dict(guild_id=guild.id, **ids))


config = Config()
