import datetime
import json
import os.path
import re
from typing import List, Optional

import discord
from discord import app_commands
from discord import ui

from psybot.config import config
from psybot.models.ctf_category import CtfCategory
from psybot.utils import move_channel, create_channel, delete_channel, MAX_CHANNELS
from psybot.modules.ctftime import Ctftime

from psybot.models.challenge import Challenge
from psybot.models.ctf import Ctf


async def get_ctf_db(interaction: discord.Interaction, archived: Optional[bool] = False) -> Optional[Ctf]:
    ctf_db: Ctf = Ctf.objects(channel_id=interaction.channel.id).first()
    if ctf_db is None:
        await interaction.response.send_message("Not a CTF channel!", ephemeral=True)
        return None
    if archived is False and ctf_db.archived:
        await interaction.response.send_message("This CTF is archived!", ephemeral=True)
        return None
    if archived is True and not ctf_db.archived:
        await interaction.response.send_message("This CTF is not archived!", ephemeral=True)
        return None
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
    async def create(self, interaction: discord.Interaction, name: str, ctftime: Optional[str], private: bool = False):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can create a CTF event", ephemeral=True)
            return
        if len(interaction.guild.channels) >= MAX_CHANNELS - 3:
            await interaction.response.send_message("There are too many channels on this discord server", ephemeral=True)
            return

        name = name.lower().replace(" ", "_").replace("-", "_")

        new_role = await interaction.guild.create_role(name=name + "-team")
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            new_role: discord.PermissionOverwrite(view_channel=True)
        }

        if not private:
            overwrites[interaction.guild.get_role(config.team_role)] = discord.PermissionOverwrite(view_channel=True)

        ctf_category = interaction.guild.get_channel(config.ctfs_category)
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
    async def update(self, interaction: discord.Interaction, field: str, value: str):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can update CTF information", ephemeral=True)
            return
        if not (ctf_db := await get_ctf_db(interaction, archived=None)) or not isinstance(interaction.channel, discord.TextChannel):
            return
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
                        await interaction.response.send_message("Invalid time. Either Unix Timestamp or \"%Y-%m-%d %H:%M %z\" (Timezone is optional but can for example be \"+0200\")", ephemeral=True)
                        return
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
                await interaction.response.send_message("Invalid url", ephemeral=True)
                return
        elif field == "ctftime":
            regex_ctftime = re.search(r'^(?:https?://ctftime.org/event/)?(\d+)/?$', value)
            if regex_ctftime:
                info['ctftime_id'] = int(regex_ctftime.group(1))
                ctf_info = await Ctftime.get_ctf_info(info['ctftime_id'])
                info |= ctf_info
            else:
                await interaction.response.send_message("Invalid ctftime link", ephemeral=True)
                return
        else:
            await interaction.response.send_message("Invalid field", ephemeral=True)
            return

        ctf_db.info = info
        ctf_db.save()
        await interaction.channel.get_partial_message(ctf_db.info_id).edit(content=create_info_message(info))
        await interaction.response.send_message("Updated info", ephemeral=True)

    @app_commands.command(description="Archive a CTF")
    async def archive(self, interaction: discord.Interaction):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can archive a CTF event", ephemeral=True)
            return
        if not (ctf_db := await get_ctf_db(interaction)) or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer()

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            if channel:
                await move_channel(channel, interaction.guild.get_channel(config.archive_category))
            else:
                chall.delete()

        await move_channel(interaction.channel, interaction.guild.get_channel(config.ctf_archive_category), challenge=False)
        ctf_db.archived = True
        ctf_db.save()
        await interaction.edit_original_message(content="The CTF has been archived")

    @app_commands.command(description="Unarchive a CTF")
    async def unarchive(self, interaction: discord.Interaction):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can unarchive a CTF event", ephemeral=True)
            return
        if not (ctf_db := await get_ctf_db(interaction, archived=True)) or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer()

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            target_category = config.complete_category if chall.solved else config.incomplete_category
            if channel:
                await move_channel(channel, interaction.guild.get_channel(target_category))
            else:
                chall.delete()

        await move_channel(interaction.channel, interaction.guild.get_channel(config.ctfs_category), challenge=False)
        ctf_db.archived = False
        ctf_db.save()
        await interaction.edit_original_message(content="The CTF has been unarchived")

    @app_commands.command(description="Export an archived CTF")
    async def export(self, interaction: discord.Interaction):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can export a CTF event", ephemeral=True)
            return
        if not (ctf_db := await get_ctf_db(interaction)) or not isinstance(interaction.channel, discord.TextChannel):
            return

        await interaction.response.defer()

        channels = [interaction.channel]

        for chall in Challenge.objects(ctf=ctf_db):
            channel = interaction.guild.get_channel(chall.channel_id)
            if channel:
                channels.append(channel)
            else:
                chall.delete()

        ctf_export = await export_channels(channels)

        if not os.path.exists(config.backups_dir):
            os.makedirs(config.backups_dir)
        filepath = os.path.join(config.backups_dir, ctf_db.name + ".json")
        with open(filepath, 'w') as f:
            f.write(json.dumps(ctf_export))

        export_channel = interaction.guild.get_channel(config.export_channel)
        await export_channel.send(files=[discord.File(filepath)])
        await interaction.edit_original_message(content=f"The CTF has been exported")

    @app_commands.command(description="Delete a CTF and its channels")
    async def delete(self, interaction: discord.Interaction, security: Optional[str]):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can delete a CTF event", ephemeral=True)
            return
        if not (ctf_db := await get_ctf_db(interaction, archived=None)) or not isinstance(interaction.channel, discord.TextChannel):
            return
        if security is None:
            await interaction.response.send_message("Please supply the security parameter \"{}\"".format(interaction.channel.name), ephemeral=True)
            return
        elif security != interaction.channel.name:
            await interaction.response.send_message("Wrong security parameter", ephemeral=True)
            return
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
    current = current.lower().replace(" ", "_").replace("-", "_")
    query = CtfCategory.objects(name=re.compile("^" + re.escape(current))).order_by('-count')[:25]
    return [app_commands.Choice(name=c["name"], value=c["name"]) for c in query]


