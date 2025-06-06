import discord
import aiohttp

from urllib.parse import quote_plus
from dateutil import parser as dateutil_parser
from discord import app_commands
from bs4 import BeautifulSoup, element
from datetime import datetime
from tabulate import tabulate

from psybot.utils import get_settings
from psybot.config import config


class Ctftime(app_commands.Group):

    @staticmethod
    async def get_ctf_info(event_id: int) -> dict:
        event_url = f'{config.ctftime_url}/api/v1/events/{event_id}/'
        async with aiohttp.ClientSession() as session, session.get(event_url) as response:
            if response.status != 200:
                return None
            data = await response.json()
            return {
                'title': data['title'],
                'url': data['url'],
                'start': int(dateutil_parser.parse(data["start"]).timestamp()),
                'end': int(dateutil_parser.parse(data["finish"]).timestamp()),
            }

    @staticmethod
    def get_table_from_html(tbl: element.Tag, raw: bool = False) -> tuple[list[str], list]:
        rows = iter(tbl.find_all('tr'))
        headers = [h.text for h in next(rows).find_all('th')]

        d = []
        for row in rows:
            out_row = []
            for column in row.find_all('td'):
                if raw:
                    out_row.append(next(column.children))
                    continue
                img = column.find('img')
                if img is not None:
                    out_row.append(img.get('alt'))
                elif column.text or (column.get('class') and 'country' in column.get('class')):
                    out_row.append(column.text.strip())
            d.append(out_row)

        return headers, d

    @staticmethod
    def check_year(year: int | None) -> int:
        current_year = datetime.now().year
        if year is None:
            return current_year
        if 0 <= year < 100:
            return year + current_year - current_year % 100
        if year < 2011 or year > current_year:
            raise app_commands.AppCommandError("Invalid year")
        return year

    @staticmethod
    def get_team_url(interaction, team) -> str | None:
        if team is None:
            if interaction.guild is None:
                return None

            settings = get_settings(interaction.guild)
            if not settings.ctftime_team:
                return None
            team = settings.ctftime_team

        if team.isnumeric():
            return f'{config.ctftime_url}/team/{int(team)}'
        return f'{config.ctftime_url}/team/list/?q={quote_plus(team)}'

    @staticmethod
    async def get_team_top10(team_url, year) -> tuple[str, list, float]:
        async with aiohttp.ClientSession() as session, session.get(team_url) as response:
            if response.status != 200:
                raise app_commands.AppCommandError("Unknown team")

            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            team_name = soup.find(class_='page-header').text.strip()

            year_rating = soup.find(id=f'rating_{year}')
            if year_rating is None:
                raise app_commands.AppCommandError("Invalid year")
            _, tbl = Ctftime.get_table_from_html(year_rating.find('table'))

            h3_tag = soup.find('h3', text='Organized CTF events')
            organized_tag = h3_tag.find_next_sibling('table') if h3_tag else None

            if organized_tag:
                _, organized_tbl = Ctftime.get_table_from_html(organized_tag, raw=True)
                for name, weight in organized_tbl:
                    event_id = name['href'].split("/")[-1]

                    async with session.get(f'{config.ctftime_url}/api/v1/events/{event_id}/') as response:
                        if response.status != 200:
                            break
                        resp = await response.json()
                        if int(resp['finish'][:4]) != year:
                            break
                    tbl.append(['-', name.text, '-', str(float(weight.text)*2)])
            tbl = sorted(tbl, key=lambda row: -float(row[3].replace('*','')))[:10]
            s = sum(float(row[3].replace('*','')) for row in tbl)
            return team_name, tbl, s

    @app_commands.command(description="Display top teams for a specified year and/or country")
    async def top(self, interaction: discord.Interaction, country: str | None, year: int | None):
        year = self.check_year(year)

        if country and (len(country) != 2 or not country.isalpha()):
            raise app_commands.AppCommandError("Invalid country. Use the alpha-2 country code")

        stats_url = f"{config.ctftime_url}/stats/{year}/"
        if country is not None:
            stats_url += country.upper()

        async with aiohttp.ClientSession() as session, session.get(stats_url) as response:
            if response.status != 200:
                raise app_commands.AppCommandError("Unknown country")

            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')

            if country:
                country_name = soup.find(class_='flag').parent.text.strip()

            headers, tbl = self.get_table_from_html(soup.find('table'))

        if country is None:
            out = "**Showing top teams globally**"
        else:
            out = f"**Showing top teams for {country_name}** :flag_{country.lower()}:"

        if year != datetime.now().year:
            out += f' **({year})**'

        out += '\n```\n'
        out += tabulate(tbl, headers=headers, floatfmt='.03f')

        while len(out) > 2000-4:
            out = out[:out.rfind('\n')]

        out += '\n```'
        await interaction.response.send_message(out)

    @app_commands.command(description="Show top 10 events for a team")
    async def team(self, interaction: discord.Interaction, team: str | None, year: int | None):
        year = self.check_year(year)

        url = self.get_team_url(interaction, team)
        if url is None:
            raise app_commands.AppCommandError("Please specify team")

        await interaction.response.defer()

        team_name, tbl, s = await self.get_team_top10(url, year)

        tbl_str = tabulate(tbl, headers=['Place', 'Event', 'CTF points', 'Rating points'], floatfmt='.03f')

        out = f"**Showing top {len(tbl)} events for {team_name}**"
        out += '\n```\n'
        out += tbl_str
        out += '\n\nTotal' + '{:.03f}'.format(s).rjust(tbl_str.index('\n')-5, ' ')
        out += '\n```\n'

        if len(out) > 2000:
            await interaction.edit_original_response(content='Message is too long...')
            return
        await interaction.edit_original_response(content=out)

    @app_commands.command(description="Calculate new CTFTime score from ctf")
    async def calc(self, interaction: discord.Interaction, weight: float, best_points: float, team_points: float, team_place: int, team: str | None):
        new_score = (team_points/best_points + 1/team_place) * weight

        await interaction.response.send_message(f"Rating points: {new_score:.03f}")

        url = self.get_team_url(interaction, team)
        if url is None:
            return

        try:
            team_name, tbl, old_rating = await self.get_team_top10(url, datetime.now().year)
        except Exception as e:
            print(e)
            return

        old_score = float(tbl[-1][3])
        new_rating = old_rating + max(new_score-old_score, 0)
        score_diff = new_rating-old_rating

        await interaction.edit_original_response(content=f'Rating points: {new_score:.03f}\nNew Rating for {team_name}: {new_rating:.03f} (+{score_diff:.03f})')


def add_commands(tree: app_commands.CommandTree, guild: discord.Object | None):
    tree.add_command(Ctftime(), guild=guild)
