import json
import os.path
import re
import discord

from discord import app_commands, ui
from dateutil import parser as dateutil_parser

from psybot.models.ctf_category import CtfCategory
from psybot.utils import *
from psybot.modules.ctftime import Ctftime
from psybot.config import config

from psybot.models.challenge import Challenge
from psybot.models.ctf import Ctf


async def get_ctf_db(interaction: discord.Interaction, archived: bool | None = False, allow_chall: bool = True) -> Ctf:
    ctf_db: Ctf = Ctf.objects(channel_id=interaction.channel_id).first()
    if ctf_db is None:
        chall_db: Challenge = Challenge.objects(channel_id=interaction.channel_id).first()
        if not allow_chall or chall_db is None:
            raise app_commands.AppCommandError("Not a CTF channel!")
        ctf_db: Ctf = chall_db.ctf
    if archived is False and ctf_db.archived:
        raise app_commands.AppCommandError("This CTF is archived!")
    if archived is True and not ctf_db.archived:
        raise app_commands.AppCommandError("This CTF is not archived!")
    return ctf_db


def user_to_dict(user: discord.Member | discord.User):
    """
    Based on https://github.com/ekofiskctf/fiskebot/blob/eb774b7/bot/ctf_model.py#L156
    """
    return {
        "id": user.id,
        "nick": user.nick if isinstance(user, discord.Member) else None,
        "user": user.name,
        "avatar": user.avatar.key if user.avatar else None,
        "bot": user.bot,
    }


async def export_channels(channels: list[discord.TextChannel]):
    """
    Based on https://github.com/ekofiskctf/fiskebot/blob/eb774b7/bot/ctf_model.py#L778
    """
    # TODO: Backup attachments, since discord deletes these when messages are deleted
    ctf_export = {"channels": []}
    for channel in channels:
        chan = {
            "name": channel.name,
            "topic": channel.topic,
            "messages": [],
            "pins": [m.id for m in await channel.pins()],
        }

        async for message in channel.history(limit=None, oldest_first=True):
            entry = {
                "id": message.id,
                "created_at": message.created_at.isoformat(),
                "content": message.clean_content,
                "author": user_to_dict(message.author),
                "attachments": [{"filename": a.filename, "url": str(a.url)} for a in message.attachments],
                "channel": {
                    "name": message.channel.name
                },
                "edited_at": (
                    message.edited_at.isoformat()
                    if message.edited_at is not None
                    else message.edited_at
                ),
                "embeds": [e.to_dict() for e in message.embeds],
                "mentions": [user_to_dict(mention) for mention in message.mentions],
                "channel_mentions": [{"id": c.id, "name": c.name} for c in message.channel_mentions],
                "mention_everyone": message.mention_everyone,
                "reactions": [
                    {
                        "count": r.count,
                        "emoji": r.emoji if isinstance(r.emoji, str) else {"name": r.emoji.name, "url": r.emoji.url},
                    } for r in message.reactions
                ]
            }
            chan["messages"].append(entry)
        ctf_export["channels"].append(chan)
    return ctf_export


def create_info_message(info):
    msg = discord.utils.escape_mentions(info['title'])
    if 'start' in info or 'end' in info:
        msg += "\n"
    if 'start' in info:
        msg += f"\n**START** <t:{info['start']}:R> <t:{info['start']}>"
    if 'end' in info:
        msg += f"\n**END** <t:{info['end']}:R> <t:{info['end']}>"
    if 'url' in info:
        msg += f"\n\n{info['url']}"
    if 'creds' in info:
        msg += "\n\n**CREDENTIALS**\n" + discord.utils.escape_mentions(info['creds'])
    return msg


