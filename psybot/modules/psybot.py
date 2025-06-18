import discord

from discord import app_commands
from mongoengine import ValidationError

from psybot.utils import is_team_admin, get_settings, MAX_CHANNELS


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

SETTINGS_TYPES = {
    'team_role': discord.Role,
    'inactive_role': discord.Role,
    'admin_role': discord.Role,
    'ctfs_category': discord.CategoryChannel,
    'incomplete_category': discord.CategoryChannel,
    'complete_category': discord.CategoryChannel,
    'archive_category': discord.CategoryChannel,
    'ctf_archive_category': discord.CategoryChannel,
    'voice_category': discord.CategoryChannel,
    'export_channel': discord.TextChannel,
    'invite_channel': discord.TextChannel,
    'admin_channel': discord.TextChannel,
    'per_ctf_voice_channels': int,
    'enforce_categories': bool,
    'send_work_message': bool,
    'use_team_role_as_acl': bool,
    'invite_admin_only': bool,
    'hedgedoc_url': str,
    'ctftime_team': str,
}

class PsybotCommands(app_commands.Group):
    @app_commands.command(description="Update guild settings")
    @app_commands.guild_only
    @app_commands.choices(key=[app_commands.Choice(name=name, value=name) for name in SETTINGS_TYPES.keys()])
    @app_commands.check(is_team_admin)
    async def set(self, interaction: discord.Interaction, key: str, value: str):
        settings = get_settings(interaction.guild)
        if key not in SETTINGS_TYPES:
            raise app_commands.AppCommandError("Invalid key")
        typ = SETTINGS_TYPES[key]

        if typ == discord.Role:
            if not await check_role(interaction.guild, value):
                raise app_commands.AppCommandError("Value must be a Role ID")
            setattr(settings, key, int(value))
        elif typ == discord.CategoryChannel:
            if not await check_category(interaction.guild, value):
                raise app_commands.AppCommandError("Value must be a Category ID")
            setattr(settings, key, int(value))
        elif typ == discord.TextChannel:
            if not await check_channel(interaction.guild, value):
                raise app_commands.AppCommandError("Value must be a Channel ID")
            setattr(settings, key, int(value))
        elif typ == bool:
            if value.strip().lower() in ('y', 'yes', 'true', 't', '1'):
                setattr(settings, key, True)
            elif value.strip().lower() in ('n', 'no', 'false', 'f', '0'):
                setattr(settings, key, False)
            else:
                raise app_commands.AppCommandError("Invalid boolean value. Please choose (y/n)")
        elif typ == str:
            setattr(settings, key, value)
        elif typ == int:
            setattr(settings, key, int(value))
        else:
            raise app_commands.AppCommandError("Invalid key")

        try:
            settings.save()
        except ValidationError:
            raise app_commands.AppCommandError("Invalid value")

        await interaction.response.send_message("Setting updated", ephemeral=True)


    @app_commands.command(description="Show guild settings and info")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def info(self, interaction: discord.Interaction):
        settings = get_settings(interaction.guild)
        channel_count = len(interaction.guild.channels)

        response = f"Channels: {channel_count}/{MAX_CHANNELS}\n\n**Settings:**"

        for key, typ in SETTINGS_TYPES.items():
            value = getattr(settings, key)
            if value is None:
                value = "(unset)"
            elif typ == discord.Role:
                value = interaction.guild.get_role(value).mention + f" ({value})"
            elif typ == discord.TextChannel:
                value = interaction.guild.get_channel(value).mention + f" ({value})"
            elif key == 'hedgedoc_url':
                value = f'<{value}>'

            response += f"\n`{key}`: {value}"

        await interaction.response.send_message(response, ephemeral=True)


def add_commands(tree: app_commands.CommandTree, guild: discord.Object | None):
    tree.add_command(PsybotCommands(name="psybot"), guild=guild)
