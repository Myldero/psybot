import discord
import logging
import traceback
import aiohttp
import asyncio
import json
import os

from pathlib import Path
from dateutil import parser as dateutil_parser

try:
    from psybot.config import config
except ModuleNotFoundError:
    class Config:
        def __init__(self):
            self.disable_download = False
    config = Config()


def user_to_dict(user: discord.Member | discord.User) -> dict:
    d = {
        "id": user.id,
        "nick": user.display_name,
        "user": user.name,
        "avatar": user.display_avatar.key if user.display_avatar else None,
    }
    if user.bot:
        d['bot'] = True
    return d


async def export_channels(channels: list[discord.TextChannel], attachment_dir: Path) -> dict:
    ctf_export = {"channels": []}
    channels_and_threads = []
    for channel in channels:
        channels_and_threads.append(channel)
        for thread in channel.threads:
            channels_and_threads.append(thread)
        async for thread in channel.archived_threads(private=False, limit=None):
            channels_and_threads.append(thread)

    async with aiohttp.ClientSession() as session:
        for channel in channels_and_threads:
            chan = {
                "id": channel.id,
                "name": channel.name,
                "messages": [],
                "pins": [m.id for m in await channel.pins()],
            }

            if hasattr(channel, "topic") and channel.topic:
                chan["topic"] = channel.topic
            if isinstance(channel, discord.Thread):
                chan["thread_parent"] = channel.parent_id

            async for message in channel.history(limit=None, oldest_first=True):
                entry = {
                    "id": message.id,
                    "created_at": message.created_at.isoformat(),
                    "content": message.content,
                    "author": user_to_dict(message.author),
                    "attachments": [{"filename": a.filename, "url": str(a.url)} for a in message.attachments],
                    "edited_at": message.edited_at.isoformat() if message.edited_at is not None else None,
                    "embeds": [e.to_dict() for e in message.embeds],
                    "mentions": [user_to_dict(mention) for mention in message.mentions],
                    "channel_mentions": [{"id": c.id, "name": c.name} for c in message.channel_mentions],
                    "reactions": [
                        {
                            "count": r.count,
                            "emoji": r.emoji if isinstance(r.emoji, str) else {"name": r.emoji.name, "url": r.emoji.url},
                        } for r in message.reactions
                    ]
                }
                if message.mention_everyone:
                    entry["mention_everyone"] = True
                if message.thread:
                    entry['thread'] = message.thread.id

                if not config.disable_download:
                    for j, attachment in enumerate(entry["attachments"]):
                        file_path = attachment_dir / "{}{}_{}".format(message.id, j, attachment["filename"].replace('/',''))
                        try:
                            async with session.get(attachment["url"]) as resp:
                                if resp.status == 200:
                                    with open(file_path, 'wb') as f:
                                        while True:
                                            chunk = await resp.content.readany()
                                            if not chunk:
                                                break
                                            f.write(chunk)
                                else:
                                    logging.warning(f"Export: failed with status {resp.status}")
                                    attachment["error"] = f"Failed with status {resp.status}"
                        except Exception as e:
                            traceback.print_exc()
                            attachment["error"] = str(e)

                chan["messages"].append(entry)
            ctf_export["channels"].append(chan)
    return ctf_export


def split_big_message(msg: str) -> tuple[str, str]:
    """split 4000-character message into two messages of up to 2000 characters"""
    assert 2000 < len(msg) <= 4000
    # First, try to find a good place to split
    if len(msg) - (idx := msg.rfind('\n', 0, 2001)) - 1 <= 2000:
        return msg[:idx], msg[idx + 1:]
    if len(msg) - (idx := msg.rfind(' ', 0, 2001)) - 1 <= 2000:
        return msg[:idx], msg[idx + 1:]
    # Give up and just split at 2000
    return msg[:2000], msg[2000:]


FILE_LIMIT = 10_000_000