class CtfCommands(app_commands.Group):
    @app_commands.command(description="Create a new CTF event")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def create(self, interaction: discord.Interaction, name: str, ctftime: str | None, private: bool = False):
        if len(interaction.guild.channels) >= MAX_CHANNELS - 3:
            raise app_commands.AppCommandError("There are too many channels on this discord server")
        name = sanitize_channel_name(name)
        if not name:
            raise app_commands.AppCommandError("Invalid CTF name")

        await interaction.response.defer()

        settings = get_settings(interaction.guild)

        new_role = await interaction.guild.create_role(name=name + "-team")
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            new_role: discord.PermissionOverwrite(view_channel=True)
        }
        if not private and settings.use_team_role_as_acl:
            overwrites[get_team_role(interaction.guild)] = discord.PermissionOverwrite(view_channel=True)
        if private:
            await interaction.user.add_roles(new_role)

        ctf_category = get_ctfs_category(interaction.guild)
        new_channel = await create_channel(name, overwrites, ctf_category, challenge=False)

        info = {'title': name}
        if ctftime:
            regex_ctftime = re.search(r'^(?:https?://ctftime.org/event/)?(\d+)/?$', ctftime)
            if regex_ctftime:
                info['ctftime_id'] = int(regex_ctftime.group(1))
                ctf_info = await Ctftime.get_ctf_info(info['ctftime_id'])
                info |= ctf_info

        info_msg = await new_channel.send(create_info_message(info))

        await info_msg.pin()

        ctf_db = Ctf(name=name, channel_id=new_channel.id, role_id=new_role.id, info=info, info_id=info_msg.id, private=private)
        ctf_db.save()

        await interaction.edit_original_response(content=f"Created ctf {new_channel.mention}")

        if not private and not settings.use_team_role_as_acl:
            for member in get_team_role(interaction.guild).members:
                await member.add_roles(new_role)


    @app_commands.command(description="Update CTF information")
    @app_commands.choices(field=[
        app_commands.Choice(name="title", value="title"),
        app_commands.Choice(name="start", value="start"),
        app_commands.Choice(name="end", value="end"),
        app_commands.Choice(name="url", value="url"),
        app_commands.Choice(name="creds", value="creds"),
        app_commands.Choice(name="ctftime", value="ctftime")
    ])
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def update(self, interaction: discord.Interaction, field: str, value: str):
        ctf_db = await get_ctf_db(interaction, archived=None, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        info = ctf_db.info or {}
        if field == "title":
            info[field] = value.replace("\n", "")
        elif field == "start" or field == "end":
            if value.isdigit():
                t = int(value)
            else:
                try:
                    t = int(dateutil_parser.parse(value).timestamp())
                except dateutil_parser.ParserError:
                    raise app_commands.AppCommandError("Invalid time, please use any standard time format")
            info[field] = t
        elif field == "creds":
            c = value.split(":", 1)
            username, password = c[0], c[1] if len(c) > 1 else "password"
            original = f"Name: `{username}`\nPassword: `{password}`"

            class CredsModal(ui.Modal, title='Edit Credentials'):
                edit = ui.TextInput(label='Edit', style=discord.TextStyle.paragraph, default=original, max_length=1000)

                async def on_submit(self, submit_interaction: discord.Interaction):
                    info["creds"] = self.edit.value
                    ctf_db.info = info
                    ctf_db.save()
                    await interaction.channel.get_partial_message(ctf_db.info_id).edit(content=create_info_message(info))
                    await submit_interaction.response.send_message("Updated info", ephemeral=True)

            await interaction.response.send_modal(CredsModal())
            return
        elif field == "url":
            if re.search(r'^https?://', value):
                info["url"] = value
            else:
                raise app_commands.AppCommandError("Invalid url")
        elif field == "ctftime":
            regex_ctftime = re.search(r'^(?:https?://ctftime.org/event/)?(\d+)/?$', value)
            if regex_ctftime:
                info['ctftime_id'] = int(regex_ctftime.group(1))
                ctf_info = await Ctftime.get_ctf_info(info['ctftime_id'])
                for key, value in ctf_info.items():
                    info[key] = value
            else:
                raise app_commands.AppCommandError("Invalid ctftime link")
        else:
            raise app_commands.AppCommandError("Invalid field")

        ctf_db.info = info
        ctf_db.save()
        await interaction.channel.get_partial_message(ctf_db.info_id).edit(content=create_info_message(info))
        await interaction.response.send_message("Updated info", ephemeral=True)

    @app_commands.command(description="Archive a CTF")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def archive(self, interaction: discord.Interaction):
        ctf_db = await get_ctf_db(interaction, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        await interaction.response.defer()

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            if channel:
                await move_channel(channel, get_archive_category(interaction.guild))
            else:
                chall.delete()

        await move_channel(interaction.channel, get_ctf_archive_category(interaction.guild), challenge=False)
        ctf_db.archived = True
        ctf_db.save()
        await interaction.edit_original_response(content="The CTF has been archived")

    @app_commands.command(description="Unarchive a CTF")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def unarchive(self, interaction: discord.Interaction):
        ctf_db = await get_ctf_db(interaction, archived=True, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        await interaction.response.defer()

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            target_category = get_complete_category(interaction.guild) if chall.solved else get_incomplete_category(interaction.guild)
            if channel:
                await move_channel(channel, target_category)
            else:
                chall.delete()

        await move_channel(interaction.channel, get_ctfs_category(interaction.guild), challenge=False)
        ctf_db.archived = False
        ctf_db.save()
        await interaction.edit_original_response(content="The CTF has been unarchived")

    @app_commands.command(description="Rename a CTF and its channels")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def rename(self, interaction: discord.Interaction, name: str):
        ctf_db = await get_ctf_db(interaction, archived=None, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        name = sanitize_channel_name(name)
        if not name:
            raise app_commands.AppCommandError("Invalid CTF name")

        await interaction.response.defer()

        if ctf_db.info.get('title') == ctf_db.name:
            ctf_db.info['title'] = name
        ctf_db.name = name
        ctf_db.save()

        await interaction.channel.edit(name=name)

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            if channel:
                if chall.category:
                    await channel.edit(name=f"{name}-{chall.category}-{chall.name}")
                else:
                    await channel.edit(name=f"{name}-{chall.name}")
            else:
                chall.delete()
        await interaction.edit_original_response(content="The CTF has been renamed")

    @app_commands.command(description="Export an archived CTF")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def export(self, interaction: discord.Interaction):
        ctf_db = await get_ctf_db(interaction, archived=None, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        await interaction.response.defer()

        channels = [interaction.channel]

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            if channel:
                channels.append(channel)
            else:
                chall.delete()

        ctf_export = await export_channels(channels)

        filepath = os.path.join(config.backups_dir, str(interaction.guild_id), f"{interaction.channel_id}_{ctf_db.name}.json")
        try:
            os.makedirs(os.path.dirname(filepath))
        except OSError:
            pass

        try:
            with open(filepath, 'w') as f:
                f.write(json.dumps(ctf_export, separators=(",", ":")))
        except FileNotFoundError:
            # Export dir was not created
            raise app_commands.AppCommandError("Invalid file permissions when exporting CTF")

        export_channel = get_export_channel(interaction.guild)
        await export_channel.send(files=[discord.File(filepath, filename=f"{ctf_db.name}.json")])
        await interaction.edit_original_response(content=f"The CTF has been exported")

    @app_commands.command(description="Delete a CTF and its channels")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def delete(self, interaction: discord.Interaction, security: str | None):
        ctf_db = await get_ctf_db(interaction, archived=None, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        if security is None:
            raise app_commands.AppCommandError("Please supply the security parameter \"{}\"".format(interaction.channel.name))
        elif security != interaction.channel.name:
            raise app_commands.AppCommandError("Wrong security parameter")
        await interaction.response.defer()

        for chall in Challenge.objects(ctf=ctf_db):
            try:
                await delete_channel(interaction.guild.get_channel(chall.channel_id))
            except AttributeError:
                pass

        try:
            await interaction.guild.get_role(ctf_db.role_id).delete(reason="Deleted CTF channels")
        except AttributeError:
            pass
        await delete_channel(interaction.channel)
        Challenge.objects(ctf=ctf_db).delete()
        ctf_db.delete()


@app_commands.command(description="Invite a user to the CTF")
@app_commands.guild_only
async def invite(interaction: discord.Interaction, user: discord.Member):
    settings = get_settings(interaction.guild)
    if settings.invite_admin_only and not get_admin_role(interaction.guild) in interaction.user.roles:
        raise app_commands.AppCommandError("Only team admins are allowed to run this command")
    ctf_db = await get_ctf_db(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    await user.add_roles(interaction.guild.get_role(ctf_db.role_id), reason=f"Invited by {interaction.user.name}")
    await interaction.response.send_message("Invited user {}".format(user.mention))


@app_commands.command(description="Invite all members with a specific role to the CTF")
@app_commands.guild_only
async def inviterole(interaction: discord.Interaction, role: discord.Role):
    settings = get_settings(interaction.guild)
    if settings.invite_admin_only and not get_admin_role(interaction.guild) in interaction.user.roles:
        raise app_commands.AppCommandError("Only team admins are allowed to run this command")
    ctf_db = await get_ctf_db(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    if not role.members:
        raise app_commands.AppCommandError("The specified role doesn't have any members")

    for user in role.members:
        await user.add_roles(interaction.guild.get_role(ctf_db.role_id), reason=f"Invited by {interaction.user.name}")
    mention_message = ", ".join(user.mention for user in role.members)
    await interaction.response.send_message("Invited user{} {}".format('s' if len(role.members) > 1 else '', mention_message))


@app_commands.command(description="Leave a CTF")
@app_commands.guild_only
async def leave(interaction: discord.Interaction):
    ctf_db = await get_ctf_db(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    ctf_role = interaction.guild.get_role(ctf_db.role_id)
    if ctf_role in interaction.user.roles:
        await interaction.user.remove_roles(ctf_role, reason="Left CTF")
        await interaction.response.send_message(f"{interaction.user.mention} Left the CTF")
    else:
        await interaction.response.send_message("Cannot leave CTF", ephemeral=True)


@app_commands.command(description="Remove a user from the CTF")
@app_commands.guild_only
@app_commands.check(is_team_admin)
async def remove(interaction: discord.Interaction, user: discord.Member):
    ctf_db = await get_ctf_db(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    ctf_role = interaction.guild.get_role(ctf_db.role_id)
    if ctf_role in user.roles:
        await user.remove_roles(ctf_role, reason=f"Removed by {interaction.user.name}")
        await interaction.response.send_message(f"Removed user {user.mention}")
    else:
        await interaction.response.send_message("Cannot remove user from CTF", ephemeral=True)


def add_commands(tree: app_commands.CommandTree, guild: discord.Object | None):
    tree.add_command(CtfCommands(name="ctf"), guild=guild)
    tree.add_command(invite, guild=guild)
    tree.add_command(inviterole, guild=guild)
    tree.add_command(leave, guild=guild)
    tree.add_command(remove, guild=guild)