@app_commands.command(description="Add a challenge")
@app_commands.autocomplete(category=category_autocomplete)
async def add(interaction: discord.Interaction, category: str, name: str):
    if not (ctf_db := await get_ctf_db(interaction)) or not isinstance(interaction.channel, discord.TextChannel):
        return
    if len(interaction.guild.channels) >= MAX_CHANNELS - 3:
        admin_role = interaction.guild.get_role(config.admin_role)
        await interaction.response.send_message(f"There are too many channels on this discord server. Please "
                                                f"wait for an admin to delete some channels. {admin_role.mention}",
                                                allowed_mentions=discord.AllowedMentions.all())
        return
    incomplete_category = interaction.guild.get_channel(config.incomplete_category)

    ctf = interaction.channel.name
    category = category.lower().replace(" ", "_").replace("-", "_")
    name = name.lower().replace(" ", "_").replace("-", "_")
    fullname = f"{ctf}-{category}-{name}"

    if config.enforce_categories:
        if not CtfCategory.objects(name=category):
            await interaction.response.send_message("Invalid CTF category", ephemeral=True)
            return

    new_channel = await create_channel(fullname, interaction.channel.overwrites, incomplete_category)

    chall_db = Challenge(name=name, category=category, channel_id=new_channel.id, ctf=ctf_db)
    chall_db.save()

    ctf_category = CtfCategory.objects(name=category).first()
    if ctf_category is None:
        ctf_category = CtfCategory(name=category, count=0)
    ctf_category.count += 1
    ctf_category.save()

    await interaction.response.send_message("Added challenge {}".format(new_channel.mention))


@app_commands.command(description="Invite a user to the CTF")
async def invite(interaction: discord.Interaction, user: discord.Member):
    if not (ctf_db := await get_ctf_db(interaction)) or not isinstance(interaction.channel, discord.TextChannel):
        return

    await user.add_roles(interaction.guild.get_role(ctf_db.role_id), reason="Invited to CTF")
    await interaction.response.send_message("Invited user {}".format(user.mention))


def add_commands(tree: app_commands.CommandTree):
    tree.add_command(CtfCommands(name="ctf"), guild=discord.Object(id=config.guild_id))
    tree.add_command(add, guild=discord.Object(id=config.guild_id))
    tree.add_command(invite, guild=discord.Object(id=config.guild_id))
