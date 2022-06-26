import re
from urllib.parse import quote_plus

import discord
import aiohttp
from discord import app_commands
from typing import Optional
from bs4 import BeautifulSoup
import datetime
from tabulate import tabulate

from config import config


class Ctftime(app_commands.Group):

    @staticmethod
    async def get_ctf_info(event_id):
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://ctftime.org/api/v1/events/{event_id}/') as response:
                if response.status != 200:
                    return None
                data = await response.json()
                return {
                    'title': data['title'],
                    'url': data['url'],
                    'start': int(datetime.datetime.strptime(data["start"], "%Y-%m-%dT%H:%M:%S%z").timestamp()),
                    'end': int(datetime.datetime.strptime(data["finish"], "%Y-%m-%dT%H:%M:%S%z").timestamp()),
                }

    @staticmethod
    def get_table_from_html(soup):
        tbl = soup.find('table')
        rows = iter(tbl.find_all('tr'))
        headers = [h.text for h in next(rows).find_all('th')]

        d = []
        for row in rows:
            out_row = []
            for column in row.find_all('td'):
                img = column.find('img')
                if img is not None:
                    out_row.append(img.get('alt'))
                elif column.text or (column.get('class') and 'country' in column.get('class')):
                    out_row.append(column.text.strip())
            d.append(out_row)

        return headers, d

    @staticmethod
    def check_year(year):
        current_year = datetime.datetime.now().year
        if 0 <= year < 100:
            return year + current_year - current_year % 100
        if year < 2011 or year > current_year:
            return None
        return year

    @app_commands.command(description="Display top teams for a specified year and/or country")
    async def top(self, interaction: discord.Interaction, country: str = "", year: int = datetime.datetime.now().year):
        year = self.check_year(year)
        if year is None:
            await interaction.response.send_message("Invalid year")
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://ctftime.org/stats/{year}/{country.upper()}') as response:
                if response.status != 200:
                    await interaction.response.send_message("Unknown country")
                    return

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                if country:
                    country_name = soup.find(class_='flag').parent.text.strip()

                headers, tbl = self.get_table_from_html(soup)

        if country:
            out = f"**Showing top teams for {country_name}** :flag_{country.lower()}:"
        else:
            out = f"**Showing top teams**"

        if year != datetime.datetime.now().year:
            out += f' **({year})**'

        out += '\n```\n'
        out += tabulate(tbl, headers=headers, floatfmt='.03f')

        while len(out) > 2000-4:
            out = out[:out.rfind('\n')]

        out += '\n```'
        await interaction.response.send_message(out)

    @app_commands.command(description="Show top 10 events for a team")
    async def team(self, interaction: discord.Interaction, team: Optional[str], year: int = datetime.datetime.now().year):
        # TODO: Get current team when available
        year = self.check_year(year)
        if year is None:
            await interaction.response.send_message("Invalid year")
            return

        if team is None:
            if config.ctftime_team is None:
                await interaction.response.send_message("Please specify team")
                return
            else:
                team = config.ctftime_team

        await interaction.response.defer()

        if team.isnumeric():
            url = f'https://ctftime.org/team/{int(team)}'
        else:
            url = f'https://ctftime.org/team/list/?q={quote_plus(team)}'

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    await interaction.edit_original_message(content="Unknown team")
                    return

                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                team_name = soup.find(class_='page-header').text.strip()

                year_rating = soup.find(id=f'rating_{year}')
                if year_rating is None:
                    await interaction.edit_original_message(content="Invalid year")
                    return
                headers, tbl = self.get_table_from_html(year_rating)

                tbl = sorted(tbl, key=lambda row: -float(row[3]))[:10]
                s = sum(float(row[3]) for row in tbl)

        tbl_str = tabulate(tbl, headers=headers, floatfmt='.03f')

        out = f"**Showing top {len(tbl)} events for {team_name}**"
        out += '\n```\n'
        out += tbl_str
        out += '\n\nTotal' + '{:.03f}'.format(s).rjust(tbl_str.index('\n')-5, ' ')
        out += '\n```\n'

        if len(out) > 2000:
            await interaction.edit_original_message(content='Message is too long...')
            return
        await interaction.edit_original_message(content=out)

    @staticmethod
    async def get_team_id(team_name):
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://ctftime.org/team/list/?q={team_name}') as response:
                if response.status == 200:
                    l = re.findall(r'^https://ctftime.org/team/([0-9]+)$', str(response.url))
                    if l:
                        return int(l[0])
                    else:
                        return None
                else:
                    return None


def add_commands(tree: app_commands.CommandTree):
    tree.add_command(Ctftime(), guild=discord.Object(id=config.guild_id))
