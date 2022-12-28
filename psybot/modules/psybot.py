from typing import Optional

import discord
from discord import app_commands
from mongoengine import ValidationError

from psybot.utils import is_team_admin, get_settings


async def check_role(guild: discord.Guild, value: str):
    if not value.isdigit():
        return False
    return guild.get_role(int(value)) is not None


async def check_category(guild: discord.Guild, value: str):
    if not value.isdigit():
        return False
    channel = guild.get_channel(int(value))
    return isinstance(channel, discord.CategoryChannel)


async def check_channel(guild: discord.Guild, value: str):
    if not value.isdigit():
        return False
    channel = guild.get_channel(int(value))
    return isinstance(channel, discord.TextChannel)


SETTING_KEYS = ['team_role', 'admin_role', 'ctfs_category', 'incomplete_category', 'complete_category',
                 'archive_category', 'ctf_archive_category', 'export_channel', 'enforce_categories',
                 'hedgedoc_url', 'ctftime_team']

class PsybotCommands(app_commands.Group):
    @app_commands.command(description="Update guild setting")
    @app_commands.guild_only
    @app_commands.choices(key=[app_commands.Choice(name=name, value=name) for name in SETTING_KEYS])
    @app_commands.check(is_team_admin)
    async def set(self, interaction: discord.Interaction, key: str, value: str):
        settings = get_settings(interaction.guild)

        if key.endswith("_role"):
            if not await check_role(interaction.guild, value):
                raise app_commands.AppCommandError("Value must be a Role ID")
            setattr(settings, key, int(value))
        elif key.endswith("_category"):
            if not await check_category(interaction.guild, value):
                raise app_commands.AppCommandError("Value must be a Category ID")
            setattr(settings, key, int(value))
        elif key.endswith("_channel"):
            if not await check_channel(interaction.guild, value):
                raise app_commands.AppCommandError("Value must be a Channel ID")
            setattr(settings, key, int(value))
        elif key in ('enforce_categories',):
            setattr(settings, key, value.strip().lower() in ('y', 'yes', 'true', 't', '1'))
        else:
            setattr(settings, key, value)

        try:
            settings.save()
        except ValidationError:
            raise app_commands.AppCommandError("Invalid value")

        await interaction.response.send_message("Setting updated", ephemeral=True)


def add_commands(tree: app_commands.CommandTree, guild: Optional[discord.Object]):
    tree.add_command(PsybotCommands(name="psybot"), guild=guild)