async def reexport_ctf(export_channel: discord.TextChannel, ctf_export: dict, attachment_dir: Path):
    if not ctf_export["channels"] or not ctf_export["channels"][0]['messages']:
        return  # Empty. Let's just skip

    name = ctf_export["channels"][0]["name"]

    channel_hooks = await export_channel.webhooks()
    if channel_hooks:
        hook = channel_hooks[0]
    else:
        hook = await export_channel.create_webhook(name='PsyBot', reason='Exporting')

    # Get first message timestamp

    start_time = int(dateutil_parser.parse(ctf_export["channels"][0]['messages'][0]["created_at"]).timestamp())

    start_message = await export_channel.send(f'Archive of {name} <t:{start_time}>')
    thread = await export_channel.create_thread(name=name, message=start_message, reason=f"Re-exporting {name}")

    thread_starters = {}
    channel_headers = []

    # TODO: Fix jump_urls and intra-ctf channel links. There's a chance that it requires us to edit a hook message later, since the target message doesn't exist yet. Also need to ensure size doesn't exceed 2000

    for channel in ctf_export["channels"]:

        header_content = '# {}{}'.format('Thread: ' if channel.get('thread_parent') else '', channel['name'])
        header_message = await thread.send(content=header_content, silent=True)
        channel_headers.append(header_message)

        last_content = ""
        for i, message in enumerate(channel["messages"]):
            author = message['author']
            author_name = author['nick'] if author.get('nick') not in (None, '<Unknown>') else author['user']
            author_avatar = 'https://cdn.discordapp.com/avatars/{}/{}.png'.format(author['id'], author['avatar'])
            content = message['content']
            if len(content) > 2000:
                assert not last_content  # Having last_content at this point should be impossible
                first_part, content = split_big_message(content)
                msg = await hook.send(content=first_part, username=author_name, avatar_url=author_avatar, thread=thread,
                                      silent=True, allowed_mentions=discord.AllowedMentions.none(), wait=True)
                logging.warning(msg.jump_url)

            embeds = [discord.Embed.from_dict(i) for i in message["embeds"]]

            files = []
            total_size = 0
            # TODO: If all the files are below 10 MB and just the sum of them is above, then we can just upload them in the following messages.
            for j, attachment in enumerate(message['attachments']):
                file_path = str(attachment_dir / "{}{}_{}".format(message['id'], j, attachment["filename"].replace('/','')))
                try:
                    f = open(file_path, 'rb')
                    f.seek(0, 2)
                    file_size = f.tell()
                    if file_size + total_size > FILE_LIMIT:
                        embed = discord.Embed(
                            title="Attachment Skipped: File Too Large",
                            description=f"**Filename:** {attachment['filename']}\n"
                                        f"**Path:** `{file_path}`\n"
                                        f"**Size:** {file_size / (1024 * 1024):.2f} MB",
                            color=0xff0000
                        )
                        embeds.append(embed)
                        logging.warning("Too big:", file_path)
                        f.close()
                        continue
                    f.seek(0)
                    files.append(discord.File(f, filename=attachment["filename"]))
                    total_size += file_size
                except OSError as e:
                    embed = discord.Embed(
                        title="Attachment Skipped: Missing File",
                        description=f"**Filename:** {attachment['filename']}\n",
                        color=0xff0000
                    )
                    embeds.append(embed)
                    logging.warning("oserror:", e)

            if content and not embeds and not files and 'thread' not in message and i + 1 < len(channel["messages"]) and \
                    channel["messages"][i + 1]['author']['id'] == author['id'] and len(content) + len(
                    last_content) + len(channel["messages"][i + 1]['content']) < 2000:
                # This is a simple message (no attachments or embeds), so we can prepend it to the next message
                last_content += content + "\n"
            elif content or embeds or files:
                msg = await hook.send(content=last_content + content, username=author_name, avatar_url=author_avatar,
                                      files=files, embeds=embeds, thread=thread, silent=True,
                                      allowed_mentions=discord.AllowedMentions.none(), wait=True)
                last_content = ""
                if 'thread' in message and len(content) < 2000 - 90:
                    thread_starters[message['thread']] = msg
            elif message == channel["messages"][0] and channel.get('thread_parent'):
                other = thread_starters.get(channel.get('id'))
                if not other:
                    continue
                # Link thread starter and the thread
                msg = await hook.send(content=other.content + '\n' + other.jump_url, username=author_name,
                                      avatar_url=author_avatar, thread=thread, silent=True,
                                      allowed_mentions=discord.AllowedMentions.none(), wait=True)
                await other.edit(content=other.content + '\n' + msg.jump_url)
        await thread.send(content='.\n' * 50, silent=True)
    try:
        for hdr in channel_headers:
            await hdr.pin()
    except Exception:
        # Limit of 50 pins reached
        pass
    link_message = ""
    for channel, hdr in zip(ctf_export["channels"], channel_headers):
        s = "**{}{}:** {}\n".format('Thread: ' if channel.get('thread_parent') else '', channel['name'], hdr.jump_url)
        if len(link_message) + len(s) > 2000:
            await thread.send(content=link_message.rstrip(), silent=True)
            link_message = ""
        link_message += s
    if link_message:
        await thread.send(content=link_message.rstrip(), silent=True)


