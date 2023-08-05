import asyncio
import json
import pickle
import random
import socket
import subprocess
import sys
import threading
import traceback
from os import path, listdir, makedirs
from typing import Literal, Union
import ast

import discord
import spotipy
import youtubesearchpython
import yt_dlp
from discord import app_commands
from discord.ext import commands
from discord.ui import View
from sclib import SoundcloudAPI, Track, Playlist
from spotipy.oauth2 import SpotifyClientCredentials

from classes.discord_classes import DiscordChannel, DiscordMember, DiscordRole,  DiscordUser, DiscordInvite
from classes.data_classes import ReturnData, WebData, Guild, GuildData
from classes.video_class import VideoClass

from utils.cli import execute, get_url_probe_data
from utils.convert import convert_duration, to_bool
from utils.translate import tg
from utils.discord import get_voice_client, create_embed, now_to_history, to_queue, get_content_of_message, get_username
from utils.json import guilds_to_json, json_to_guilds
from utils.log import log, send_to_admin
from utils.save import save_json, push_update, update_guilds
from utils.saves import new_queue_save, load_queue_save, delete_queue_save, rename_queue_save
from utils.spotify import spotify_to_yt_video, spotify_playlist_to_yt_video_list, spotify_album_to_yt_video_list
from utils.url import extract_yt_id, get_playlist_from_url, get_url_type
from utils.video_time import set_stopped, set_started, set_resumed, set_new_time
from utils.checks import is_float

from ipc.main import send_msg, recv_msg
from vars import *
import config

# ---------------- Bot class ------------

class Bot(commands.Bot):
    """
    Bot class

    This class is used to create the bot instance.
    """

    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=prefix, intents=intents)
        self.synced = False

    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            log(None, "Trying to sync commands")
            await self.tree.sync()
            log(None, f"Synced slash commands for {self.user}")
        await bot.change_presence(activity=discord.Game(name=f"/help"))
        log(None, f'Logged in as:\n{bot.user.name}\n{bot.user.id}')

        save_json()

    async def on_guild_join(self, guild_object):
        # log
        log_msg = f"Joined guild ({guild_object.name})({guild_object.id}) with {guild_object.member_count} members and {len(guild_object.voice_channels)} voice channels"
        log(None, log_msg)

        # send log to admin
        await send_to_admin(log_msg)

        # create guild object
        guild[guild_object.id] = Guild(guild_object.id)
        save_json()

        # get text channels
        text_channels = guild_object.text_channels
        sys_channel = guild_object.system_channel

        # send welcome message in system channel or first text channel
        message = f"Hello **`{guild_object.name}`**! I am `{self.user.display_name}`. Thank you for inviting me.\n\nTo see what commands I have available type `/help`\n\nIf you have any questions, you can DM my developer <@!{my_id}>#4272"
        if sys_channel is not None:
            if sys_channel.permissions_for(guild_object.me).send_messages:
                await sys_channel.send(message)
        else:
            await text_channels[0].send(message)

        # download all channels
        await download_guild(WebData(guild_object.id, bot.user.name, bot.user.id), guild_object.id, mute_response=True, ephemeral=True)

    @staticmethod
    async def on_guild_remove(guild_object):
        # log
        log_msg = f"Left guild ({guild_object.name})({guild_object.id}) with {guild_object.member_count} members and {len(guild_object.voice_channels)} voice channels"
        log(None, log_msg)

        # send log to admin
        await send_to_admin(log_msg)

        # update guilds
        save_json()

    async def on_voice_state_update(self, member, before, after):
        # set voice state
        voice_state = member.guild.voice_client

        # set guild_id
        guild_id = member.guild.id

        # check if bot is alone in voice channel
        if voice_state is not None and len(voice_state.channel.members) == 1:
            # stop playing and disconnect
            voice_state.stop()
            await voice_state.disconnect()

            # set stopped to true
            guild[guild_id].options.stopped = True

            # log
            log(guild_id, "-->> Disconnecting when last person left -> Queue Cleared <<--")

            # save history
            now_to_history(guild_id)

            # clear queue when last person leaves
            guild[guild_id].queue.clear()

        if not member.id == self.user.id:
            return


        # if bot joins a voice channel
        elif before.channel is None:
            # get voice client
            voice = after.channel.guild.voice_client

            # initialize loop
            time_var = 0
            while True:
                # check every second
                await asyncio.sleep(1)

                # increase time_var
                time_var += 1

                # check if bot is playing and not paused
                if voice.is_playing() and not voice.is_paused():
                    time_var = 0 # reset time_var

                # check if time_var is greater than buffer
                if time_var >= guild[guild_id].options.buffer:
                    # stop playing and disconnect
                    voice.stop()
                    await voice.disconnect()

                    # set stopped to true
                    guild[guild_id].options.stopped = True

                    # log
                    log(guild_id, f"-->> Disconnecting after {guild[guild_id].options.buffer} seconds of no play <<--")

                    # save history
                    now_to_history(guild_id)

                # check if bot is disconnected
                if not voice.is_connected():
                    break # break loop

        # if bot leaves a voice channel
        elif after.channel is None:
            # clear queue when bot leaves
            guild[guild_id].queue.clear()
            # log
            log(guild_id, f"-->> Cleared Queue after bot Disconnected <<--")

    async def on_command_error(self, ctx, error):
        # get error traceback
        error_traceback = traceback.format_exception(type(error), error, error.__traceback__)
        error_traceback = ''.join(error_traceback)

        if isinstance(error, discord.errors.Forbidden):
            log(ctx, 'error.Forbidden', [error], log_type='error', author=ctx.author)
            await ctx.send(tg(ctx.guild.id, "The command failed because I don't have the required permissions.\n Please give me the required permissions and try again."))

        elif isinstance(error, commands.CheckFailure):
            err_msg = f'Error for ({ctx.author}) -> ({ctx.command}) with error ({error})'
            log(ctx, err_msg, log_type='error', author=ctx.author)
            await send_to_admin(err_msg)
            await ctx.reply(f"（ ͡° ͜ʖ ͡°)つ━☆・。\n"
                            f"⊂　　 ノ 　　　・゜+.\n"
                            f"　しーＪ　　　°。+ ´¨)\n"
                            f"　　　　　　　　　.· ´¸.·´¨) ¸.·*¨)\n"
                            f"　　　　　　　　　　(¸.·´ (¸.·' ☆ **Fuck off**\n"
                            f"*{tg(ctx.guild.id, 'You dont have permission to use this command')}*")

        else:
            message = f"Error for ({ctx.author}) -> ({ctx.command}) with error ({error})\n{error_traceback}"

            # log
            log(ctx, message, log_type='error', author=ctx.author)

            # send log to admin
            await send_to_admin(message)

            # send to user
            await ctx.reply(f"{error}   {bot.get_user(my_id).mention}", ephemeral=True)

    async def on_message(self, message):
        # on every message
        if message.author == bot.user:
            return

        # check if message is a DM
        if not message.guild:
            try:
                # respond to DM
                await message.channel.send(
                    f"I'm sorry, but I only work in servers.\n\n"
                    f""
                    f"If you want me to join your server, you can invite me with this link: {config.INVITE_URL}\n\n"
                    f""
                    f"If you have any questions, you can DM my developer <@!{my_id}>#4272")

                # send DM to ADMIN
                await send_to_admin(f"<@!{message.author.id}> tied to DM me with this message `{message.content}`")

            except discord.errors.Forbidden:
                pass

# ----------- SOUND EFFECTS ---------------------

def load_sound_effects():
    """
    Loads all sound effects from the sound_effects folder
    to the global variable all_sound_effects
    """
    global all_sound_effects
    all_sound_effects = ["No sound effects found"]
    try:
        all_sound_effects = listdir('sound_effects')
        for file_index, file_val in enumerate(all_sound_effects):
            all_sound_effects[file_index] = all_sound_effects[file_index][:len(file_val) - 4]
    except FileNotFoundError:
        all_sound_effects = ["No sound effects found"]
    log(None, 'Loaded sound_effects folder')
all_sound_effects = ["No sound effects found"]
load_sound_effects()

# ---------------------------------------------- LOAD ------------------------------------------------------------------

log(None, "--------------------------------------- NEW / REBOOTED ----------------------------------------")

build_new_guilds = False

with open('db/radio.json', 'r', encoding='utf-8') as file:
    radio_dict = json.load(file)
log(None, 'Loaded radio.json')

with open('db/languages.json', 'r', encoding='utf-8') as file:
    languages_dict = json.load(file)
    text = languages_dict['en']
    authorized_users += [my_id, 349164237605568513]
log(None, 'Loaded languages.json')

# ---------------------------------------------- BOT -------------------------------------------------------------------

bot = Bot()

log(None, 'Discord API initialized')

# ---------------------------------------------- SPOTIPY ---------------------------------------------------------------

credentials = SpotifyClientCredentials(client_id=config.SPOTIPY_CLIENT_ID, client_secret=config.SPOTIPY_CLIENT_SECRET)
sp = spotipy.Spotify(client_credentials_manager=credentials)

log(None, 'Spotify API initialized')

# --------------------------------------------- SOUNDCLOUD -------------------------------------------------------------

sc = SoundcloudAPI(client_id=config.SOUNDCLOUD_CLIENT_ID)

log(None, 'SoundCloud API initialized')

# ----------------------------------------------------------------------------------------------------------------------

if build_new_guilds:
    log(None, 'Building new guilds.json ...')
    with open('db/guilds.json', 'r', encoding='utf-8') as file:
        jf = json.load(file)
    guild = dict(zip(jf.keys(), [Guild(int(guild)) for guild in jf.keys()]))

    try:
        json = json.dumps(guilds_to_json(guild), indent=4)
    except Exception as ex:
        print("something failed, figure it out", file=sys.stderr)
        print(ex, file=sys.stderr)
        exit(0)
    with open('db/guilds.json', 'w', encoding='utf-8') as file:
        file.write(json)
    exit(0)

with open('db/guilds.json', 'r', encoding='utf-8') as file:
    guild = json_to_guilds(json.load(file))
log(None, 'Loaded guilds.json')

# ---------------------------------------------- SOURCE ------------------------------------------------------

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

class GetSource(discord.PCMVolumeTransformer):
    ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, guild_id: int, source: discord.FFmpegPCMAudio):
        super().__init__(source, guild[guild_id].options.volume)

    @classmethod
    async def create_source(cls, guild_id: int, url: str, source_type: str = 'Video', time_stamp: int=None, video_class: VideoClass=None):
        """
        Get source from url

        When the source type is 'Video', the url is a youtube video url
        When the source type is 'SoundCloud', the url is a soundcloud track url
        Other it tries to get the source from the url

        :param guild_id: int
        :param url: str
        :param video_class: VideoClass
        :param source_type: str ('Video', 'SoundCloud') - default: 'Video' > anything else for direct url
        :param time_stamp: int - time stamp in seconds

        :return source: discord.FFmpegPCMAudio
        """
        SOURCE_FFMPEG_OPTIONS = {
            'before_options': f'{f"-ss {time_stamp} " if time_stamp else ""}-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn'
        }
        chapters = None

        if source_type == 'Video':
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: cls.ytdl.extract_info(url, download=False))

            if 'chapters' in data:
                chapters = data['chapters']

            if 'entries' in data:
                data = data['entries'][0]

            url = data['url']

        if source_type == 'SoundCloud':
            track = sc.resolve(url)
            url = track.get_stream_url()

        if source_type == 'Local':
            SOURCE_FFMPEG_OPTIONS = {
                'before_options': f'{f"-ss {time_stamp} " if time_stamp else ""}',
                'options': '-vn'
            }

        if video_class:
            video_class.stream_url = url

        return cls(guild_id, discord.FFmpegPCMAudio(url, **SOURCE_FFMPEG_OPTIONS)), chapters

# ------------------------------------ View Classes --------------------------------------------------------------------

class PlayerControlView(View):
    def __init__(self, ctx):
        super().__init__(timeout=7200)
        if type(ctx) == commands.Context:
            self.guild = ctx.guild
            self.guild_id = ctx.guild.id

    @discord.ui.button(emoji=react_dict['play'], style=discord.ButtonStyle.blurple, custom_id='play')
    async def callback(self, interaction, button):
        voice: discord.voice_client.VoiceClient = get_voice_client(bot.voice_clients, guild=self.guild)
        if voice:
            if voice.is_paused():
                voice.resume()
                # noinspection PyUnresolvedReferences
                pause_button = [x for x in self.children if x.custom_id == 'pause'][0]
                pause_button.style = discord.ButtonStyle.blurple
                button.style = discord.ButtonStyle.grey
                await interaction.response.edit_message(view=self)
            elif voice.is_playing():
                await interaction.response.send_message(tg(self.guild_id, "Player **already resumed!**"),
                                                        ephemeral=True)
            else:
                await interaction.response.send_message(tg(self.guild_id, "No audio playing"), ephemeral=True)
        else:
            await interaction.response.send_message(tg(self.guild_id, "No audio"), ephemeral=True)

    @discord.ui.button(emoji=react_dict['pause'], style=discord.ButtonStyle.blurple, custom_id='pause')
    async def pause_callback(self, interaction, button):
        voice: discord.voice_client.VoiceClient = get_voice_client(bot.voice_clients, guild=self.guild)
        if voice:
            if voice.is_playing():
                voice.pause()
                # noinspection PyUnresolvedReferences
                play_button = [x for x in self.children if x.custom_id == 'play'][0]
                play_button.style = discord.ButtonStyle.blurple
                button.style = discord.ButtonStyle.grey
                await interaction.response.edit_message(view=self)
            elif voice.is_paused():
                await interaction.response.send_message(tg(self.guild_id, "Player **already paused!**"),
                                                        ephemeral=True)
            else:
                await interaction.response.send_message(tg(self.guild_id, "No audio playing"), ephemeral=True)
        else:
            await interaction.response.send_message(tg(self.guild_id, "No audio"), ephemeral=True)

    # noinspection PyUnusedLocal
    @discord.ui.button(emoji=react_dict['stop'], style=discord.ButtonStyle.red, custom_id='stop')
    async def stop_callback(self, interaction, button):
        voice: discord.voice_client.VoiceClient = get_voice_client(bot.voice_clients, guild=self.guild)
        if voice:
            if voice.is_playing() or voice.is_paused():
                voice.stop()
                guild[interaction.guild_id].options.stopped = True
                await interaction.response.edit_message(view=None)
            else:
                await interaction.response.send_message(tg(self.guild_id, "No audio playing"), ephemeral=True)
        else:
            await interaction.response.send_message(tg(self.guild_id, "No audio"), ephemeral=True)

class SearchOptionView(View):

    def __init__(self, ctx, force=False, from_play=False):
        super().__init__(timeout=180)

        if type(ctx) == commands.Context:
            self.ctx = ctx
            self.guild = ctx.guild
            self.guild_id = ctx.guild.id
            self.force = force
            self.from_play = from_play

    # noinspection PyUnusedLocal
    @discord.ui.button(emoji=react_dict['1'], style=discord.ButtonStyle.blurple, custom_id='1')
    async def callback_1(self, interaction, button):
        video = guild[self.guild_id].search_list[0]
        if self.force:
            to_queue(self.guild_id, video, position=0)
        else:
            to_queue(self.guild_id, video)
        save_json()
        await interaction.response.edit_message(content=f'[`{video.title}`](<{video.url}>) '
                                                        f'{tg(self.guild_id, "added to queue!")}', view=None)
        if self.from_play:
            await play_def(self.ctx)

    # noinspection PyUnusedLocal
    @discord.ui.button(emoji=react_dict['2'], style=discord.ButtonStyle.blurple, custom_id='2')
    async def callback_2(self, interaction, button):
        video = guild[self.guild_id].search_list[1]
        if self.force:
            to_queue(self.guild_id, video, position=0)
        else:
            to_queue(self.guild_id, video)
        save_json()
        await interaction.response.edit_message(content=f'[`{video.title}`](<{video.url}>) '
                                                        f'{tg(self.guild_id, "added to queue!")}', view=None)
        if self.from_play:
            await play_def(self.ctx)

    # noinspection PyUnusedLocal
    @discord.ui.button(emoji=react_dict['3'], style=discord.ButtonStyle.blurple, custom_id='3')
    async def callback_3(self, interaction, button):
        video = guild[self.guild_id].search_list[2]
        if self.force:
            to_queue(self.guild_id, video, position=0)
        else:
            to_queue(self.guild_id, video)
        save_json()
        await interaction.response.edit_message(content=f'[`{video.title}`](<{video.url}>) '
                                                        f'{tg(self.guild_id, "added to queue!")}', view=None)
        if self.from_play:
            await play_def(self.ctx)

    # noinspection PyUnusedLocal
    @discord.ui.button(emoji=react_dict['4'], style=discord.ButtonStyle.blurple, custom_id='4')
    async def callback_4(self, interaction, button):
        video = guild[self.guild_id].search_list[3]
        if self.force:
            to_queue(self.guild_id, video, position=0)
        else:
            to_queue(self.guild_id, video)
        save_json()
        await interaction.response.edit_message(content=f'[`{video.title}`](<{video.url}>) '
                                                        f'{tg(self.guild_id, "added to queue!")}', view=None)
        if self.from_play:
            await play_def(self.ctx)

    # noinspection PyUnusedLocal
    @discord.ui.button(emoji=react_dict['5'], style=discord.ButtonStyle.blurple, custom_id='5')
    async def callback_5(self, interaction, button):
        video = guild[self.guild_id].search_list[4]
        if self.force:
            to_queue(self.guild_id, video, position=0)
        else:
            to_queue(self.guild_id, video)
        save_json()
        await interaction.response.edit_message(content=f'[`{video.title}`](<{video.url}>) '
                                                        f'{tg(self.guild_id, "added to queue!")}', view=None)
        if self.from_play:
            await play_def(self.ctx)

