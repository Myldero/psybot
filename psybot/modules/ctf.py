import datetime
import json
import os.path
import re
from typing import List, Optional

import discord
from discord import app_commands
from discord import ui

from psybot.models.ctf_category import CtfCategory
from psybot.utils import *
from psybot.modules.ctftime import Ctftime
from psybot.config import config

from psybot.models.challenge import Challenge
from psybot.models.ctf import Ctf


async def get_ctf_db(interaction: discord.Interaction, archived: Optional[bool] = False, allow_chall: bool = True) -> Ctf:
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


def user_to_dict(user):
    """
    Based on https://github.com/ekofiskctf/fiskebot/blob/eb774b7/bot/ctf_model.py#L156
    """
    return {
        "id": user.id,
        "nick": user.nick,
        "user": user.name,
        "avatar": user.avatar.key if user.avatar else None,
        "bot": user.bot,
    }


async def export_channels(channels: List[discord.TextChannel]):
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
    async def create(self, interaction: discord.Interaction, name: str, ctftime: Optional[str], private: bool = False):
        if len(interaction.guild.channels) >= MAX_CHANNELS - 3:
            raise app_commands.AppCommandError("There are too many channels on this discord server")
        name = sanitize_channel_name(name)

        new_role = await interaction.guild.create_role(name=name + "-team")
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            new_role: discord.PermissionOverwrite(view_channel=True)
        }

        if not private:
            overwrites[get_team_role(interaction.guild)] = discord.PermissionOverwrite(view_channel=True)

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

        await interaction.response.send_message(f"Created ctf {new_channel.mention}")

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
        ctf_db = await get_ctf_db(interaction, archived=None)
        assert isinstance(interaction.channel, discord.TextChannel)

        info = ctf_db.info or {}
        if field == "title":
            info[field] = value.replace("\n", "")
        elif field == "start" or field == "end":
            if value.isdigit():
                t = int(value)
            else:
                try:
                    t = int(datetime.datetime.strptime(value, "%Y-%m-%d %H:%M %z").timestamp())
                except ValueError:
                    try:
                        t = int(datetime.datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp())
                    except ValueError:
                        raise app_commands.AppCommandError('Invalid time. Either Unix Timestamp or "%Y-%m-%d %H:%M %z" (Timezone is optional but can for example be "+0200")')
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
        ctf_db = await get_ctf_db(interaction, allow_chall=False)
        assert isinstance(interaction.channel, discord.TextChannel)

        await interaction.response.defer()

        name = sanitize_channel_name(name)

        if ctf_db.info.get('title') == ctf_db.name:
            ctf_db.info['title'] = name
        ctf_db.name = name
        ctf_db.save()

        await interaction.channel.edit(name=name)

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            if channel:
                await channel.edit(name=f"{name}-{chall.category}-{chall.name}")
            else:
                chall.delete()
        await interaction.edit_original_response(content="The CTF has been renamed")

    @app_commands.command(description="Export an archived CTF")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def export(self, interaction: discord.Interaction):
        ctf_db = await get_ctf_db(interaction, allow_chall=False)
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
            # This is due to os.makedirs not succeeding
            await interaction.edit_original_response(content=f"Invalid file permissions when exporting CTF")
            return

        export_channel = get_export_channel(interaction.guild)
        await export_channel.send(files=[discord.File(filepath, filename=f"{ctf_db.name}.json")])
        await interaction.edit_original_response(content=f"The CTF has been exported")

    @app_commands.command(description="Delete a CTF and its channels")
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def delete(self, interaction: discord.Interaction, security: Optional[str]):
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


async def category_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    current = sanitize_channel_name(current)
    query = CtfCategory.objects(name=re.compile("^" + re.escape(current)), guild_id=interaction.guild_id).order_by('-count')[:25]
    return [app_commands.Choice(name=c["name"], value=c["name"]) for c in query]


@app_commands.command(description="Add a challenge")
@app_commands.autocomplete(category=category_autocomplete)
@app_commands.guild_only
async def add(interaction: discord.Interaction, category: str, name: str):
    ctf_db = await get_ctf_db(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    if len(interaction.guild.channels) >= MAX_CHANNELS - 3:
        admin_role = get_admin_role(interaction.guild)
        await interaction.response.send_message(f"There are too many channels on this discord server. Please "
                                                f"wait for an admin to delete some channels. {admin_role.mention}",
                                                allowed_mentions=discord.AllowedMentions.all())
        return
    incomplete_category = get_incomplete_category(interaction.guild)

    ctf = sanitize_channel_name(ctf_db.name)
    category = sanitize_channel_name(category)
    name = sanitize_channel_name(name)
    fullname = f"{ctf}-{category}-{name}"

    settings = get_settings(interaction.guild)
    if settings.enforce_categories:
        if not CtfCategory.objects(name=category, guild_id=interaction.guild_id):
            raise app_commands.AppCommandError("Invalid CTF category")

    if old_chall := Challenge.objects(name=name, category=category, ctf=ctf_db).first():
        if interaction.guild.get_channel(old_chall.channel_id):
            raise app_commands.AppCommandError("A challenge with that name already exists")
        else:
            old_chall.delete()

    new_channel = await create_channel(fullname, interaction.channel.overwrites, incomplete_category)

    chall_db = Challenge(name=name, category=category, channel_id=new_channel.id, ctf=ctf_db)
    chall_db.save()

    ctf_category = CtfCategory.objects(name=category, guild_id=interaction.guild_id).first()
    if ctf_category is None:
        ctf_category = CtfCategory(name=category, guild_id=interaction.guild_id, count=0)
    ctf_category.count += 1
    ctf_category.save()

    await interaction.response.send_message("Added challenge {}".format(new_channel.mention))


@app_commands.command(description="Invite a user to the CTF")
@app_commands.guild_only
async def invite(interaction: discord.Interaction, user: discord.Member):
    ctf_db = await get_ctf_db(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    await user.add_roles(interaction.guild.get_role(ctf_db.role_id), reason="Invited to CTF")
    await interaction.response.send_message("Invited user {}".format(user.mention))


def add_commands(tree: app_commands.CommandTree, guild: Optional[discord.Object]):
    tree.add_command(CtfCommands(name="ctf"), guild=guild)
    tree.add_command(add, guild=guild)
    tree.add_command(invite, guild=guild)