# Allow running this file standalone
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Export a CTF')
    parser.add_argument('--channels', type=Path, help='Path to file containing newline-separated channel names or IDs to export')
    parser.add_argument('--json', type=Path, help='JSON file to re-export directly')
    parser.add_argument('--export', type=int, required=True, help='ID of channel to export messages to')
    parser.add_argument('--dir', type=Path, default=Path('backups'), help='Path to backups directory')
    parser.add_argument('--token', type=str, help='Bot token. If not provided, it is expected in BOT_TOKEN env or in stdin')

    args = parser.parse_args()

    if True ^ (args.channels is None) ^ (args.json is None):
        raise Exception("Only one of --channels or --json can be provided")

    bot_token = args.token or os.environ.get("BOT_TOKEN") or input("Bot token: ")

    logging.basicConfig(level=logging.INFO)
    intents = discord.Intents.all()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logging.info(f"{client.user.name} Online")

        export_channel = client.get_channel(args.export)
        guild = export_channel.guild

        if args.json:
            ctf_export = json.load(open(args.json, 'r'))
            attachment_dir = Path(str(args.json).replace(".json",""))
        else:
            channels: list[discord.TextChannel] = []
            for line in open(args.channels, 'r').readlines():
                line = line.strip()
                if line.isdigit():
                    if channel := guild.get_channel(int(line)):
                        channels.append(channel)
                    else:
                        logging.warning(f"Skipping {line}")
                if channel := discord.utils.get(guild.channels, name=line):
                    channels.append(channel)
                else:
                    logging.warning(f"Skipping {line}")

            assert all(isinstance(channel, discord.TextChannel) for channel in channels)
            assert len(set(channels)) == len(channels)

            attachment_dir = Path(args.dir) / str(guild.id) / f"{channels[0].id}_{channels[0].name}"
            try:
                attachment_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logging.warning(f"Failed to create directory {attachment_dir}")

            ctf_export = await export_channels(channels, attachment_dir)

            filepath = attachment_dir.parent / f"{channels[0].id}_{channels[0].name}.json"

            try:
                with open(filepath, 'w') as f:
                    f.write(json.dumps(ctf_export, separators=(",", ":")))
            except FileNotFoundError:
                logging.warning(f"Failed to create JSON export file")

        await reexport_ctf(export_channel, ctf_export, attachment_dir)
        logging.info("Export done!")
        await client.close()

    async def main():
        async with client:
            await client.start(bot_token)

    asyncio.run(main())