class PlaylistOptionView(View):
    def __init__(self, ctx, url, force=False, from_play=False):
        super().__init__(timeout=180)

        if type(ctx) == commands.Context:
            self.ctx = ctx
            self.url = url
            self.guild = ctx.guild
            self.guild_id = ctx.guild.id
            self.force = force
            self.from_play = from_play

    # noinspection PyUnusedLocal
    @discord.ui.button(label='Yes', style=discord.ButtonStyle.blurple)
    async def callback_1(self, interaction, button):
        playlist_url = get_playlist_from_url(self.url)
        await interaction.response.edit_message(content=tg(self.guild_id, "Adding playlist to queue..."), view=None)

        position = 0 if self.force else None
        response: ReturnData = await queue_command_def(self.ctx, playlist_url, position=position, mute_response=True,
                                                       force=self.force)

        # await interaction.response.edit_message(content=response.message, view=None)
        await interaction.followup.edit_message(content=response.message, view=None, message_id=interaction.message.id)

        if self.from_play:
            await play_def(self.ctx)

    # noinspection PyUnusedLocal
    @discord.ui.button(label='No', style=discord.ButtonStyle.blurple)
    async def callback_2(self, interaction, button):
        pure_url = self.url[:self.url.index('&list=')]

        position = 0 if self.force else None
        response: ReturnData = await queue_command_def(self.ctx, pure_url, position=position, mute_response=True,
                                                       force=self.force)

        await interaction.response.edit_message(content=response.message, view=None)

        if self.from_play:
            await play_def(self.ctx)

# --------------------------------------- QUEUE --------------------------------------------------

@bot.hybrid_command(name='queue', with_app_command=True, description=text['queue_add'], help=text['queue_add'])
@app_commands.describe(url=text['url'], position=text['pos'])
async def queue_command(ctx: commands.Context, url, position: int = None):
    log(ctx, 'queue', [url, position], log_type='command', author=ctx.author)

    await queue_command_def(ctx, url, position=position)

@bot.hybrid_command(name='queue_export', with_app_command=True, description=text['queue_export'], help=text['queue_export'])
@app_commands.describe(guild_id=text['guild_id'], ephemeral=text['ephemeral'])
async def export_queue_command(ctx: commands.Context, guild_id=None, ephemeral: bool=True):
    log(ctx, 'export_queue', [guild_id, ephemeral], log_type='command', author=ctx.author)

    await export_queue(ctx, guild_id, ephemeral=ephemeral)

@bot.hybrid_command(name='queue_import', with_app_command=True, description=text['queue_import'], help=text['queue_import'])
@app_commands.describe(queue_string=text['queue_string'], guild_id=text['guild_id'], ephemeral=text['ephemeral'])
async def import_queue_command(ctx: commands.Context, queue_string: str, guild_id=None, ephemeral: bool=True):
    log(ctx, 'import_queue', [queue_string, guild_id, ephemeral], log_type='command', author=ctx.author)

    await import_queue(ctx, queue_string, guild_id, ephemeral=ephemeral)

@bot.hybrid_command(name='next_up', with_app_command=True, description=text['next_up'], help=text['next_up'])
@app_commands.describe(url=text['url'], user_only=text['ephemeral'])
async def next_up(ctx: commands.Context, url, user_only: bool = False):
    log(ctx, 'next_up', [url, user_only], log_type='command', author=ctx.author)

    await next_up_def(ctx, url, user_only)

@bot.hybrid_command(name='skip', with_app_command=True, description=text['skip'], help=text['skip'])
async def skip(ctx: commands.Context):
    log(ctx, 'skip', [], log_type='command', author=ctx.author)

    await skip_def(ctx)

@bot.hybrid_command(name='remove', with_app_command=True, description=text['queue_remove'], help=text['queue_remove'])
@app_commands.describe(number=text['number'], user_only=text['ephemeral'])
async def remove(ctx: commands.Context, number: int, user_only: bool = False):
    log(ctx, 'remove', [number, user_only], log_type='command', author=ctx.author)

    await remove_def(ctx, number, ephemeral=user_only)

@bot.hybrid_command(name='clear', with_app_command=True, description=text['clear'], help=text['clear'])
@app_commands.describe(user_only=text['ephemeral'])
async def clear(ctx: commands.Context, user_only: bool = False):
    log(ctx, 'clear', [user_only], log_type='command', author=ctx.author)

    await clear_def(ctx, user_only)

@bot.hybrid_command(name='shuffle', with_app_command=True, description=text['shuffle'], help=text['shuffle'])
@app_commands.describe(user_only=text['ephemeral'])
async def shuffle(ctx: commands.Context, user_only: bool = False):
    log(ctx, 'shuffle', [user_only], log_type='command', author=ctx.author)

    await shuffle_def(ctx, user_only)

@bot.hybrid_command(name='show', with_app_command=True, description=text['queue_show'], help=text['queue_show'])
@app_commands.describe(display_type=text['display_type'], user_only=text['ephemeral'])
async def show(ctx: commands.Context, display_type: Literal['short', 'medium', 'long'] = None,
               list_type: Literal['queue', 'history'] = 'queue', user_only: bool = False):
    log(ctx, 'show', [display_type, user_only], log_type='command', author=ctx.author)

    await show_def(ctx, display_type, list_type, user_only)

@bot.hybrid_command(name='search', with_app_command=True, description=text['search'], help=text['search'])
@app_commands.describe(search_query=text['search_query'])
async def search_command(ctx: commands.Context, search_query):
    log(ctx, 'search', [search_query], log_type='command', author=ctx.author)

    await search_command_def(ctx, search_query)

# --------------------------------------- PLAYER --------------------------------------------------

@bot.hybrid_command(name='play', with_app_command=True, description=text['play'], help=text['play'])
@app_commands.describe(url=text['play'], force=text['force'])
async def play(ctx: commands.Context, url=None, force=False):
    log(ctx, 'play', [url, force], log_type='command', author=ctx.author)

    await play_def(ctx, url, force)

@bot.hybrid_command(name='radio', with_app_command=True, description=text['radio'], help=text['radio'])
@app_commands.describe(favourite_radio=text['favourite_radio'], radio_code=text['radio_code'])
async def radio(ctx: commands.Context, favourite_radio: Literal[
    'Rádio BLANÍK', 'Rádio BLANÍK CZ', 'Evropa 2', 'Fajn Radio', 'Hitrádio PopRock', 'Český rozhlas Pardubice', 'Radio Beat', 'Country Radio', 'Radio Kiss', 'Český rozhlas Vltava', 'Hitrádio Černá Hora'] = None,
                radio_code: int = None):
    log(ctx, 'radio', [favourite_radio, radio_code], log_type='command', author=ctx.author)

    await radio_def(ctx, favourite_radio, radio_code)

@bot.hybrid_command(name='ps', with_app_command=True, description=text['ps'], help=text['ps'])
@app_commands.describe(effect_number=text['effects_number'])
async def ps(ctx: commands.Context, effect_number: app_commands.Range[int, 1, len(all_sound_effects)]):
    log(ctx, 'ps', [effect_number], log_type='command', author=ctx.author)

    await ps_def(ctx, effect_number)

@bot.hybrid_command(name='nowplaying', with_app_command=True, description=text['nowplaying'], help=text['nowplaying'])
@app_commands.describe(user_only=text['ephemeral'])
async def nowplaying(ctx: commands.Context, user_only: bool = False):
    log(ctx, 'nowplaying', [user_only], log_type='command', author=ctx.author)

    await now_def(ctx, user_only)

@bot.hybrid_command(name='last', with_app_command=True, description=text['last'], help=text['last'])
@app_commands.describe(user_only=text['ephemeral'])
async def last(ctx: commands.Context, user_only: bool = False):
    log(ctx, 'last', [user_only], log_type='command', author=ctx.author)

    await last_def(ctx, user_only)

@bot.hybrid_command(name='loop', with_app_command=True, description=text['loop'], help=text['loop'])
async def loop_command(ctx: commands.Context):
    log(ctx, 'loop', [], log_type='command', author=ctx.author)

    await loop_command_def(ctx)

@bot.hybrid_command(name='loop_this', with_app_command=True, description=text['loop_this'], help=text['loop_this'])
async def loop_this(ctx: commands.Context):
    log(ctx, 'loop_this', [], log_type='command', author=ctx.author)

    await loop_command_def(ctx, clear_queue=True)

# --------------------------------------- VOICE --------------------------------------------------

@bot.hybrid_command(name='stop', with_app_command=True, description=f'Stop the player')
async def stop(ctx: commands.Context):
    log(ctx, 'stop', [], log_type='command', author=ctx.author)

    await stop_def(ctx)

@bot.hybrid_command(name='pause', with_app_command=True, description=f'Pause the player')
async def pause(ctx: commands.Context):
    log(ctx, 'pause', [], log_type='command', author=ctx.author)

    await pause_def(ctx)

@bot.hybrid_command(name='resume', with_app_command=True, description=f'Resume the player')
async def resume(ctx: commands.Context):
    log(ctx, 'resume', [], log_type='command', author=ctx.author)

    await resume_def(ctx)

@bot.hybrid_command(name='join', with_app_command=True, description=text['join'], help=text['join'])
@app_commands.describe(channel_id=text['channel_id'])
async def join(ctx: commands.Context, channel_id=None):
    log(ctx, 'join', [channel_id], log_type='command', author=ctx.author)

    await join_def(ctx, channel_id)

@bot.hybrid_command(name='disconnect', with_app_command=True, description=text['die'], help=text['die'])
async def disconnect(ctx: commands.Context):
    log(ctx, 'disconnect', [], log_type='command', author=ctx.author)

    await disconnect_def(ctx)

@bot.hybrid_command(name='volume', with_app_command=True, description=text['volume'], help=text['volume'])
@app_commands.describe(volume=text['volume'], user_only=text['ephemeral'])
async def volume_command(ctx: commands.Context, volume=None, user_only: bool = False):
    log(ctx, 'volume', [volume, user_only], log_type='command', author=ctx.author)

    await volume_command_def(ctx, volume, user_only)

# --------------------------------------- MENU --------------------------------------------------

@bot.tree.context_menu(name='Play now')
async def play_now(inter, message: discord.Message):
    ctx = await bot.get_context(inter)
    log(ctx, 'play_now', [message], log_type='command', author=ctx.author)

    if ctx.author.voice is None:
        await inter.response.send_message(content=tg(ctx.guild.id, 'You are **not connected** to a voice channel'),
                                          ephemeral=True)
        return

    url, probe_data = get_content_of_message(message)

    response: ReturnData = await queue_command_def(ctx, url, mute_response=True, probe_data=probe_data, ephemeral=True,
                                                   position=0, from_play=True)
    if response:
        if response.response:
            await play_def(ctx, force=True)
        else:
            if not inter.response.is_done():
                await inter.response.send_message(content=response.message, ephemeral=True)

@bot.tree.context_menu(name='Add to queue')
async def add_to_queue(inter, message: discord.Message):
    ctx = await bot.get_context(inter)
    log(ctx, 'add_to_queue', [message], log_type='command', author=ctx.author)

    url, probe_data = get_content_of_message(message)

    response: ReturnData = await queue_command_def(ctx, url, mute_response=True, probe_data=probe_data, ephemeral=True)
    if not inter.response.is_done():
        await inter.response.send_message(content=response.message, ephemeral=True)

@bot.tree.context_menu(name='Show Profile')
async def show_profile(inter, member: discord.Member):
    ctx = await bot.get_context(inter)
    log(ctx, 'show_profile', [member], log_type='command', author=ctx.author)

    embed = discord.Embed(title=f"{member.name}#{member.discriminator}",
                          description=f"ID: `{member.id}` | Name: `{member.display_name}` | Nickname: `{member.nick}`")
    embed.add_field(name="Created at", value=member.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=True)
    embed.add_field(name="Joined at", value=member.joined_at.strftime("%d/%m/%Y %H:%M:%S"), inline=True)

    embed.add_field(name="Roles", value=", ".join([role.mention for role in member.roles[1:]]), inline=False)

    embed.add_field(name='Top Role', value=f'{member.top_role.mention}', inline=True)

    # noinspection PyUnresolvedReferences
    embed.add_field(name='Badges', value=', '.join([badge.name for badge in member.public_flags.all()]), inline=False)

    embed.add_field(name='Avatar',
                    value=f'[Default Avatar]({member.avatar}) | [Display Avatar]({member.display_avatar})',
                    inline=False)

    embed.add_field(name='Activity', value=f'`{member.activity}`', inline=False)

    embed.add_field(name='Activities', value=f'`{member.activities}`', inline=True)
    embed.add_field(name='Status', value=f'`{member.status}`', inline=True)
    embed.add_field(name='Web Status', value=f'`{member.web_status}`', inline=True)

    embed.add_field(name='Raw Status', value=f'`{member.raw_status}`', inline=True)
    embed.add_field(name='Desktop Status', value=f'`{member.desktop_status}`', inline=True)
    embed.add_field(name='Mobile Status', value=f'`{member.mobile_status}`', inline=True)

    embed.add_field(name='Voice', value=f'`{member.voice}`', inline=False)

    embed.add_field(name='Premium Since', value=f'`{member.premium_since}`', inline=False)

    embed.add_field(name='Accent Color', value=f'`{member.accent_color}`', inline=True)
    embed.add_field(name='Color', value=f'`{member.color}`', inline=True)
    embed.add_field(name='Banner', value=f'`{member.banner}`', inline=True)

    embed.add_field(name='System', value=f'`{member.system}`', inline=True)
    embed.add_field(name='Pending', value=f'`{member.pending}`', inline=True)
    embed.add_field(name='Bot', value=f'`{member.bot}`', inline=True)

    embed.set_thumbnail(url=member.avatar)
    await inter.response.send_message(embed=embed, ephemeral=True)

# --------------------------------------- GENERAL --------------------------------------------------

@bot.hybrid_command(name='ping', with_app_command=True, description=text['ping'], help=text['ping'])
async def ping_command(ctx: commands.Context):
    log(ctx, 'ping', [], log_type='command', author=ctx.author)

    await ping_def(ctx)

# noinspection PyTypeHints
@bot.hybrid_command(name='language', with_app_command=True, description=text['language'], help=text['language'])
@app_commands.describe(country_code=text['country_code'])
async def language_command(ctx: commands.Context, country_code: Literal[tuple(languages_dict.keys())]):
    log(ctx, 'language', [country_code], log_type='command', author=ctx.author)

    await language_command_def(ctx, country_code)

@bot.hybrid_command(name='sound_effects', with_app_command=True, description=text['sound'], help=text['sound'])
@app_commands.describe(user_only=text['ephemeral'])
async def sound_effects(ctx: commands.Context, user_only: bool = True):
    log(ctx, 'sound_effects', [user_only], log_type='command', author=ctx.author)

    await sound_effects_def(ctx, user_only)

@bot.hybrid_command(name='list_radios', with_app_command=True, description=text['list_radios'], help=text['list_radios'])
@app_commands.describe(user_only=text['ephemeral'])
async def list_radios(ctx: commands.Context, user_only: bool = True):
    log(ctx, 'list_radios', [user_only], log_type='command', author=ctx.author)

    await list_radios_def(ctx, user_only)

@bot.hybrid_command(name='key', with_app_command=True, description=text['key'], help=text['key'])
async def key_command(ctx: commands.Context):
    log(ctx, 'key', [], log_type='command', author=ctx.author)

    await key_def(ctx)

# noinspection PyTypeHints
@bot.hybrid_command(name='options', with_app_command=True, description=text['options'], help=text['options'])
@app_commands.describe(volume='In percentage (200 max)',
                       buffer='In seconds (what time to wait after no music is playing to disconnect)',
                       language='Language code', response_type='short/long -> embeds/plain text',
                       buttons='Whether to show player control buttons on messages', loop='True, False',
                       history_length='Number of items in history (100 max)')
async def options_command(ctx: commands.Context, loop: bool = None,
                          language: Literal[tuple(languages_dict.keys())] = None,
                          response_type: Literal['short', 'long'] = None, buttons: bool = None, volume=None,
                          buffer: int = None, history_length: int = None):
    log(ctx, 'options', [loop, language, response_type, buttons, volume, buffer, history_length], log_type='command',
        author=ctx.author)

    await options_command_def(ctx, loop=loop, language=language, response_type=response_type, buttons=buttons,
                              volume=volume, buffer=buffer, history_length=history_length)

# ---------------------------------------- ADMIN --------------------------------------------------

async def is_authorised(ctx):
    if ctx.author.id in authorized_users or ctx.author.id == 349164237605568513:
        return True

@bot.hybrid_command(name='zz_announce', with_app_command=True)
@commands.check(is_authorised)
async def announce_command(ctx: commands.Context, message):
    log(ctx, 'announce', [message], log_type='command', author=ctx.author)

    await announce_command_def(ctx, message)

@bot.hybrid_command(name='zz_earrape', with_app_command=True)
@commands.check(is_authorised)
async def earrape_command(ctx: commands.Context):
    log(ctx, 'earrape', [], log_type='command', author=ctx.author)

    await earrape_command_def(ctx)

@bot.hybrid_command(name='zz_kys', with_app_command=True)
@commands.check(is_authorised)
async def kys(ctx: commands.Context):
    log(ctx, 'kys', [], log_type='command', author=ctx.author)

    await kys_def(ctx)

@bot.hybrid_command(name='zz_file', with_app_command=True)
@commands.check(is_authorised)
async def file_command(ctx: commands.Context, config_file: discord.Attachment = None, config_type: Literal[
    'guilds', 'other', 'radio', 'languages', 'log', 'data', 'activity', 'apache_activity', 'apache_error'] = 'guilds'):
    log(ctx, 'zz_file', [config_file, config_type], log_type='command', author=ctx.author)

    await file_command_def(ctx, config_file, config_type)

# noinspection PyTypeHints
@bot.hybrid_command(name='zz_options', with_app_command=True)
@app_commands.describe(server='all, this, {guild_id}', volume='No division', buffer='In seconds',
                       language='Language code', response_type='short, long', buttons='True, False',
                       is_radio='True, False', loop='True, False', stopped='True, False',
                       history_length='Number of items in history (100 is probably a lot)')
@commands.check(is_authorised)
async def change_options(ctx: commands.Context, server=None, stopped: bool = None, loop: bool = None,
                         is_radio: bool = None, buttons: bool = None,
                         language: Literal[tuple(languages_dict.keys())] = None,
                         response_type: Literal['short', 'long'] = None, buffer: int = None, history_length: int = None,
                         volume: int = None, search_query: str = None, last_updated: int = None):
    log(ctx, 'zz_change_options',
        [server, stopped, loop, is_radio, buttons, language, response_type, buffer, history_length, volume,
         search_query, last_updated], log_type='command', author=ctx.author)

    await options_def(ctx, server=str(server), stopped=str(stopped), loop=str(loop), is_radio=str(is_radio),
                      buttons=str(buttons), language=str(language), response_type=str(response_type),
                      buffer=str(buffer), history_length=str(history_length), volume=str(volume),
                      search_query=str(search_query), last_updated=str(last_updated))

@bot.hybrid_command(name='zz_download_guild', with_app_command=True)
@commands.check(is_authorised)
async def download_guild_command(ctx: commands.Context, guild_id, ephemeral: bool=True):
    log(ctx, 'download_guild', [guild_id, ephemeral], log_type='command', author=ctx.author)

    await download_guild(ctx, guild_id, ephemeral=ephemeral)

@bot.hybrid_command(name='zz_download_guild_channel', with_app_command=True)
@commands.check(is_authorised)
async def download_guild_channel_command(ctx: commands.Context, channel_id, ephemeral: bool=True):
    log(ctx, 'download_guild_channel', [channel_id, ephemeral], log_type='command', author=ctx.author)

    await download_guild_channel(ctx, channel_id, ephemeral=ephemeral)

@bot.hybrid_command(name='zz_get_guild', with_app_command=True)
@commands.check(is_authorised)
async def get_guild_command(ctx: commands.Context, guild_id, ephemeral: bool=True):
    log(ctx, 'get_guild', [guild_id, ephemeral], log_type='command', author=ctx.author)

    await get_guild(ctx, guild_id, ephemeral=ephemeral)

@bot.hybrid_command(name='zz_get_guild_channel', with_app_command=True)
@commands.check(is_authorised)
async def get_guild_channel_command(ctx: commands.Context, channel_id, ephemeral: bool=True):
    log(ctx, 'get_guild_channel', [channel_id, ephemeral], log_type='command', author=ctx.author)

    await get_guild_channel(ctx, channel_id, ephemeral=ephemeral)

@bot.hybrid_command(name='zz_set_time', with_app_command=True)
@commands.check(is_authorised)
async def set_time_command(ctx: commands.Context, time_stamp: int, ephemeral: bool=True, mute_response: bool=False):
    log(ctx, 'set_time', [time_stamp, ephemeral, mute_response], log_type='command', author=ctx.author)

    await set_video_time(ctx, time_stamp, ephemeral=ephemeral, mute_response=mute_response)

# --------------------------------------------- COMMAND FUNCTIONS ------------------------------------------------------

def ctx_check(ctx: commands.Context or WebData) -> (bool, int, int, discord.Guild):
    """
    This function checks if the context is a discord context or a web context and returns the relevant information.

    is_ctx - True if the context is a discord context, False if it is a web context
    guild_id - The guild id of the context
    author_id - The author id of the context
    guild_object - The guild object of the context

    :type ctx: commands.Context | WebData
    :param ctx: commands.Context | WebData
    :return: (is_ctx, guild_id, author_id, guild) - (bool, int, int, discord.Guild)
    """
    save_json()
    if type(ctx) == WebData:
        is_ctx = False
        guild_id = ctx.guild_id
        author_id = ctx.author_id
        guild_object = bot.get_guild(guild_id)

    elif type(ctx) == commands.Context:
        is_ctx = True
        guild_id = ctx.guild.id
        author_id = ctx.author.id
        guild_object = ctx.guild

    else:
        raise TypeError(f'ctx_check: ctx is not a valid type: {type(ctx)}')

    return is_ctx, guild_id, author_id, guild_object

# --------------------------------------- QUEUE --------------------------------------------------

async def queue_command_def(ctx, url=None, position: int = None, mute_response: bool = False, force: bool = False, from_play: bool = False, probe_data: list = None, no_search: bool = False, ephemeral: bool = False, ) -> ReturnData:
    """
    This function tries to queue a song. It is called by the queue command and the play command.

    :param ctx: Context
    :param url: An input string that is either a URL or a search query
    :param position: An integer that represents the position in the queue to insert the song
    :param mute_response: Whether to mute the response or not
    :param force: Whether to force the song to play or not
    :param from_play: Set to True if the command is being called from the play command
    :param probe_data: Data from the probe command
    :param no_search: Whether to search for the song or not when the URL is not a URL
    :param ephemeral: Should the response be ephemeral
    :return: ReturnData(bool, str, VideoClass or None)
    """

    log(ctx, 'queue_command_def', [url, position, mute_response, force, from_play, probe_data, no_search, ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not url:
        message = tg(guild_id, "`url` is **required**")
        if not mute_response:
            await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    url_type, url = get_url_type(url)
    yt_id = extract_yt_id(url)

    if url_type == 'YouTube Playlist':
        if is_ctx:
            if not ctx.interaction.response.is_done():
                await ctx.defer(ephemeral=ephemeral)

        try:
            playlist_videos_result: dict = youtubesearchpython.Playlist.getVideos(url)
            playlist_videos: list = playlist_videos_result['videos']
        except KeyError:
            log(ctx, "------------------------------- playlist -------------------------")
            tb = traceback.format_exc()
            log(ctx, tb)
            log(ctx, "--------------------------------------------------------------")

            message = f'This playlist is not viewable: `{url}`'
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        if position is not None:
            playlist_videos = list(reversed(playlist_videos))

        for index, val in enumerate(playlist_videos):
            url = f"https://www.youtube.com/watch?v={playlist_videos[index]['id']}"
            video = VideoClass('Video', author_id, url)
            to_queue(guild_id, video, position=position, copy_video=False)

        message = f"`{len(playlist_videos)}` {tg(guild_id, 'songs from playlist added to queue!')} -> [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})"
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(True, message)

    if url_type == 'YouTube Playlist Video' and is_ctx:
        view = PlaylistOptionView(ctx, url, force, from_play)
        message = tg(guild_id, 'This video is from a **playlist**, do you want to add the playlist to **queue?**')
        await ctx.reply(message, view=view, ephemeral=ephemeral)
        return ReturnData(False, message)

    if url_type == 'Spotify Playlist' or url_type == 'Spotify Album':
        adding_message = None
        if is_ctx:
            adding_message = await ctx.reply(tg(guild_id, 'Adding songs to queue... (might take a while)'), ephemeral=ephemeral)

        if url_type == 'Spotify Playlist':
            video_list = spotify_playlist_to_yt_video_list(url, author_id)
        else:
            video_list = spotify_album_to_yt_video_list(url, author_id)

        if position is not None:
            video_list = list(reversed(video_list))

        for video in video_list:
            to_queue(guild_id, video, position=position, copy_video=False)

        message = f'`{len(video_list)}` {tg(guild_id, "songs from playlist added to queue!")} -> [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})'
        if is_ctx:
            await adding_message.edit(content=message)
        return ReturnData(True, message)

    if url_type == 'Spotify Track':
        video = spotify_to_yt_video(url, author_id)
        if video is not None:
            message = to_queue(guild_id, video, position=position, copy_video=False)
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(True, message)

    if url_type == 'Spotify URL':
        video = spotify_to_yt_video(url, author_id)
        if video is None:
            message = f'{tg(guild_id, "Invalid spotify url")}: `{url}`'
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        message = to_queue(guild_id, video, position=position, copy_video=False)
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(True, message)

    if url_type == 'SoundCloud URL':
        try:
            track = sc.resolve(url)
        except Exception as e:
            message = f'{tg(guild_id, "Invalid SoundCloud url")}: {url} -> {e}'
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        if type(track) == Track:
            try:
                video = VideoClass('SoundCloud', author=author_id, url=url)
            except ValueError as e:
                if not mute_response:
                    await ctx.reply(e, ephemeral=ephemeral)
                return ReturnData(False, f"{e}")

            message = to_queue(guild_id, video, position=position, copy_video=False)
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(True, message)

        if type(track) == Playlist:
            tracks = track.tracks
            if position is not None:
                tracks = list(reversed(tracks))

            for index, val in enumerate(tracks):
                duration = int(val.duration * 0.001)
                artist_url = 'https://soundcloud.com/' + track.permalink_url.split('/')[-2]

                video = VideoClass('SoundCloud', author=author_id, url=val.permalink_url, title=val.title,
                                   picture=val.artwork_url, duration=duration, channel_name=val.artist,
                                   channel_link=artist_url)
                to_queue(guild_id, video, position=position, copy_video=False)

            message = f"`{len(tracks)}` {tg(guild_id, 'songs from playlist added to queue!')} -> [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})"
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(True, message)

    if url_type == 'YouTube Video' or yt_id is not None:
        url = f"https://www.youtube.com/watch?v={yt_id}"
        video = VideoClass('Video', author_id, url=url)
        message = to_queue(guild_id, video, position=position, copy_video=False)
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(True, message)

    if url_type == 'String with URL':
        probe, extracted_url = await get_url_probe_data(url)
        if probe:
            if not probe_data:
                probe_data = [extracted_url, extracted_url, extracted_url]

            video = VideoClass('Probe', author_id, url=extracted_url, title=probe_data[0], picture=vlc_logo, duration='Unknown', channel_name=probe_data[1], channel_link=probe_data[2])
            message = to_queue(guild_id, video, position=position, copy_video=False)
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(True, message)

    if is_ctx and not no_search:
        return await search_command_def(ctx, url, display_type='short', force=force, from_play=from_play, ephemeral=ephemeral)

    message = f'`{url}` {tg(guild_id, "is not supported!")} -> [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})'
    if not mute_response:
        await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(False, message)

async def next_up_def(ctx, url, ephemeral: bool = False):
    """
    Adds a song to the queue and plays it if the queue is empty
    :param ctx: Context
    :param url: An input url
    :param ephemeral: Should the response be ephemeral
    :return: None
    """
    log(ctx, 'next_up_def', [url, ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)
    response = await queue_command_def(ctx, url, position=0, mute_response=True, force=True)

    if response.response:
        if guild_object.voice_client:
            if not guild_object.voice_client.is_playing():
                await play_def(ctx)
                return
        else:
            await play_def(ctx)
            return

        await ctx.reply(response.message, ephemeral=ephemeral)

    else:
        return

    save_json()

async def skip_def(ctx) -> ReturnData:
    """
    Skips the current song
    :param ctx: Context
    :return: ReturnData
    """
    log(ctx, 'skip_def', [], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if guild_object.voice_client:
        if guild_object.voice_client.is_playing():
            stop_response = await stop_def(ctx, mute_response=True, keep_loop=True)
            if not stop_response.response:
                return stop_response

            await asyncio.sleep(0.5)

            play_response = await play_def(ctx)
            if not play_response.response:
                return play_response

            return ReturnData(True, 'Skipped!')

    message = tg(guild_id, "There is **nothing to skip!**")
    await ctx.reply(message, ephemeral=True)
    return ReturnData(False, message)

async def remove_def(ctx, number: int, display_type: Literal['short', 'long'] = None, ephemeral: bool = False, list_type: Literal['queue', 'history'] = 'queue') -> ReturnData:
    """
    Removes a song from the queue or history
    :param ctx: Context
    :param number: index of the song to be removed
    :param display_type: ('short' or 'long') How the response should be displayed
    :param ephemeral: Should the response be ephemeral
    :param list_type: ('queue' or 'history') Which list to remove from
    :return: ReturnData
    """
    log(ctx, 'remove_def', [number, display_type, ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not display_type:
        display_type = guild[guild_id].options.response_type

    if list_type == 'queue':
        if number or number == 0 or number == '0':
            if number > len(guild[guild_id].queue):
                if not guild[guild_id].queue:
                    message = tg(guild_id, "Nothing to **remove**, queue is **empty!**")
                    await ctx.reply(message, ephemeral=True)
                    return ReturnData(False, message)
                message = tg(guild_id, "Index out of range!")
                await ctx.reply(message, ephemeral=True)
                return ReturnData(False, message)

            video = guild[guild_id].queue[number]

            message = f'REMOVED #{number} : [`{video.title}`](<{video.url}>)'

            if display_type == 'long':
                embed = create_embed(video, f'{tg(guild_id, "REMOVED #")}{number}', guild_id)
                await ctx.reply(embed=embed, ephemeral=ephemeral)
            if display_type == 'short':
                await ctx.reply(message, ephemeral=ephemeral)

            guild[guild_id].queue.pop(number)

            save_json()

            return ReturnData(True, message)

    elif list_type == 'history':
        if number or number == 0 or number == '0':
            if number > len(guild[guild_id].history):
                if not guild[guild_id].history:
                    message = tg(guild_id, "Nothing to **remove**, history is **empty!**")
                    await ctx.reply(message, ephemeral=True)
                    return ReturnData(False, message)
                message = tg(guild_id, "Index out of range!")
                await ctx.reply(message, ephemeral=True)
                return ReturnData(False, message)

            video = guild[guild_id].history[number]

            message = f'REMOVED #{number} : [`{video.title}`](<{video.url}>)'

            if display_type == 'long':
                embed = create_embed(video, f'{tg(guild_id, "REMOVED #")}{number}', guild_id)
                await ctx.reply(embed=embed, ephemeral=ephemeral)
            if display_type == 'short':
                await ctx.reply(message, ephemeral=ephemeral)

            guild[guild_id].history.pop(number)

            save_json()

            return ReturnData(True, message)

    else:
        save_json()
        message = tg(guild_id, 'Invalid list type!')
        await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    save_json()

    return ReturnData(False, tg(guild_id, 'No number given!'))

async def clear_def(ctx, ephemeral: bool = False) -> ReturnData:
    """
    Clears the queue
    :param ctx: Context
    :param ephemeral: Should the response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'clear_def', [ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    guild[guild_id].queue.clear()
    save_json()

    message = tg(guild_id, 'Removed **all** songs from queue')
    await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(True, message)

async def shuffle_def(ctx, ephemeral: bool = False) -> ReturnData:
    """
    Shuffles the queue
    :param ctx: Context
    :param ephemeral: Should the response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'shuffle_def', [ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    random.shuffle(guild[guild_id].queue)
    save_json()

    message = tg(guild_id, 'Songs in queue shuffled')
    await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(True, message)

async def show_def(ctx, display_type: Literal['short', 'medium', 'long'] = None, list_type: Literal['queue', 'history'] = 'queue', ephemeral: bool = False) -> ReturnData:
    """
    Shows the queue or history (only in discord)
    :param ctx: Context
    :param display_type: ('short', 'medium' or 'long') How the response should be displayed
    :param list_type: ('queue' or 'history') Which list to show
    :param ephemeral: Should the response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'show_def', [display_type, list_type, ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'Cannot use this command in WEB'))

    if list_type == 'queue':
        show_list = guild[guild_id].queue
    elif list_type == 'history':
        show_list = list(reversed(guild[guild_id].history))
    else:
        return ReturnData(False, tg(guild_id, 'Bad list_type'))

    max_embed = 5
    if not show_list:
        message = tg(guild_id, "Nothing to **show**, queue is **empty!**")
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(True, message)

    if not display_type:
        if len(show_list) <= max_embed:
            display_type = 'long'
        else:
            display_type = 'medium'

    if display_type == 'long':
        message = f"**THE {list_type.capitalize()}**\n **Loop** mode  `{guild[guild_id].options.loop}`,  **Display** type `{display_type}`, [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})"
        await ctx.send(message, ephemeral=ephemeral, mention_author=False)

        for index, val in enumerate(show_list):
            embed = create_embed(val, f'{tg(guild_id, f"{list_type.upper()} #")}{index}', guild_id)

            await ctx.send(embed=embed, ephemeral=ephemeral, mention_author=False)

    if display_type == 'medium':
        embed = discord.Embed(title=f"Song {list_type}",
                              description=f'Loop: {guild[guild_id].options.loop} | Display type: {display_type} | [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})',
                              color=0x00ff00)

        message = ''
        for index, val in enumerate(show_list):
            add = f'**{index}** --> `{convert_duration(val.duration)}`  [{val.title}](<{val.url}>) \n'

            if len(message) + len(add) > 1023:
                embed.add_field(name="", value=message, inline=False)
                message = ''
            else:
                message = message + add

        embed.add_field(name="", value=message, inline=False)

        if len(embed) < 6000:
            await ctx.reply(embed=embed, ephemeral=ephemeral, mention_author=False)
        else:
            await ctx.reply("HTTPException(discord 6000 character limit) >> using display type `short`",
                            ephemeral=ephemeral, mention_author=False)
            display_type = 'short'

    if display_type == 'short':
        send = f"**THE {list_type.upper()}**\n **Loop** mode  `{guild[guild_id].options.loop}`,  **Display** type `{display_type}`, [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})"
        # noinspection PyUnresolvedReferences
        if ctx.interaction.response.is_done():
            await ctx.send(send, ephemeral=ephemeral, mention_author=False)
        else:
            await ctx.reply(send, ephemeral=ephemeral, mention_author=False)

        message = ''
        for index, val in enumerate(show_list):
            add = f'**{tg(guild_id, f"{list_type.upper()} #")}{index}**  `{convert_duration(val.duration)}`  [`{val.title}`](<{val.url}>) \n'
            if len(message) + len(add) > 2000:
                if ephemeral:
                    await ctx.send(message, ephemeral=ephemeral, mention_author=False)
                else:
                    await ctx.message.channel.send(content=message, mention_author=False)
                message = ''
            else:
                message = message + add

        if ephemeral:
            await ctx.send(message, ephemeral=ephemeral, mention_author=False)
        else:
            await ctx.message.channel.send(content=message, mention_author=False)

    save_json()

async def search_command_def(ctx, search_query, display_type: Literal['short', 'long'] = None, force: bool = False, from_play: bool = False, ephemeral: bool = False) -> ReturnData:
    """
    Search for a song and add it to the queue with buttons (only in discord)
    :param ctx: Context
    :param search_query: String to be searched for in YouTube
    :param display_type: ('short' or 'long') How the response should be displayed
    :param force: bool - if True, the song will be added to the front of the queue
    :param from_play: bool - if True, the song will be played after it is added to the queue, even if another one is already playing
    :param ephemeral: Should the response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'search_command_def', [search_query, display_type, force, from_play, ephemeral], log_type='function',
        author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'Search command cannot be used in WEB'))

    # noinspection PyUnresolvedReferences
    if not ctx.interaction.response.is_done():
        await ctx.defer(ephemeral=ephemeral)

    guild[guild_id].options.search_query = search_query

    if display_type is None:
        display_type = guild[guild_id].options.response_type

    message = f'**Search query:** `{search_query}`\n'

    if display_type == 'long':
        await ctx.reply(tg(guild_id, 'Searching...'), ephemeral=ephemeral)

    custom_search = youtubesearchpython.VideosSearch(search_query, limit=5)
    guild[guild_id].search_list.clear()

    view = SearchOptionView(ctx, force, from_play)

    if not custom_search.result()['result']:
        message = tg(guild_id, 'No results found!')
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    for i in range(5):
        # noinspection PyTypeChecker
        url = custom_search.result()['result'][i]['link']
        video = VideoClass('Video', ctx.author.id, url)
        guild[guild_id].search_list.append(video)

        if display_type == 'long':
            embed = create_embed(video, f'{tg(guild_id, "Result #")}{i + 1}', guild_id)
            await ctx.message.channel.send(embed=embed, ephemeral=ephemeral)
        if display_type == 'short':
            message += f'{tg(guild_id, "Result #")}{i + 1} : [`{video.title}`](<{video.url}>)\n'
    if display_type == 'short':
        await ctx.reply(message, view=view, ephemeral=ephemeral)

    save_json()

# --------------------------------------- PLAYER --------------------------------------------------

async def play_def(ctx, url=None, force=False, mute_response=False, after=False) -> ReturnData:
    log(ctx, 'play_def', [url, force, mute_response, after], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)
    response = ReturnData(False, tg(guild_id, 'Unknown error'))

    notif = f' -> [Control Panel]({config.WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})'

    if after and guild[guild_id].options.stopped:
        log(ctx, "play_def -> stopped play next loop")
        now_to_history(guild_id)
        return ReturnData(False, tg(guild_id, "Stopped play next loop"))

    voice = guild_object.voice_client

    if not voice:
        if not is_ctx:
            return ReturnData(False, tg(guild_id, 'Bot is not connected to a voice channel'))

        if ctx.author.voice is None:
            message = tg(guild_id, "You are **not connected** to a voice channel")
            if not mute_response:
                await ctx.reply(message)
            return ReturnData(False, message)

    if is_ctx:
        if not ctx.interaction.response.is_done():
            await ctx.defer()

    if url:
        if voice:
            if not voice.is_playing():
                force = True

        position = 0 if force else None
        response = await queue_command_def(ctx, url=url, position=position, mute_response=True, force=force, from_play=True)

        if not response or not response.response:
            return response

    if not guild_object.voice_client:
        # if not is_ctx:
        #     if not ctx.interaction.response.is_done():
        #         await ctx.defer()
        join_response = await join_def(ctx, None, True)
        voice = guild_object.voice_client
        if not join_response.response:
            return join_response

    if voice.is_playing():
        if not guild[guild_id].options.is_radio and not force:
            if url:
                if response.video is not None:
                    message = f'{tg(guild_id, "**Already playing**, added to queue")}: [`{response.video.title}`](<{response.video.url}>) {notif}'
                    if not mute_response:
                        await ctx.reply(message)
                    return ReturnData(False, message)

                message = f'{tg(guild_id, "**Already playing**, added to queue")} {notif}'
                if not mute_response:
                    await ctx.reply(message)
                return ReturnData(False, message)

            message = f'{tg(guild_id, "**Already playing**")} {notif}'
            if not mute_response:
                await ctx.reply(message)
            return ReturnData(False, message)

        voice.stop()
        guild[guild_id].options.stopped = True
        guild[guild_id].options.is_radio = False

    if voice.is_paused():
        return await resume_def(ctx)

    if not guild[guild_id].queue:
        message = f'{tg(guild_id, "There is **nothing** in your **queue**")} {notif}'
        if not after and not mute_response:
            await ctx.reply(message)
        now_to_history(guild_id)
        return ReturnData(False, message)

    video = guild[guild_id].queue[0]
    now_to_history(guild_id)

    if video.class_type not in ['Video', 'Probe', 'SoundCloud']:
        guild[guild_id].queue.pop(0)
        if video.class_type == 'Radio':
            return await radio_def(ctx, video.title)
        if video.class_type == 'Local':
            return await ps_def(ctx, video.local_number)

        message = tg(guild_id, "Unknown type")
        if not mute_response:
            await ctx.reply(message)
        return ReturnData(False, message)

    if not force:
        guild[guild_id].options.stopped = False

    try:
        source, chapters = await GetSource.create_source(guild_id, video.url, source_type=video.class_type, video_class=video)
        voice.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_def(ctx, after=True), bot.loop))

        await volume_command_def(ctx, guild[guild_id].options.volume * 100, False, True)

        # Variables update
        guild[guild_id].options.stopped = False
        # video variables
        set_started(video, guild_object, chapters=chapters)

        # Queue update
        # if guild[guild_id].options.loop:
        #     to_queue(guild_id, video)
        guild[guild_id].queue.pop(0)

        save_json()

        # Response
        options = guild[guild_id].options
        response_type = options.response_type

        message = f'{tg(guild_id, "Now playing")} [`{video.title}`](<{video.url}>) {notif}'
        view = PlayerControlView(ctx)

        if response_type == 'long':
            if not mute_response:
                embed = create_embed(video, tg(guild_id, "Now playing"), guild_id)
                if options.buttons:
                    await ctx.reply(embed=embed, view=view)
                else:
                    await ctx.reply(embed=embed)
            return ReturnData(True, message)

        elif response_type == 'short':
            if not mute_response:
                if options.buttons:
                    await ctx.reply(message, view=view)
                else:
                    await ctx.reply(message)
            return ReturnData(True, message)

        else:
            return ReturnData(True, message)

    except (discord.ext.commands.errors.CommandInvokeError, IndexError, TypeError, discord.errors.ClientException,
            discord.errors.NotFound):
        log(ctx, "------------------------------- play -------------------------")
        tb = traceback.format_exc()
        log(ctx, tb)
        log(ctx, "--------------------------------------------------------------")
        message = f'{tg(guild_id, "An **error** occurred while trying to play the song")} {bot.get_user(my_id).mention} ({sys.exc_info()[0]})'
        await ctx.reply(message)
        return ReturnData(False, message)

async def radio_def(ctx, favourite_radio: Literal['Rádio BLANÍK', 'Rádio BLANÍK CZ', 'Evropa 2', 'Fajn Radio', 'Hitrádio PopRock', 'Český rozhlas Pardubice', 'Radio Beat', 'Country Radio', 'Radio Kiss', 'Český rozhlas Vltava', 'Hitrádio Černá Hora'] = None,
                    radio_code: int = None) -> ReturnData:
    """
    Play radio
    :param ctx: Context
    :param favourite_radio: ('Rádio BLANÍK', 'Rádio BLANÍK CZ', 'Evropa 2', 'Fajn Radio', 'Hitrádio PopRock', 'Český rozhlas Pardubice', 'Radio Beat', 'Country Radio', 'Radio Kiss', 'Český rozhlas Vltava', 'Hitrádio Černá Hora')
    :param radio_code: (0-95)
    :return: ReturnData
    """
    log(ctx, 'radio_def', [favourite_radio, radio_code], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    # noinspection PyUnresolvedReferences
    if is_ctx:
        if not ctx.interaction.response.is_done():
            await ctx.defer()
    if favourite_radio and radio_code:
        message = tg(guild_id, "Only **one** argument possible!")
        await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    if favourite_radio:
        radio_type: str = favourite_radio
    elif radio_code:
        radio_type: str = list(radio_dict.keys())[radio_code]
    else:
        radio_type: str = 'Evropa 2'

    if not guild_object.voice_client:
        response = await join_def(ctx, None, True)
        if not response.response:
            return response

    if guild_object.voice_client.is_playing():
        await stop_def(ctx, mute_response=True)

    guild[guild_id].options.is_radio = True

    url = radio_dict[radio_type]['stream']
    video = VideoClass('Radio', author_id, radio_info=dict(name=radio_type), stream_url=url)
    video.renew()

    source, chapters = await GetSource.create_source(guild_id, url, source_type='Radio', video_class=video)
    set_started(video, chapters=chapters, guild_object=guild_object)

    guild_object.voice_client.play(source)

    await volume_command_def(ctx, guild[guild_id].options.volume * 100, False, True)

    embed = create_embed(video, tg(guild_id, "Now playing"), guild_id)
    if guild[guild_id].options.buttons:
        view = PlayerControlView(ctx)
        await ctx.reply(embed=embed, view=view)
    else:
        await ctx.reply(embed=embed)

    save_json()

    return ReturnData(True, tg(guild_id, "Radio **started**"))

async def ps_def(ctx, effect_number: app_commands.Range[int, 1, len(all_sound_effects)], mute_response: bool = False) -> ReturnData:
    """
    Play sound effect
    :param ctx: Context
    :param effect_number: index of sound effect (show all sound effects with sound_effects_def)
    :param mute_response: bool - Should bot response be muted
    :return: ReturnData
    """
    log(ctx, 'ps_def', [effect_number, mute_response], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)
    guild[guild_id].options.is_radio = False
    try:
        name = all_sound_effects[effect_number]
    except IndexError:
        message = tg(guild_id, "Number **not in list** (use `/sound` to get all sound effects)")
        if not mute_response:
            await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    filename = f"{config.PARENT_DIR}sound_effects/{name}.mp3"
    if path.exists(filename):
        source, chapters = await GetSource.create_source(guild_id, filename, source_type='Local')
    else:
        filename = f"{config.PARENT_DIR}sound_effects/{name}.wav"
        if path.exists(filename):
            source, chapters = await GetSource.create_source(guild_id, filename, source_type='Local')
        else:
            message = tg(guild_id, "No such file/website supported")
            if not mute_response:
                await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

    if not guild_object.voice_client:
        join_response = await join_def(ctx, None, True)
        if not join_response.response:
            return join_response

    stop_response = await stop_def(ctx, mute_response=True)
    if not stop_response.response:
        return stop_response

    video = VideoClass('Local', author_id, title=name, duration='Unknown', local_number=effect_number, stream_url=filename)
    set_started(video, guild_object, chapters=chapters)

    voice = guild_object.voice_client
    voice.play(source)
    await volume_command_def(ctx, guild[guild_id].options.volume * 100, False, True)

    message = tg(guild_id, "Playing sound effect number") + f" `{effect_number}`"
    if not mute_response:
        await ctx.reply(message, ephemeral=True)
    return ReturnData(True, message)

async def now_def(ctx, ephemeral: bool = False) -> ReturnData:
    """
    Show now playing song
    :param ctx: Context
    :param ephemeral: Should bot response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'now_def', [ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)
    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'This command cant be used in WEB'))

    if ctx.voice_client:
        if ctx.voice_client.is_playing():
            guild[guild_id].now_playing.renew()
            embed = create_embed(guild[guild_id].now_playing, tg(guild_id, "Now playing"), guild_id)

            view = PlayerControlView(ctx)

            if guild[guild_id].options.buttons:
                await ctx.reply(embed=embed, view=view, ephemeral=ephemeral)
                return ReturnData(True, tg(guild_id, "Now playing"))

            await ctx.reply(embed=embed, ephemeral=ephemeral)
            return ReturnData(True, tg(guild_id, "Now playing"))

        if ctx.voice_client.is_paused():
            message = f'{tg(guild_id, "There is no song playing right **now**, but there is one **paused:**")} [`{guild[guild_id].now_playing.title}`](<{guild[guild_id].now_playing.url}>)'
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        message = tg(guild_id, 'There is no song playing right **now**')
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    message = tg(guild_id, 'There is no song playing right **now**')
    await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(False, message)

async def last_def(ctx, ephemeral: bool = False) -> ReturnData:
    """
    Show last played song
    :param ctx: Context
    :param ephemeral: Should bot response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'last_def', [ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)
    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'This command cant be used in WEB'))

    if not guild[guild_id].history:
        message = tg(guild_id, 'There is no song played yet')
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    embed = create_embed(guild[guild_id].history[-1], tg(guild_id, "Last Played"), guild_id)
    view = PlayerControlView(ctx)

    if guild[guild_id].options.buttons:
        await ctx.reply(embed=embed, view=view, ephemeral=ephemeral)
    else:
        await ctx.reply(embed=embed, ephemeral=ephemeral)

    return ReturnData(True, tg(guild_id, "Last Played"))

async def loop_command_def(ctx, clear_queue: bool=False, ephemeral: bool=False) -> ReturnData:
    """
    Loop command
    :param ctx: Context
    :param clear_queue: Should queue be cleared
    :param ephemeral: Should bot response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'loop_command_def', [clear_queue, ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    # add now_playing to queue if loop is activated
    add_to_queue_when_activated = False

    options = guild[guild_id].options

    if clear_queue:
        if options.loop:
            message = tg(guild_id, "Loop mode is already enabled")
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        if not guild[guild_id].now_playing or not guild_object.voice_client.is_playing:
            message = tg(guild_id, "There is no song playing right **now**")
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        guild[guild_id].queue.clear()
        to_queue(guild_id, guild[guild_id].now_playing)
        guild[guild_id].options.loop = True
        save_json()

        message = f'{tg(guild_id, "Queue **cleared**, Player will now loop **currently** playing song:")} [`{guild[guild_id].now_playing.title}`](<{guild[guild_id].now_playing.url}>)'
        await ctx.reply(message)
        return ReturnData(True, message)

    if options.loop:
        guild[guild_id].options.loop = False
        save_json()

        message = tg(guild_id, "Loop mode: `False`")
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(True, message)

    guild[guild_id].options.loop = True
    if guild[guild_id].now_playing and add_to_queue_when_activated:
        to_queue(guild_id, guild[guild_id].now_playing)
    save_json()

    message = tg(guild_id, 'Loop mode: `True`')
    await ctx.reply(message, ephemeral=True)
    return ReturnData(True, message)

# --------------------------------------- VOICE --------------------------------------------------

async def stop_def(ctx, mute_response: bool = False, keep_loop: bool = False) -> ReturnData:
    """
    Stops player
    :param ctx: Context
    :param mute_response: Should bot response be muted
    :param keep_loop: Should loop be kept
    :return: ReturnData
    """
    log(ctx, 'stop_def', [mute_response, keep_loop], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    voice: discord.voice_client.VoiceClient = get_voice_client(bot.voice_clients, guild=guild_object)

    if not voice:
        message = tg(guild_id, "Bot is not connected to a voice channel")
        if not mute_response:
            await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    voice.stop()

    guild[guild_id].options.stopped = True
    if not keep_loop:
        guild[guild_id].options.loop = False

    now_to_history(guild_id)

    message = tg(guild_id, "Player **stopped!**")
    if not mute_response:
        await ctx.reply(message, ephemeral=True)
    return ReturnData(True, message)

async def pause_def(ctx, mute_response: bool = False) -> ReturnData:
    """
    Pause player
    :param ctx: Context
    :param mute_response: Should bot response be muted
    :return: ReturnData
    """
    log(ctx, 'pause_def', [mute_response], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    voice: discord.voice_client.VoiceClient = get_voice_client(bot.voice_clients, guild=guild_object)

    if voice:
        if voice.is_playing():
            voice.pause()
            if guild[guild_id].now_playing:
                set_stopped(guild[guild_id].now_playing)
            message = tg(guild_id, "Player **paused!**")
            resp = True
        elif voice.is_paused():
            message = tg(guild_id, "Player **already paused!**")
            resp = False
        else:
            message = tg(guild_id, 'No audio playing')
            resp = False
    else:
        message = tg(guild_id, "Bot is not connected to a voice channel")
        resp = False

    save_json()

    if not mute_response:
        await ctx.reply(message, ephemeral=True)
    return ReturnData(resp, message)

async def resume_def(ctx, mute_response: bool = False) -> ReturnData:
    """
    Resume player
    :param ctx: Context
    :param mute_response: Should bot response be muted
    :return: ReturnData
    """
    log(ctx, 'resume_def', [mute_response], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    voice: discord.voice_client.VoiceClient = get_voice_client(bot.voice_clients, guild=guild_object)

    if voice:
        if voice.is_paused():
            voice.resume()
            if guild[guild_id].now_playing:
                set_resumed(guild[guild_id].now_playing)
            message = tg(guild_id, "Player **resumed!**")
            resp = True
        elif voice.is_playing():
            message = tg(guild_id, "Player **already resumed!**")
            resp = False
        else:
            message = tg(guild_id, 'No audio playing')
            resp = False
    else:
        message = tg(guild_id, "Bot is not connected to a voice channel")
        resp = False

    save_json()

    if not mute_response:
        await ctx.reply(message, ephemeral=True)
    return ReturnData(resp, message)

async def join_def(ctx, channel_id=None, mute_response: bool = False) -> ReturnData:
    """
    Join voice channel
    :param ctx: Context
    :param channel_id: id of channel to join
    :param mute_response: Should bot response be muted
    :return: ReturnData
    """
    log(ctx, 'join_def', [channel_id, mute_response], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    # if video in now_playing -> add to history
    now_to_history(guild_id)

    # define author channel (for ide)
    author_channel = None

    if not channel_id:
        # if not from ctx and no channel_id provided return False
        if not is_ctx:
            return ReturnData(False, tg(guild_id, 'No channel_id provided'))

        if ctx.author.voice:
            # get author voice channel
            author_channel = ctx.author.voice.channel

            if ctx.voice_client:
                # if bot is already connected to author channel return True
                if ctx.voice_client.channel == author_channel:
                    message = tg(guild_id, "I'm already in this channel")
                    if not mute_response:
                        await ctx.reply(message, ephemeral=True)
                    return ReturnData(True, message)
        else:
            # if author is not connected to a voice channel return False
            message = tg(guild_id, "You are **not connected** to a voice channel")
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

    try:
        # get voice channel
        if author_channel:
            voice_channel = author_channel
        else:
            voice_channel = bot.get_channel(int(channel_id))

        # check if bot has permission to join channel
        if not voice_channel.permissionas_for(guild_object.me).connect:
            message = tg(guild_id, "I don't have permission to join this channel")
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

        # check if bot has permission to speak in channel
        if not voice_channel.permissions_for(guild_object.me).speak:
            message = tg(guild_id, "I don't have permission to speak in this channel")
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

        # check if the channel is empty
        if not len(voice_channel.members) > 0:
            message = tg(guild_id, "The channel is empty")
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

        # disconnect from voice channel if connected
        if guild_object.voice_client:
            await guild_object.voice_client.disconnect(force=True)
        # connect to voice channel
        await voice_channel.connect()
        # deafen bot
        await guild_object.change_voice_state(channel=voice_channel, self_deaf=True)

        message = f"{tg(guild_id, 'Joined voice channel:')}  `{voice_channel.name}`"
        if not mute_response:
            await ctx.reply(message, ephemeral=True)
        return ReturnData(True, message)

    except (discord.ext.commands.errors.CommandInvokeError, discord.errors.ClientException, AttributeError, ValueError,
            TypeError):
        log(ctx, "------------------------------- join -------------------------")
        tb = traceback.format_exc()
        log(ctx, tb)
        log(ctx, "--------------------------------------------------------------")

        message = tg(guild_id, "Channel **doesn't exist** or bot doesn't have **sufficient permission** to join")
        await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

async def disconnect_def(ctx, mute_response: bool = False) -> ReturnData:
    """
    Disconnect bot from voice channel
    :param ctx: Context
    :param mute_response: Should bot response be muted
    :return: ReturnData
    """
    log(ctx, 'disconnect_def', [mute_response], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if guild_object.voice_client:
        await stop_def(ctx, mute_response=True)
        guild[guild_id].queue.clear()

        channel = guild_object.voice_client.channel
        await guild_object.voice_client.disconnect(force=True)

        now_to_history(guild_id)
        message = f"{tg(guild_id, 'Left voice channel:')} `{channel}`"
        if not mute_response:
            await ctx.reply(message, ephemeral=True)
        return ReturnData(True, message)
    else:
        now_to_history(guild_id)
        message = tg(guild_id, "Bot is **not** in a voice channel")
        if not mute_response:
            await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

async def volume_command_def(ctx, volume: Union[float, int] = None, ephemeral: bool = False, mute_response: bool = False) -> ReturnData:
    """
    Change volume of player
    :param ctx: Context
    :param volume: volume to set
    :param ephemeral: Should bot response be ephemeral
    :param mute_response: Should bot response be muted
    :return: ReturnData
    """
    log(ctx, 'volume_command_def', [volume, ephemeral, mute_response], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if volume:
        try:
            volume = int(volume)
        except (ValueError, TypeError):
            message = tg(guild_id, f'Invalid volume')
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        new_volume = volume / 100

        guild[guild_id].options.volume = new_volume
        voice = guild_object.voice_client
        if voice:
            try:
                if voice.source:
                    voice.source.volume = new_volume
                    # voice.source = discord.PCMVolumeTransformer(voice.source, volume=new_volume) -- just trouble
            except AttributeError:
                pass

        message = f'{tg(guild_id, "Changed the volume for this server to:")} `{guild[guild_id].options.volume * 100}%`'
    else:
        message = f'{tg(guild_id, "The volume for this server is:")} `{guild[guild_id].options.volume * 100}%`'

    save_json()

    if not mute_response:
        await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(True, message)

# --------------------------------------- GENERAL --------------------------------------------------

async def ping_def(ctx) -> ReturnData:
    """
    Ping command
    :param ctx: Context
    :return: ReturnData
    """
    log(ctx, 'ping_def', [], log_type='function', author=ctx.author)
    save_json()

    # await ctx.defer(ephemeral=True)
    #
    # # await download_guild_channel(ctx, ctx.channel.id)
    # #
    # # await asyncio.sleep(10)
    #
    # await get_guild(ctx, ctx.guild.id)
    #
    # update_guilds()
    # push_update(ctx.guild.id)

    # await set_video_time(ctx, 60)

    message = f'**Pong!** Latency: {round(bot.latency * 1000)}ms'
    await ctx.reply(message)
    return ReturnData(True, message)

# noinspection PyTypeHints
async def language_command_def(ctx, country_code: Literal[tuple(languages_dict.keys())]) -> ReturnData:
    """
    Change language of bot in guild
    :param ctx: Context
    :param country_code: Country code of language (e.g. en, cs, sk ...)
    :return: ReturnData
    """
    log(ctx, 'language_command_def', [country_code], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    guild[guild_id].options.language = country_code
    save_json()

    message = f'{tg(guild_id, "Changed the language for this server to: ")} `{guild[guild_id].options.language}`'
    await ctx.reply(message)
    return ReturnData(True, message)

async def sound_effects_def(ctx, ephemeral: bool = True) -> ReturnData:
    """
    List of all sound effects
    :param ctx: Context
    :param ephemeral: Should bot response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'sound_effects_def', [ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'Command cannot be used in WEB'))

    embed = discord.Embed(title="Sound Effects", colour=discord.Colour.from_rgb(241, 196, 15))
    message = ''
    for index, val in enumerate(all_sound_effects):
        add = f'**{index}** -> {val}\n'

        if len(message) + len(add) > 1023:
            embed.add_field(name="", value=message, inline=False)
            message = ''
        else:
            message = message + add

    embed.add_field(name="", value=message, inline=False)

    save_json()
    await ctx.send(embed=embed, ephemeral=ephemeral)
    return ReturnData(True, tg(guild_id, 'Sound effects'))

async def list_radios_def(ctx, ephemeral: bool = True) -> ReturnData:
    """
    List of all radios
    :param ctx: Context
    :param ephemeral: Should bot response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'list_radios_def', [ephemeral], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'Command cannot be used in WEB'))

    embed = discord.Embed(title="Radio List")
    message = ''
    for index, (name, val) in enumerate(radio_dict.items()):
        add = f'**{index}** -> {name}\n'

        if len(message) + len(add) > 1023:
            embed.add_field(name="", value=message, inline=False)
            message = ''
        else:
            message = message + add

    embed.add_field(name="", value=message, inline=False)

    save_json()
    await ctx.send(embed=embed, ephemeral=ephemeral)
    return ReturnData(True, tg(guild_id, 'Radio list'))

async def key_def(ctx: commands.Context) -> ReturnData:
    """
    Get key of guild
    :param ctx: Context
    :return: ReturnData
    """
    log(ctx, 'key_def', [], log_type='function', author=ctx.author)
    save_json()

    message = f'Key: `{guild[ctx.guild.id].data.key}` -> [Control Panel]({config.WEB_URL}/guild/{ctx.guild.id}&key={guild[ctx.guild.id].data.key})'
    await ctx.reply(message)
    return ReturnData(True, message)

async def options_command_def(ctx, loop=None, language=None, response_type=None, buttons=None, volume=None, buffer=None, history_length=None) -> ReturnData:
    log(ctx, 'options_command_def', [loop, language, response_type, buttons, volume, buffer, history_length],
        log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not is_ctx:
        return ReturnData(False, tg(guild_id, 'Command cannot be used in WEB'))

    if all(v is None for v in [loop, language, response_type, buttons, volume, buffer, history_length]):
        return await options_def(ctx, server=None, ephemeral=False)

    return await options_def(ctx, server=guild_id, ephemeral=False, loop=str(loop), language=str(language),
                             response_type=str(response_type), buttons=str(buttons), volume=str(volume),
                             buffer=str(buffer), history_length=str(history_length))

# ---------------------------------------- ADMIN --------------------------------------------------

async def announce_command_def(ctx, message: str, ephemeral: bool = False) -> ReturnData:
    """
    Announce message to all servers
    :param ctx: Context
    :param message: Message to announce
    :param ephemeral: Should bot response be ephemeral
    :return: ReturnData
    """
    log(ctx, 'announce_command_def', [message, ephemeral], log_type='function', author=ctx.author)
    for guild_object in bot.guilds:
        try:
            await guild_object.system_channel.send(message)
        except Exception as e:
            log(ctx, f"Error while announcing message to ({guild_object.name}): {e}", [guild_object.id, ephemeral],
                log_type='error', author=ctx.author)

    message = f'Announced message to all servers: `{message}`'
    await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(True, message)

async def earrape_command_def(ctx: commands.Context):
    log(ctx, 'ear_rape_command_def', [], log_type='function', author=ctx.author)
    guild_id = ctx.guild.id
    times = 10
    new_volume = 10000000000000

    guild[guild_id].options.volume = 1.0

    voice = ctx.voice_client
    if voice:
        try:
            if voice.source:
                for i in range(times):
                    voice.source.volume = new_volume
                    voice.source = discord.PCMVolumeTransformer(voice.source, volume=new_volume)
        except AttributeError:
            pass

        await ctx.reply(tg(guild_id, f'Haha get ear raped >>> effect can only be turned off by `/disconnect`'), ephemeral=True)
    else:
        await ctx.reply(tg(guild_id, f'Ear Rape can only be activated if the bot is in a voice channel'), ephemeral=True)

    save_json()

async def kys_def(ctx: commands.Context):
    log(ctx, 'kys_def', [], log_type='function', author=ctx.author)
    guild_id = ctx.guild.id
    await ctx.reply(tg(guild_id, "Committing seppuku..."))
    sys.exit(3)

async def file_command_def(ctx: commands.Context, config_file: discord.Attachment = None, config_type: Literal[
    'guilds', 'other', 'radio', 'languages', 'log', 'data', 'activity', 'apache_activity', 'apache_error'] = 'log'):
    log(ctx, 'config_command_def', [config_file, config_type], log_type='function', author=ctx.author)

    config_types = {
        'guilds': '.json',
        'other': '.json',
        'radio': '.json',
        'languages': '.json',
        'saves': '.json',
        'log': '.log',
        'data': '.log',
        'activity': '.log',
        'apache_activity': '.log',
        'apache_error': '.log'
    }

    if config_type in ['guilds', 'other', 'languages', 'radio', 'saves']:
        file_path = f'{config.PARENT_DIR}db/{config_type}{config_types[config_type]}'
    else:
        file_path = f'{config.PARENT_DIR}log/{config_type}{config_types[config_type]}'

    if config_file is None:
        if not path.exists(file_path):
            message = f'File `{config_type}{config_types[config_type]}` does not exist'
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

        file_to_send = discord.File(file_path, filename=f"{config_type}{config_types[config_type]}")
        await ctx.reply(file=file_to_send)
        return ReturnData(True, f"Sent file: `{config_type}{config_types[config_type]}`")

    filename = config_file.filename
    file_name_list = filename.split('.')
    filename_type = '.' + file_name_list[-1]
    file_name_list.pop(-1)
    filename_name = '.'.join(file_name_list)

    if not filename_type in config_types.values():
        message = 'You need to upload a `.json` or `.log` file'
        await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    if not filename_name in config_types.keys():
        message = 'You need to upload a file with a valid name (guilds, other, radio, languages, saves, log, data, activity, apache_activity, apache_error)'
        await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    if filename_name in config_types.keys() and filename_name != config_type:
        config_type = filename_name

    # read file
    content = await config_file.read()
    if not content:
        message = f"no content in file: `{file_path}`"
        await ctx.reply(message, ephemeral=True)
        return ReturnData(False, message)

    # get original content
    with open(file_path, 'rb', encoding='utf-8') as f:
        org_content = f.read()

    if config_type == 'guilds':
        try:
            json_to_guilds(json.loads(content))
        except Exception as e:
            message = f'This file might be outdated or corrupted: `{config_type}{config_types[config_type]}` -> {e}'
            log(ctx, message, [config_type, config_types[config_type]], log_type='error', author=ctx.author)
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

    with open(file_path, 'wb', encoding='utf-8') as f:
        try:
            # write new content
            f.write(content)
        except Exception as e:
            # write original content back if error
            f.write(org_content)
            # send error message
            message = f"Error while saving file: {e}"
            log(ctx, message, [config_type, config_types[config_type]], log_type='error', author=ctx.author)
            await ctx.reply(message, ephemeral=True)
            return ReturnData(False, message)

    if config_type == 'guilds':
        with open('db/guilds.json', 'r', encoding='utf-8') as f:
            try:
                globals()['guild'] = json_to_guilds(json.load(f))
            except Exception as e:
                message = f'This file might be outdated or corrupted: `{config_type}{config_types[config_type]}` -> {e}'
                log(ctx, message, [config_type, config_types[config_type]], log_type='error', author=ctx.author)
                await ctx.reply(message, ephemeral=True)
                return ReturnData(False, message)

        log(None, 'Loaded guilds.json')
        await ctx.reply("Loaded new `guilds.json`", ephemeral=True)
    else:
        await ctx.reply(f"Saved new `{config_type}{config_types[config_type]}`", ephemeral=True)

async def options_def(ctx: commands.Context, server: Union[str, int, None]=None, stopped: str = None, loop: str = None, is_radio: str = None,
                      buttons: str = None, language: str = None, response_type: str = None, buffer: str = None,
                      history_length: str = None, volume: str = None, search_query: str = None, last_updated: str = None,
                      ephemeral=True):
    log(ctx, 'options_def',
        [server, stopped, loop, is_radio, buttons, language, response_type, buffer, history_length, volume, search_query, last_updated, ephemeral],
        log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)

    if not server:
        options = guild[guild_id].options

        message = f"""
        **Options:**
        stopped -> `{options.stopped}`
        loop -> `{options.loop}`
        is_radio -> `{options.is_radio}`
        buttons -> `{options.buttons}`
        language -> `{options.language}`
        response_type -> `{options.response_type}`
        buffer -> `{options.buffer}`
        history_length -> `{options.history_length}`
        volume -> `{options.volume}`
        search_query -> `{options.search_query}`
        last_updated -> `{options.last_updated}`
        """

        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(True, message)

    guilds = []

    if server == 'this':
        guilds.append(guild_id)

    elif server == 'all':
        for guild_id in guild.keys():
            guilds.append(guild_id)

    else:
        try:
            server = int(server)
        except (ValueError, TypeError):
            message = tg(guild_id, "That is not a **guild id!**")
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        if not server in guild.keys():
            message = tg(guild_id, "That guild doesn't exist or the bot is not in it")
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        guilds.append(server)

    for for_guild_id in guilds:
        options = guild[for_guild_id].options

        bool_list_t = ['True', 'true', '1']
        bool_list_f = ['False', 'false', '0']
        bool_list = bool_list_f + bool_list_t
        response_types = ['long', 'short']

        if stopped not in bool_list and stopped is not None and stopped != 'None':
            msg = f'stopped has to be: {bool_list} --> {stopped}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)
        if loop not in bool_list and loop is not None and loop != 'None':
            msg = f'loop has to be: {bool_list} --> {loop}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)
        if is_radio not in bool_list and is_radio is not None and is_radio != 'None':
            msg = f'is_radio has to be: {bool_list} --> {is_radio}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)
        if buttons not in bool_list and buttons is not None and buttons != 'None':
            msg = f'buttons has to be: {bool_list} --> {buttons}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)

        if response_type not in response_types and response_type is not None and response_type != 'None':
            msg = f'response_type has to be: {response_types} --> {response_type}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)

        if language not in languages_dict and language is not None and language != 'None':
            msg = f'language has to be: {languages_dict} --> {language}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)

        if not is_float(volume) and volume is not None and volume != 'None':
            msg = f'volume has to be a number: {volume}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)
        if not buffer.isdigit() and buffer is not None and buffer != 'None':
            msg = f'buffer has to be a number: {buffer}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)
        if not history_length.isdigit() and history_length is not None and history_length != 'None':
            msg = f'history_length has to be a number: {history_length}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)
        if not last_updated.isdigit() and last_updated is not None and last_updated != 'None':
            msg = f'last_updated has to be a number: {last_updated}'
            await ctx.reply(msg, ephemeral=ephemeral)
            return ReturnData(False, msg)

        if stopped is not None and stopped != 'None':
            options.stopped = to_bool(stopped)
        if loop is not None and loop != 'None':
            options.loop = to_bool(loop)
        if is_radio is not None and is_radio != 'None':
            options.is_radio = to_bool(is_radio)
        if buttons is not None and buttons != 'None':
            options.buttons = to_bool(buttons)


        if language is not None and language != 'None':
            options.language = language
        if search_query is not None and search_query != 'None':
            options.search_query = search_query
        if response_type is not None and response_type != 'None':
            options.response_type = response_type

        if volume is not None and volume != 'None':
            options.volume = float(int(volume) / 100)
        if buffer is not None and buffer != 'None':
            options.buffer = int(buffer)
        if history_length is not None and history_length != 'None':
            options.history_length = int(history_length)
        if last_updated is not None and last_updated != 'None':
            options.last_updated = int(last_updated)

        save_json()

    message = tg(guild_id, f'Edited options successfully!')
    await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(True, message)

# -------------------------------------- CHAT EXPORT -------------------------------------

async def save_channel_info_to_file(guild_id: int, file_path) -> ReturnData:
    """
    Saves all channels of a guild to a json file
    :param guild_id: ID of the guild
    :param file_path: Path of the resulting json file
    :return: ReturnData
    """
    log(None, 'save_channel_info_to_file', [guild_id], log_type='function')

    guild_object = bot.get_guild(guild_id)
    if not guild_object:
        return ReturnData(False, f'Guild ({guild_id}) not found')

    channels = guild_object.text_channels
    channels_dict = {}
    for channel in channels:
        channels_dict[int(channel.id)] = DiscordChannel(channel.id, no_members=True).__dict__

    file_path_rel = f'{file_path}/channels.json'
    makedirs(path.dirname(file_path_rel), exist_ok=True)

    with open(file_path_rel, 'w', encoding='utf-8') as f:
        f.write(json.dumps(channels_dict, indent=4))

    return ReturnData(True, f'Saved channels of ({guild_id}) to file')

async def download_guild_channel(ctx, channel_id: int, mute_response: bool=False, ephemeral: bool=True):
    log(ctx, 'download_guild_channel', [channel_id, mute_response, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)
    try:
        channel_id = int(channel_id)
    except (ValueError, TypeError):
        message = f'({channel_id}) ' + tg(ctx_guild_id, 'is not an id')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    channel_object = bot.get_channel(channel_id)
    if not channel_object:
        message = f'Channel ({channel_id}) is not accessible'
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    guild_id = channel_object.guild.id
    response = await save_channel_info_to_file(guild_id, f'{config.PARENT_DIR}db/guilds/{guild_id}')
    if not response.response:
        message = tg(ctx_guild_id, f'Error while saving channel info to file') + ': {response.message}'
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    rel_path = f'{config.PARENT_DIR}dce/DiscordChatExporter.Cli.dll'
    output_file_path = f'{config.PARENT_DIR}db/guilds/%g/%c/file.html'
    command = f'dotnet "{rel_path}" export -c {channel_id} -t {config.BOT_TOKEN} -o "{output_file_path}" -p 1mb --dateformat "dd/MM/yyyy HH:mm:ss"'

    log(ctx, f'download_guild_channel -> executing command: {command}')
    msg = f'Guild channel ({channel_id}) will be downloaded'
    org_msg = await ctx.reply(msg, ephemeral=ephemeral)

    try:
        asyncio.run_coroutine_threadsafe(execute(command), bot.loop)
        # for path_output in execute(command):
        #     print(path_output)
    except subprocess.CalledProcessError as e:
        message = tg(ctx_guild_id, f'Command raised an error') + ": " + str(e)
        if not mute_response and is_ctx:
            await org_msg.edit(content=message)
        return ReturnData(False, message)

    return ReturnData(True, msg)

async def download_guild(ctx, guild_id: int, mute_response: bool=False, ephemeral: bool=True):
    log(ctx, 'download_guild', [guild_id, mute_response, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)
    try:
        guild_id = int(guild_id)
    except (ValueError, TypeError):
        message = f'({guild_id}) ' + tg(ctx_guild_id, 'is not an id')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    guild_object = bot.get_guild(guild_id)
    if not guild_object:
        message = f'Guild ({guild_id}) ' + tg(ctx_guild_id, 'is not accessible')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    guild_id = guild_object.id
    response = await save_channel_info_to_file(guild_id, f'{config.PARENT_DIR}db/guilds/{guild_id}')
    if not response.response:
        message = tg(ctx_guild_id, f'Error while saving channel info to file') + ":" + response.message
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    rel_path = f'{config.PARENT_DIR}dce/DiscordChatExporter.Cli.dll'
    output_file_path = f'{config.PARENT_DIR}db/guilds/%g/%c/file.html'
    command = f'dotnet "{rel_path}" exportguild -g {guild_id} -t {config.BOT_TOKEN} -o "{output_file_path}" -p 1mb --dateformat "dd/MM/yyyy HH:mm:ss"'

    log(ctx, f'download_guild_channel -> executing command: {command}')
    msg = f'Guild ({guild_id}) will be downloaded (can take more than 1min depending on the size)'
    org_msg = await ctx.reply(msg, ephemeral=ephemeral)

    try:
        asyncio.run_coroutine_threadsafe(execute(command), bot.loop)
        # for path_output in execute(command):
        #     print(path_output)
    except subprocess.CalledProcessError as e:
        log(ctx, f'download_guild_channel -> error: {e}')
        message = tg(ctx_guild_id, f'Command raised an error')
        if not mute_response and is_ctx:
            await org_msg.edit(content=message)
        return ReturnData(False, message)

    return ReturnData(True, msg)

async def get_guild_channel(ctx, channel_id: int, mute_response: bool=False, guild_id=None, ephemeral: bool=True):
    log(ctx, 'get_guild_channel', [channel_id, mute_response, guild_id, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)

    try:
        channel_id = int(channel_id)
    except (ValueError, TypeError):
        message = f'({channel_id}) ' + tg(ctx_guild_id, 'is not an id')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    if is_ctx:
        if not ctx.interaction.response.is_done():
            await ctx.defer(ephemeral=ephemeral)

    channel_object = bot.get_channel(channel_id)
    channel_name = guild_id
    if channel_object:
        guild_id = channel_object.guild.id
        channel_name = channel_object.name

    path_of_folder = f'{config.PARENT_DIR}db/guilds/{guild_id}/{channel_id}'

    if not path.exists(path_of_folder):
        message = f'Channel ({channel_id}) has not been downloaded'
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    try:
        files_in_folder = listdir(path_of_folder)

        files_to_send = []
        for file_name in files_in_folder:
            files_to_send.append(discord.File(f'{path_of_folder}/{file_name}'))
    except (FileNotFoundError, PermissionError) as e:
        message = f'Channel ({channel_id}) has not yet been downloaded or an error occurred: {e}'
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    await ctx.reply(files=files_to_send, content=f'Channel: {channel_name}', ephemeral=ephemeral)
    return ReturnData(True, 'files sent')

async def get_guild(ctx, guild_id: int, mute_response: bool=False, ephemeral: bool=True):
    log(ctx, 'get_guild', [guild_id, mute_response, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)
    try:
        guild_id = int(guild_id)
    except (ValueError, TypeError):
        message = f'({guild_id}) ' + tg(ctx_guild_id, 'is not an id')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    if is_ctx:
        if not ctx.interaction.response.is_done():
            await ctx.defer(ephemeral=ephemeral)

    path_of_folder = f'{config.PARENT_DIR}db/guilds/{guild_id}'

    if not path.exists(path_of_folder):
        message = f'Guild ({guild_id}) has not been downloaded'
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    try:
        channels_in_folder = listdir(path_of_folder)
        for channel in channels_in_folder:
            await get_guild_channel(ctx, channel_id=int(channel), mute_response=mute_response, ephemeral=ephemeral, guild_id=guild_id)
    except (FileNotFoundError, PermissionError) as e:
        message = f'Guild ({guild_id}) has not yet been downloaded or an error occurred: {e}'
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    return ReturnData(True, 'files sent')

# ---------------------------------- QUEUE IMPORT/EXPORT ----------------------------------

async def export_queue(ctx, guild_id: int=None, ephemeral: bool=False):
    log(ctx, 'export_queue', [guild_id, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)

    if not guild_id:
        if is_ctx:
            guild_id = ctx.guild.id
        else:
            guild_id = ctx.guild_id

    try:
        guild_id = int(guild_id)
    except (ValueError, TypeError):
        message = f'({guild_id}) ' + tg(ctx_guild_id, 'is not an id')
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    try:
        queue_dict = guild[guild_id].queue
    except Exception as e:
        message = f"Error: {e}"
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    if not queue_dict:
        message = tg(ctx_guild_id, f"Queue is empty")
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    queue_list = []
    for item in queue_dict:
        if item.class_type == 'Video':
            data = extract_yt_id(item.url)
        elif item.class_type == 'Radio':
            data = item.radio_info['name']
        elif item.class_type == 'Local':
            data = item.local_number
        elif item.class_type == 'Probe':
            data = item.url
        elif item.class_type == 'SoundCloud':
            data = item.url
        else:
            data = item.url

        queue_list.append(f'{item.class_type}:{data}')

    queue_string = ','.join(queue_list)

    try:
        # data = queue_to_json(queue_dict)
        # await ctx.reply(file=discord.File(str(data), filename=f'queue_{guild_id}.json'), ephemeral=ephemeral)
        await ctx.reply(f"Queue String: `{queue_string}`", ephemeral=ephemeral)

        return ReturnData(True, queue_string)
    except Exception as e:
        message = f"Error: {e}"
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

async def import_queue(ctx, queue_data, guild_id: int=None, ephemeral: bool=False):
    log(ctx, 'import_queue', [queue_data, guild_id, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)

    if type(queue_data) == discord.Attachment:
        queue_data = queue_data.read()

    if not guild_id:
        if is_ctx:
            guild_id = ctx.guild.id
        else:
            guild_id = ctx.guild_id

    try:
        guild_id = int(guild_id)
    except (ValueError, TypeError):
        message = f'({guild_id}) ' + tg(ctx_guild_id, 'is not an id')
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    queue_list = []
    for item in queue_data.split(','):
        item = item.split(':')
        if item[0] == 'Video':
            video = VideoClass('Video', author_id, item[1])
        elif item[0] == 'Radio':
            video = VideoClass('Radio', author_id, radio_info=dict(name=item[1]))
        elif item[0] == 'Local':
            video = VideoClass('Local', author_id, local_number=item[1])
        elif item[0] == 'Probe':
            video = VideoClass('Probe', author_id, url=item[1])
        elif item[0] == 'SoundCloud':
            video = VideoClass('SoundCloud', author_id, url=item[1])
        else:
            message = f"Error: {item[0]} is not a valid class type"
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

        video.renew()
        queue_list.append(video)

    guild[guild_id].queue += queue_list
    push_update(guild_id)

    message = f"Added to queue: `{len(queue_list)}` items"
    await ctx.reply(message, ephemeral=ephemeral)

    return ReturnData(True, message)

# --------------------------------------- VIDEO TIME --------------------------------------

async def set_video_time(ctx, time_stamp: int, mute_response: bool=False, ephemeral: bool=False):
    log(ctx, 'set_video_time', [time_stamp, mute_response, ephemeral], log_type='function')
    is_ctx, ctx_guild_id, author_id, ctx_guild_object = ctx_check(ctx)
    try:
        time_stamp = int(time_stamp)
    except (ValueError, TypeError):
        try:
            time_stamp = int(float(time_stamp))
        except (ValueError, TypeError):
            message = f'({time_stamp}) ' + tg(ctx_guild_id, 'is not an int')
            if not mute_response:
                await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(False, message)

    voice = ctx_guild_object.voice_client
    if not voice:
        message = tg(ctx_guild_id, f'Bot is not in a voice channel')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    # if not voice.is_playing():
    #     message = f'Bot is not playing anything'
    #     if not mute_response:
    #         await ctx.reply(message, ephemeral=ephemeral)
    #     return ReturnData(False, message)

    now_playing_video = guild[ctx_guild_id].now_playing
    if not now_playing_video:
        message = tg(ctx_guild_id, f'Bot is not playing anything')
        if not mute_response:
            await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    url = now_playing_video.stream_url
    if not url:
        url = now_playing_video.url

    new_source, new_chapters = await GetSource.create_source(ctx_guild_id, url, time_stamp=time_stamp, video_class=now_playing_video, source_type=now_playing_video.class_type)

    voice.source = new_source
    set_new_time(now_playing_video, time_stamp)

    message = tg(ctx_guild_id, f'Video time set to') + ": " +str(time_stamp)
    if not mute_response:
        await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(True, message)

# --------------------------------------------- HELP COMMAND -----------------------------------------------------------

bot.remove_command('help')

@bot.hybrid_command(name='help', with_app_command=True, description='Shows all available commands',
                    help='Shows all available commands')
@app_commands.describe(general='General commands', player='Player commands', queue='Queue commands',
                       voice='Voice commands')
async def help_command(ctx: commands.Context,
                       general: Literal['help', 'ping', 'language', 'sound_effects', 'list_radios'] = None,
                       player: Literal['play', 'radio', 'ps', 'skip', 'nowplaying', 'last', 'loop', 'loop_this'] = None,
                       queue: Literal['queue', 'queue_import', 'queue_export', 'remove', 'clear', 'shuffle', 'show', 'search'] = None,
                       voice: Literal['stop', 'pause', 'resume', 'join', 'disconnect', 'volume'] = None
                       ):
    log(ctx, 'help', [general, player, queue, voice], log_type='command', author=ctx.author)
    gi = ctx.guild.id

    if general:
        command = general
    elif player:
        command = player
    elif queue:
        command = queue
    elif voice:
        command = voice
    else:
        command = None

    embed = discord.Embed(title="Help",
                          description=f"Use `/help <command>` to get help on a command | Prefix: `{prefix}`")
    embed.add_field(name="General", value=f"`/help` - {tg(gi, 'help')}\n"
                                          f"`/ping` - {tg(gi, 'ping')}\n"
                                          f"`/language` - {tg(gi, 'language')}\n"
                                          f"`/sound_ effects` - {tg(gi, 'sound')}\n"
                                          f"`/list_radios` - {tg(gi, 'list_radios')}\n"
                                          f"`/key` - {tg(gi, 'key')}\n"
                    , inline=False)
    embed.add_field(name="Player", value=f"`/play` - {tg(gi, 'play')}\n"
                                         f"`/radio` - {tg(gi, 'radio')}\n"
                                         f"`/ps` - {tg(gi, 'ps')}\n"
                                         f"`/skip` - {tg(gi, 'skip')}\n"
                                         f"`/nowplaying` - {tg(gi, 'nowplaying')}\n"
                                         f"`/last` - {tg(gi, 'last')}\n"
                                         f"`/loop` - {tg(gi, 'loop')}\n"
                                         f"`/loop_this` - {tg(gi, 'loop_this')}\n"
                    , inline=False)
    embed.add_field(name="Queue", value=f"`/queue` - {tg(gi, 'queue_add')}\n"
                                        f"`/queue_import` - {tg(gi, 'queue_import')}\n"
                                        f"`/queue_export` - {tg(gi, 'queue_export')}\n"
                                        f"`/remove` - {tg(gi, 'queue_remove')}\n"
                                        f"`/clear` - {tg(gi, 'clear')}\n"
                                        f"`/shuffle` - {tg(gi, 'shuffle')}\n"
                                        f"`/show` - {tg(gi, 'queue_show')}\n"
                                        f"`/search` - {tg(gi, 'search')}"
                    , inline=False)
    embed.add_field(name="Voice", value=f"`/stop` - {tg(gi, 'stop')}\n"
                                        f"`/pause` - {tg(gi, 'pause')}\n"
                                        f"`/resume` - {tg(gi, 'resume')}\n"
                                        f"`/join` - {tg(gi, 'join')}\n"
                                        f"`/disconnect` - {tg(gi, 'die')}\n"
                                        f"`/volume` - {tg(gi, 'volume')}"
                    , inline=False)
    embed.add_field(name="Context Menu", value=f"`Add to queue` - {tg(gi, 'queue_add')}\n"
                                               f"`Show Profile` - {tg(gi, 'profile')}\n"
                                               f"`Play now` - {tg(gi, 'play')}")

    embed.add_field(name="Admin Commands (only for bot owner)", value=f"`/zz_announce` - \n"
                                                                      f"`/zz_rape` - \n"
                                                                      f"`/zz_rape_play` - \n"
                                                                      f"`/zz_kys` - \n"
                                                                      f"`/zz_config` - \n"
                                                                      f"`/zz_log` - \n"
                                                                      f"`/zz_change_config` - \n"
                    , inline=False)

    if command == 'help':
        embed = discord.Embed(title="Help", description=f"`/help` - {tg(gi, 'help')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`general` - {tg(gi, 'The commands from')} General\n"
                                                             f"`player` - {tg(gi, 'The commands from')} Player\n"
                                                             f"`queue` - {tg(gi, 'The commands from')} Queue\n"
                                                             f"`voice` - {tg(gi, 'The commands from')} Voice"
                        , inline=False)

    elif command == 'ping':
        embed = discord.Embed(title="Help", description=f"`/ping` - {tg(gi, 'ping')}")

    elif command == 'language':
        embed = discord.Embed(title="Help", description=f"`/language` - {tg(gi, 'language')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`country_code` - {tg(gi, 'country_code')}", inline=False)

    elif command == 'sound_effects':
        embed = discord.Embed(title="Help", description=f"`/sound_effects` - {tg(gi, 'sound')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'list_radios':
        embed = discord.Embed(title="Help", description=f"`/list_radios` - {tg(gi, 'list_radios')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'key':
        embed = discord.Embed(title="Help", description=f"`/key` - {tg(gi, 'key')}")

    elif command == 'play':
        embed = discord.Embed(title="Help", description=f"`/play` - {tg(gi, 'play')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`url` - {tg(gi, 'url')}", inline=False)
        embed.add_field(name="", value=f"`force` - {tg(gi, 'force')}", inline=False)

    elif command == 'radio':
        embed = discord.Embed(title="Help", description=f"`/radio` - {tg(gi, 'radio')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`favourite_radio` - {tg(gi, 'favourite_radio')}",
                        inline=False)
        embed.add_field(name="", value=f"`radio_code` - {tg(gi, 'radio_code')}", inline=False)

    elif command == 'ps':
        embed = discord.Embed(title="Help", description=f"`/ps` - {tg(gi, 'ps')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`effect_number` - {tg(gi, 'effects_number')}",
                        inline=False)

    elif command == 'skip':
        embed = discord.Embed(title="Help", description=f"`/skip` - {tg(gi, 'skip')}")

    elif command == 'nowplaying':
        embed = discord.Embed(title="Help", description=f"`/nowplaying` - {tg(gi, 'nowplaying')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'last':
        embed = discord.Embed(title="Help", description=f"`/last` - {tg(gi, 'last')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'loop':
        embed = discord.Embed(title="Help", description=f"`/loop` - {tg(gi, 'loop')}")

    elif command == 'loop_this':
        embed = discord.Embed(title="Help", description=f"`/loop_this` - {tg(gi, 'loop_this')}")

    elif command == 'queue':
        embed = discord.Embed(title="Help", description=f"`/queue` - {tg(gi, 'queue_add')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`url` - {tg(gi, 'url')}", inline=False)
        embed.add_field(name="", value=f"`position` - {tg(gi, 'pos')}", inline=False)
        embed.add_field(name="", value=f"`mute_response` - {tg(gi, 'mute_response')}", inline=False)
        embed.add_field(name="", value=f"`force` - {tg(gi, 'force')}", inline=False)

    elif command == 'queue_import':
        embed = discord.Embed(title="Help", description=f"`/queue_import` - {tg(gi, 'queue_import')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`queue_string` - {tg(gi, 'queue_string')}", inline=False)
        embed.add_field(name="", value=f"`guild_id` - {tg(gi, 'guild_id')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'queue_export':
        embed = discord.Embed(title="Help", description=f"`/queue_export` - {tg(gi, 'queue_export')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`guild_id` - {tg(gi, 'guild_id')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'next_up':
        embed = discord.Embed(title="Help", description=f"`/next_up` - {tg(gi, 'next_up')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`url` - {tg(gi, 'url')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'remove':
        embed = discord.Embed(title="Help", description=f"`/remove` - {tg(gi, 'remove')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`number` - {tg(gi, 'number')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'clear':
        embed = discord.Embed(title="Help", description=f"`/clear` - {tg(gi, 'clear')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'shuffle':
        embed = discord.Embed(title="Help", description=f"`/shuffle` - {tg(gi, 'shuffle')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'show':
        embed = discord.Embed(title="Help", description=f"`/show` - {tg(gi, 'show')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`display_type` - {tg(gi, 'display_type')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'search':
        embed = discord.Embed(title="Help", description=f"`/search` - {tg(gi, 'search')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`search_query` - {tg(gi, 'search_query')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    elif command == 'stop':
        embed = discord.Embed(title="Help", description=f"`/stop` - {tg(gi, 'stop')}")

    elif command == 'pause':
        embed = discord.Embed(title="Help", description=f"`/pause` - {tg(gi, 'pause')}")

    elif command == 'resume':
        embed = discord.Embed(title="Help", description=f"`/resume` - {tg(gi, 'resume')}")

    elif command == 'join':
        embed = discord.Embed(title="Help", description=f"`/join` - {tg(gi, 'join')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`channel_id` - {tg(gi, 'channel_id')}", inline=False)

    elif command == 'disconnect':
        embed = discord.Embed(title="Help", description=f"`/disconnect` - {tg(gi, 'die')}")

    elif command == 'volume':
        embed = discord.Embed(title="Help", description=f"`/volume` - {tg(gi, 'volume')}")
        embed.add_field(name=f"{tg(gi, 'Arguments')}", value=f"`volume` - {tg(gi, 'volume')}", inline=False)
        embed.add_field(name="", value=f"`user_only` - {tg(gi, 'ephemeral')}", inline=False)

    await ctx.reply(embed=embed, ephemeral=True)

# --------------------------------------------- WEB FUNCTIONS ----------------------------------------------------------

async def move_def(ctx, org_number, destination_number, ephemeral=True) -> ReturnData:
    log(ctx, 'web_move', [org_number, destination_number], log_type='function', author=ctx.author)
    is_ctx, guild_id, author_id, guild_object = ctx_check(ctx)
    queue_length = len(guild[guild_id].queue)

    if queue_length == 0:
        log(ctx, "move_def -> No songs in queue")
        message = tg(guild_id, "No songs in queue")
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    org_number = int(org_number)
    destination_number = int(destination_number)

    if queue_length - 1 >= org_number >= 0:
        if queue_length - 1 >= destination_number >= 0:
            video = guild[guild_id].queue.pop(org_number)
            guild[guild_id].queue.insert(destination_number, video)

            save_json()

            message = f"{tg(guild_id, 'Moved')} #{org_number} to #{destination_number} : {video.title}"
            await ctx.reply(message, ephemeral=ephemeral)
            return ReturnData(True, message)

        message = f'{tg(guild_id, "Destination number must be between 0 and")} {queue_length - 1}'
        log(guild_id, f"move_def -> {message}")
        await ctx.reply(message, ephemeral=ephemeral)
        return ReturnData(False, message)

    message = f'{tg(guild_id, "Original number must be between 0 and")} {queue_length - 1}'
    log(guild_id, f"move_def -> {message}")
    await ctx.reply(message, ephemeral=ephemeral)
    return ReturnData(False, message)

async def web_up(web_data, number) -> ReturnData:
    log(web_data, 'web_up', [number], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id
    queue_length = len(guild[guild_id].queue)
    number = int(number)

    if queue_length == 0:
        log(guild_id, "web_up -> No songs in queue")
        return ReturnData(False, tg(ctx_guild_id, 'No songs in queue'))

    if number == 0:
        return await move_def(web_data, 0, queue_length - 1)

    return await move_def(web_data, number, number - 1)

async def web_down(web_data, number) -> ReturnData:
    log(web_data, 'web_down', [number], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id
    queue_length = len(guild[guild_id].queue)
    number = int(number)

    if queue_length == 0:
        log(guild_id, "web_down -> No songs in queue")
        return ReturnData(False, tg(ctx_guild_id, 'No songs in queue'))

    if number == queue_length - 1:
        return await move_def(web_data, number, 0)

    return await move_def(web_data, number, number + 1)

async def web_top(web_data, number) -> ReturnData:
    log(web_data, 'web_top', [number], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id
    queue_length = len(guild[guild_id].queue)
    number = int(number)

    if queue_length == 0:
        log(guild_id, "web_top -> No songs in queue")
        return ReturnData(False, tg(ctx_guild_id, 'No songs in queue'))

    if number == 0:
        log(guild_id, "web_top -> Already at the top")
        return ReturnData(False, tg(ctx_guild_id, 'Already at the top'))

    return await move_def(web_data, number, 0)

async def web_bottom(web_data, number) -> ReturnData:
    log(web_data, 'web_bottom', [number], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id
    queue_length = len(guild[guild_id].queue)
    number = int(number)

    if queue_length == 0:
        log(guild_id, "web_bottom -> No songs in queue")
        return ReturnData(False, tg(ctx_guild_id, 'No songs in queue'))

    if number == queue_length - 1:
        log(guild_id, "web_bottom -> Already at the bottom")
        return ReturnData(False, tg(ctx_guild_id, 'Already at the bottom'))

    return await move_def(web_data, number, queue_length - 1)

async def web_duplicate(web_data, number) -> ReturnData:
    log(web_data, 'web_duplicate', [number], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id
    queue_length = len(guild[guild_id].queue)
    number = int(number)

    if queue_length == 0:
        log(guild_id, "web_duplicate -> No songs in queue")
        return ReturnData(False, tg(ctx_guild_id, 'No songs in queue'))

    video = guild[guild_id].queue[number]

    to_queue(guild_id, video, position=number+1)

    message = f'{tg(ctx_guild_id, "Duplicated")} #{number} : {video.title}'
    log(guild_id, f"web_duplicate -> {message}")
    return ReturnData(True, message)

# web queue
async def web_queue(web_data, video_type, position=None) -> ReturnData:
    log(web_data, 'web_queue', [video_type, position], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id

    if video_type == 'np':
        video = guild[guild_id].now_playing
    else:
        try:
            index = int(video_type[1:])
            video = guild[guild_id].history[index]
        except (TypeError, ValueError, IndexError):
            log(guild_id, "web_queue -> Invalid video type")
            return ReturnData(False, tg(ctx_guild_id, 'Invalid video type (Internal web error -> contact developer)'))

    if video.class_type == 'Radio':
        return await web_queue_from_radio(web_data, video.radio_info['name'], position)

    try:
        to_queue(guild_id, video, position=position)

        save_json()
        log(guild_id, f"web_queue -> Queued: {video.url}")
        return ReturnData(True, f'{tg(ctx_guild_id, "Queued")} {video.title}', video)

    except Exception as e:
        log(guild_id, f"web_queue -> Error while queuing: {e}")
        return ReturnData(False, tg(ctx_guild_id, 'Error while queuing (Internal web error -> contact developer)'))

async def web_queue_from_radio(web_data, radio_name, position=None) -> ReturnData:
    log(web_data, 'web_queue_from_radio', [radio_name, position], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)

    if radio_name in radio_dict.keys():
        video = VideoClass('Radio', web_data.author_id, radio_info=dict(name=radio_name))
        video.renew()

        if position == 'start':
            to_queue(web_data.guild_id, video, position=0, copy_video=False)
        else:
            to_queue(web_data.guild_id, video, copy_video=False)

        message = f'`{video.title}` ' + tg(ctx_guild_id, 'added to queue!')
        save_json()
        return ReturnData(True, message, video)

    else:
        message = tg(ctx_guild_id, 'Radio station') + f' `{radio_name}` ' + tg(ctx_guild_id, 'does not exist!')
        save_json()
        return ReturnData(False, message)

async def web_join(web_data, form) -> ReturnData:
    log(web_data, 'web_join', [form], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)

    if form['join_btn'] == 'id':
        channel_id = form['channel_id']
    elif form['join_btn'] == 'name':
        channel_id = form['channel_name']
    else:
        return ReturnData(False, tg(ctx_guild_id, 'Invalid channel id (Internal web error -> contact developer)'))

    try:
        channel_id = int(channel_id)
    except ValueError:
        return ReturnData(False, tg(ctx_guild_id, 'Invalid channel id') + f': {channel_id}')

    task = asyncio.run_coroutine_threadsafe(join_def(web_data, channel_id), bot.loop)

    return task.result()

async def web_disconnect(web_data) -> ReturnData:
    log(web_data, 'web_disconnect', [], log_type='function', author=web_data.author)

    task = asyncio.run_coroutine_threadsafe(disconnect_def(web_data), bot.loop)

    return task.result()

# user edit
async def web_user_options_edit(web_data, form) -> ReturnData:
    log(web_data, 'web_user_options_edit', [form], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    options = guild[web_data.guild_id].options

    loop = form['loop']
    language = form['language']
    response_type = form['response_type']
    buttons = form['buttons']
    volume = form['volume']
    buffer = form['buffer']
    history_length = form['history_length']

    bool_list_t = ['True', 'true', '1']
    bool_list_f = ['False', 'false', '0']
    bool_list = bool_list_f + bool_list_t
    response_types = ['long', 'short']

    if loop not in bool_list:
        return ReturnData(False, f'loop has to be: {bool_list} --> {loop}')
    if buttons not in bool_list:
        return ReturnData(False, f'buttons has to be: {bool_list} --> {buttons}')

    if response_type not in response_types:
        return ReturnData(False, f'response_type has to be: {response_types} --> {response_type}')

    if language not in languages_dict:
        return ReturnData(False, f'language has to be: {languages_dict}')

    if not volume.isdigit():
        return ReturnData(False, f'volume has to be a number: {volume}')
    if not buffer.isdigit():
        return ReturnData(False, f'buffer has to be a number: {buffer}')
    if not history_length.isdigit():
        return ReturnData(False, f'history_length has to be a number: {history_length}')

    options.loop = to_bool(loop)
    options.buttons = to_bool(buttons)

    options.language = language
    options.response_type = response_type

    options.volume = float(int(volume) * 0.01)
    options.buffer = int(buffer)
    options.history_length = int(history_length)

    return ReturnData(True, tg(ctx_guild_id, f'Edited options successfully!'))

# admin
async def web_video_edit(web_data, form) -> ReturnData:
    log(web_data, 'web_video_edit', [form], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    guild_id = web_data.guild_id
    index = form['edit_btn']
    is_queue = True
    is_np = False

    if index == 'np':
        is_np = True

    elif not index.isdigit():
        is_queue = False
        try:
            index = int(index[1:])
            if index < 0 or index >= len(guild[guild_id].history):
                return ReturnData(False, tg(ctx_guild_id, 'Invalid index (out of range)'))
        except (TypeError, ValueError, IndexError):
            return ReturnData(False, tg(ctx_guild_id, 'Invalid index (not a number)'))

    elif index.isdigit():
        is_queue = True
        index = int(index)
        if index < 0 or index >= len(guild[guild_id].queue):
            return ReturnData(False, tg(ctx_guild_id, 'Invalid index (out of range)'))

    else:
        return ReturnData(False, tg(ctx_guild_id, 'Invalid index (not a number)'))

    class_type = form['class_type']
    author = form['author']
    url = form['url']
    title = form['title']
    picture = form['picture']
    duration = form['duration']
    channel_name = form['channel_name']
    channel_link = form['channel_link']
    radio_info = form['radio_info']
    local_number = form['local_number']
    created_at = form['created_at']
    played_duration = form['played_duration']
    chapters = form['chapters']
    discord_channel = form['discord_channel']
    stream_url = form['stream_url']

    none_list = ['None', '']

    if author in none_list: author = None
    if url in none_list: url = None
    if title in none_list: title = None
    if picture in none_list: picture = None
    if duration in none_list: duration = None
    if channel_name in none_list: channel_name = None
    if channel_link in none_list: channel_link = None
    if radio_info in none_list: radio_info = None
    if local_number in none_list: local_number = None
    if created_at in none_list: created_at = None
    if played_duration in none_list: played_duration = None
    if chapters in none_list: chapters = None
    if discord_channel in none_list: discord_channel = None
    if stream_url in none_list: stream_url = None

    if class_type not in ['Video', 'Radio', 'Local', 'Probe', 'SoundCloud']:
        return ReturnData(False, f'Invalid class type: {class_type}')

    if created_at:
        if not created_at.isdigit():
            return ReturnData(False, f'Invalid struct time: {created_at}')
        created_at = int(created_at)

    if local_number:
        if not local_number.isdigit():
            return ReturnData(False, f'Invalid local number: {local_number}')
        local_number = int(local_number)

    if author and author.isdigit():
        author = int(author)

    if duration and duration.isdigit():
        duration = int(duration)

    if radio_info:
        try:
            radio_info = ast.literal_eval(radio_info)
            assert type(radio_info) == dict
        except (TypeError, ValueError, json.decoder.JSONDecodeError, AssertionError, SyntaxError):
            return ReturnData(False, f'Invalid radio info: {radio_info}')

    if played_duration:
        try:
            played_duration = ast.literal_eval(played_duration)
            assert type(played_duration) == list
        except (TypeError, ValueError, json.decoder.JSONDecodeError, AssertionError, SyntaxError):
            return ReturnData(False, f'Invalid played duration: {played_duration}')

    if chapters:
        try:
            chapters = ast.literal_eval(chapters)
            assert type(chapters) == list
        except (TypeError, ValueError, json.decoder.JSONDecodeError, AssertionError, SyntaxError):
            return ReturnData(False, f'Invalid chapters: {chapters}')

    if discord_channel:
        try:
            discord_channel = ast.literal_eval(discord_channel)
            assert type(discord_channel) == dict
        except (TypeError, ValueError, json.decoder.JSONDecodeError, AssertionError, SyntaxError):
            return ReturnData(False, f'Invalid discord channel: {discord_channel}')

    video = VideoClass(class_type, author, url=url, title=title, picture=picture, duration=duration, channel_name=channel_name, channel_link=channel_link, radio_info=radio_info, local_number=local_number, created_at=created_at, played_duration=played_duration, chapters=chapters, discord_channel=discord_channel, stream_url=stream_url)

    if is_np:
        guild[guild_id].now_playing = video
    else:
        if is_queue:
            guild[guild_id].queue[index] = video
        else:
            guild[guild_id].history[index] = video

    save_json()

    return ReturnData(True, tg(ctx_guild_id, 'Edited item') + f' {"h" if not is_queue else ""}{index} ' + tg(ctx_guild_id, 'successfully!'))

async def web_options_edit(web_data, form) -> ReturnData:
    log(web_data, 'web_options_edit', [form], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)

    try:
        stopped = form['stopped']
        loop = form['loop']
        is_radio = form['is_radio']
        language = form['language']
        response_type = form['response_type']
        search_query = form['search_query']
        buttons = form['buttons']
        volume = form['volume']
        buffer = form['buffer']
        history_length = form['history_length']
        last_updated = form['last_updated']
    except KeyError:
        return ReturnData(False, tg(ctx_guild_id, 'Missing form data - please contact the developer (he fucked up when doing an update)'))

    return await options_def(web_data, server='this', stopped=stopped, loop=loop, is_radio=is_radio, language=language,
                             response_type=response_type, search_query=search_query, buttons=buttons, volume=volume,
                             buffer=buffer, history_length=history_length, last_updated=last_updated)

async def web_delete_guild(web_data, guild_id) -> ReturnData:
    log(web_data, 'web_delete_guild', [guild_id], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    try:
        guild_id = int(guild_id)
    except (TypeError, ValueError):
        return ReturnData(False, tg(ctx_guild_id, 'Invalid guild id') + f': {guild_id}')

    if guild_id not in guild.keys():
        return ReturnData(False, tg(ctx_guild_id, 'Guild not found') + f': {guild_id}')

    del guild[guild_id]

    save_json()

    return ReturnData(True, tg(ctx_guild_id, 'Deleted guild') + f' {guild_id} ' + tg(ctx_guild_id, 'successfully!'))

async def web_disconnect_guild(web_data, guild_id) -> ReturnData:
    log(web_data, 'web_disconnect_guild', [guild_id], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    try:
        guild_id = int(guild_id)
    except (TypeError, ValueError):
        return ReturnData(False, tg(ctx_guild_id, 'Invalid guild id') + f': {guild_id}')

    bot_guild_ids = [guild_object.id for guild_object in bot.guilds]

    if guild_id not in bot_guild_ids:
        return ReturnData(False, tg(ctx_guild_id, 'Guild not found in bot.guilds') + f': {guild_id}')

    guild_to_disconnect = bot.get_guild(guild_id)

    try:
        await guild_to_disconnect.leave()
    except discord.HTTPException as e:
        return ReturnData(False, f"Something Failed -> HTTPException: {e}")

    save_json()

    return ReturnData(True, tg(ctx_guild_id, 'Left guild') + f' {guild_id} ' + tg(ctx_guild_id, 'successfully!'))

async def web_create_invite(web_data, guild_id):
    log(web_data, 'web_create_invite', [guild_id], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data)
    try:
        guild_object = bot.get_guild(int(guild_id))
    except (TypeError, ValueError):
        return ReturnData(False, tg(ctx_guild_id, 'Invalid guild id') + f': {guild_id}')

    if not guild_object:
        return ReturnData(False, tg(ctx_guild_id, 'Guild not found:') + f' {guild_id}')

    try:
        guild_object_invites = await guild_object.invites()
    except discord.HTTPException as e:
        return ReturnData(False, tg(ctx_guild_id, "Something Failed -> HTTPException") + f": {e}")

    if guild_object_invites:
        message = f'Guild ({guild_object.id}) invites -> {guild_object_invites}'
        log(None, message)
        await send_to_admin(message)
        return ReturnData(True, message)

    if not guild_object_invites:
        try:
            channel = guild_object.text_channels[0]
            invite = await channel.create_invite()
            message = tg(ctx_guild_id, 'Invite for guild') + f' ({guild_object.id}) -> {invite}'
            log(None, message)
            await send_to_admin(message)
            return ReturnData(True, message)
        except discord.HTTPException as e:
            return ReturnData(False, tg(ctx_guild_id, "Something Failed -> HTTPException") + f": {e}")

# ------------------------------------------------ IPC SERVER ----------------------------------------------------------

async def execute_function(request_dict) -> ReturnData:
    """
    Execute a function from a request dict
    :param request_dict: A request dict
    :type request_dict: dict
    :return: ReturnData
    """

    if request_dict['type'] != 'function':
        return ReturnData(False, f'Wrong type: {request_dict["type"]} --> Internal error (contact developer)')

    web_data = request_dict['web_data']
    func_name = request_dict['function_name']

    if request_dict['args'] is None:
        args = {}
    else:
        args = request_dict['args']

    try:

        if func_name == 'remove_def':
            return await remove_def(web_data, number=args['number'], list_type=args['list_type'])
        if func_name == 'web_up':
            return await web_up(web_data, number=args['number'])
        if func_name == 'web_down':
            return await web_down(web_data, number=args['number'])
        if func_name == 'web_top':
            return await web_top(web_data, number=args['number'])
        if func_name == 'web_bottom':
            return await web_bottom(web_data, number=args['number'])
        if func_name == 'web_duplicate':
            return await web_duplicate(web_data, number=args['number'])

        if func_name == 'play_def':
            return await play_def(web_data)
        if func_name == 'stop_def':
            return await stop_def(web_data)
        if func_name == 'pause_def':
            return await pause_def(web_data)
        if func_name == 'skip_def':
            return await skip_def(web_data)

        if func_name == 'loop_command_def':
            return await loop_command_def(web_data)
        if func_name == 'shuffle_def':
            return await shuffle_def(web_data)
        if func_name == 'clear_def':
            return await clear_def(web_data)

        if func_name == 'web_disconnect':
            return await web_disconnect(web_data)
        if func_name == 'web_join':
            return await web_join(web_data, form=args['form'])

        if func_name == 'web_queue':
            return await web_queue(web_data, video_type=args['video_type'], position=args['position'])
        if func_name == 'queue_command_def':
            return await queue_command_def(web_data, url=args['url'])
        if func_name == 'web_queue_from_radio':
            return await web_queue_from_radio(web_data, radio_name=args['radio_name'])

        if func_name == 'new_queue_save':
            return new_queue_save(web_data.guild_id, save_name=args['save_name'])
        if func_name == 'load_queue_save':
            return load_queue_save(web_data.guild_id, save_name=args['save_name'])
        if func_name == 'delete_queue_save':
            return delete_queue_save(web_data.guild_id, save_name=args['save_name'])
        if func_name == 'rename_queue_save':
            return rename_queue_save(web_data.guild_id, old_name=args['old_name'], new_name=args['new_name'])

        if func_name == 'volume_command_def':
            return await volume_command_def(web_data, volume=args['volume'])
        if func_name == 'set_video_time':
            return await set_video_time(web_data, time_stamp=args['time_stamp'])

        # user edit
        if func_name == 'web_user_options_edit':
            return await web_user_options_edit(web_data, form=args['form'])

        # admin
        if func_name == 'web_video_edit':
            return await web_video_edit(web_data, form=args['form'])
        if func_name == 'web_options_edit':
            return await web_options_edit(web_data, form=args['form'])

        if func_name == 'web_delete_guild':
            return await web_delete_guild(web_data, guild_id=args['guild_id'])
        if func_name == 'web_disconnect_guild':
            return asyncio.run_coroutine_threadsafe(web_disconnect_guild(web_data, args['guild_id']), bot.loop).result()
            # return await web_disconnect_guild(web_data, guild_id=args['guild_id'])
        if func_name == 'web_create_invite':
            return asyncio.run_coroutine_threadsafe(web_create_invite(web_data, args['guild_id']), bot.loop).result()
            # return await web_create_invite(web_data, guild_id=args['guild_id'])

        if func_name == 'download_guild':
            guild_id = args['guild_id']
            return await download_guild(web_data, guild_id)
        if func_name == 'download_guild_channel':
            channel_id = args['channel_id']
            return await download_guild_channel(web_data, channel_id)

        if func_name == 'export_queue':
            guild_id = args['guild_id']
            return await export_queue(web_data, guild_id)
        if func_name == 'import_queue':
            guild_id = args['guild_id']
            queue_data = args['queue_data']
            return await import_queue(web_data, queue_data, guild_id)

    except KeyError as e:
        return ReturnData(False, f'Wrong args for ({func_name}): {e} --> Internal error (contact developer)')

    return ReturnData(False, f'Unknown function: {func_name}')

async def execute_get_data(request_dict):
    data_type = request_dict['data_type']

    if data_type == 'guilds':
        return guild
    elif data_type == 'guild':
        guild_id = request_dict['guild_id']
        try:
            return guild[guild_id]
        except KeyError:
            return None
    elif data_type == 'guild_channels':
        guild_id = request_dict['guild_id']
        guild_channels = []
        guild_object = bot.get_guild(guild_id)
        if not guild_object:
            return None
        for channel in guild_object.voice_channels:
            guild_channels.append(DiscordChannel(channel.id))
        return guild_channels
    elif data_type == 'guild_text_channels':
        guild_id = request_dict['guild_id']
        guild_channels = []
        guild_object = bot.get_guild(guild_id)
        if not guild_object:
            return None
        for channel in guild_object.text_channels:
            guild_channels.append(DiscordChannel(channel.id))
        return guild_channels
    elif data_type == 'guild_members':
        guild_id = request_dict['guild_id']
        guild_users = []
        guild_object = bot.get_guild(guild_id)
        if not guild_object:
            return None
        for member in guild_object.members:
            guild_users.append(DiscordMember(member))
        return guild_users
    elif data_type == 'guild_roles':
        guild_id = request_dict['guild_id']
        guild_roles = []
        guild_object = bot.get_guild(guild_id)
        if not guild_object:
            return None
        for role in guild_object.roles:
            guild_roles.append(DiscordRole(role_id=role.id, guild_id=guild_id))
        return guild_roles
    elif data_type == 'guild_invites':
        guild_id = request_dict['guild_id']
        guild_invites = []
        guild_object = bot.get_guild(guild_id)
        if not guild_object:
            return None

        invites = asyncio.run_coroutine_threadsafe(guild_object.invites(), bot.loop).result()
        if not invites:
            return None

        for invite in invites:
            guild_invites.append(DiscordInvite(invite))

        return guild_invites

    elif data_type == 'channel_transcript':
        channel_id = request_dict['channel_id']
        channel_object = DiscordChannel(channel_id)
        return await channel_object.get_first_messages(100)

    elif data_type == 'user_name':
        user_id = request_dict['user_id']
        return get_username(user_id)
    elif data_type == 'user_data':
        user_id = request_dict['user_id']
        return DiscordUser(user_id)

    elif data_type == 'language':
        guild_id = request_dict['guild_id']
        try:
            return guild[guild_id].options.language
        except KeyError:
            return None
    elif data_type == 'update':
        guild_id = request_dict['guild_id']
        try:
            return str(guild[guild_id].options.last_updated)
        except KeyError:
            return None
    if data_type == 'renew':
        queue_type = request_dict['queue_type']
        index = request_dict['index']
        guild_id = request_dict['guild_id']

        if queue_type == 'now_playing':
            guild[guild_id].now_playing.renew()
        elif queue_type == 'queue':
            try:
                guild[guild_id].queue[index].renew()
            except IndexError:
                pass
    elif data_type == 'bot_guilds':
        update_guilds()
        bot_guilds = []
        for bot_guild in bot.guilds:
            to_append = GuildData(bot_guild.id)
            bot_guilds.append(to_append)
        return bot_guilds
    else:
        print(f'Unknown data type: {data_type}', file=sys.stderr)

# handle client
async def handle_client(client):
    request_data = await recv_msg(client)
    request_dict = pickle.loads(request_data)

    request_type = request_dict['type']

    if request_type == 'get_data':
        response = await execute_get_data(request_dict)
    elif request_type == 'function':
        response = await execute_function(request_dict)
    else:
        response = ReturnData(False, 'idk')

    if response:
        # serialize response
        serialized_response = pickle.dumps(response)
        await send_msg(client, serialized_response)

    client.close()

async def run_server():
    # IPC parameters
    HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
    PORT = 5421  # Port to listen on (non-privileged ports are > 1023)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(8)
    server.setblocking(False)

    log(None, f'IPC server is running on {HOST}:{PORT}')

    loop = asyncio.get_event_loop()

    ipc = True
    while ipc:
        client, _ = await loop.sock_accept(server)
        loop.create_task(handle_client(client))

def ipc_run():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(run_server())
    loop.close()

# --------------------------------------------------- APP --------------------------------------------------------------

def application():
    web_thread = threading.Thread(target=ipc_run)
    bot_thread = threading.Thread(target=bot.run, kwargs={'token': config.BOT_TOKEN})

    web_thread.start()
    bot_thread.start()

    web_thread.join()
    bot_thread.join()

if __name__ == '__main__':
    application()
