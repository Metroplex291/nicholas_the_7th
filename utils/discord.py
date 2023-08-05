from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from classes.video_class import VideoClass
    from classes.data_classes import ReturnData

from utils.convert import struct_to_time
from utils.translate import tg
from utils.globals import get_bot, get_guild_dict
from utils.video_time import set_stopped
from utils.save import save_json, push_update

import discord
import copy
from time import time

from config import WEB_URL


def get_voice_client(iterable, **attrs) -> discord.VoiceClient:
    """
    Gets voice_client from voice_clients list
    :param iterable: list
    :return: discord.VoiceClient
    """
    from operator import attrgetter

    # noinspection PyShadowingNames
    def _get(iterable, /, **attrs):
        # global -> local
        _all = all
        attrget = attrgetter

        # Special case the single element call
        if len(attrs) == 1:
            k, v = attrs.popitem()
            pred = attrget(k.replace('__', '.'))
            return next((elem for elem in iterable if pred(elem) == v), None)

        converted = [(attrget(attr.replace('__', '.')), value) for attr, value in attrs.items()]
        for elem in iterable:
            if _all(pred(elem) == value for pred, value in converted):
                return elem
        return None

    # noinspection PyShadowingNames
    async def _aget(iterable, /, **attrs):
        # global -> local
        _all = all
        attrget = attrgetter

        # Special case the single element call
        if len(attrs) == 1:
            k, v = attrs.popitem()
            pred = attrget(k.replace('__', '.'))
            async for elem in iterable:
                if pred(elem) == v:
                    return elem
            return None

        converted = [(attrget(attr.replace('__', '.')), value) for attr, value in attrs.items()]

        async for elem in iterable:
            if _all(pred(elem) == value for pred, value in converted):
                return elem
        return None


    return (
        _aget(iterable, **attrs)  # type: ignore
        if hasattr(iterable, '__aiter__')  # isinstance(iterable, collections.abc.AsyncIterable) is too slow
        else _get(iterable, **attrs)  # type: ignore
    )

def create_embed(video: VideoClass, name: str, guild_id: int, embed_colour: (int, int, int) = (88, 101, 242)) -> discord.Embed:
    """
    Creates embed with video info
    :param video: VideoClass
    :param name: str - title of embed
    :param guild_id: id of guild the embed is created for
    :param embed_colour: (int, int, int) - rgb colour of embed default: (88, 101, 242) -> #5865F2 == discord.Color.blurple()
    :return: discord.Embed
    """
    try:
        bot = get_bot()
        requested_by = bot.get_user(video.author).mention
    except AttributeError:
        requested_by = video.author
    # set variables
    title = video.title
    time_played = video.time()
    author = f'[{video.channel_name}]({video.channel_link})'
    current_chapter = video.current_chapter()
    url = video.url
    thumbnail = video.picture

    if video.radio_info is not None and 'picture' in video.radio_info.keys():
        title = video.radio_info["title"]
        author = f'[{video.radio_info["channel_name"]}]({video.channel_link})'
        thumbnail = video.radio_info["picture"]

    started_at = struct_to_time(video.played_duration[0]["start"]["epoch"], "time")
    requested_at = struct_to_time(video.created_at, "time")

    # Create embed
    embed = (discord.Embed(title=name, description=f'```\n{title}\n```', color=discord.Color.from_rgb(*embed_colour)))

    embed.add_field(name=tg(guild_id, 'Duration'), value=time_played)
    embed.add_field(name=tg(guild_id, 'Requested by'), value=requested_by)
    embed.add_field(name=tg(guild_id, 'Author'), value=author)

    if current_chapter is not None:
        embed.add_field(name=tg(guild_id, 'Chapter'), value=current_chapter)

    embed.add_field(name=tg(guild_id, 'URL'), value=url, inline=False)

    embed.set_thumbnail(url=thumbnail)
    embed.set_footer(text=f'{tg(guild_id, "Requested at")} {requested_at} | {tg(guild_id, "Started playing at")} {started_at}')

    return embed

def now_to_history(guild_id: int):
    """
    Adds now_playing to history
    Removes first element of history if history length is more than options.history_length

    :param guild_id: int - id of guild
    :return: None
    """
    guild = get_guild_dict()

    if guild[guild_id].now_playing is not None:
        # trim history
        if len(guild[guild_id].history) >= guild[guild_id].options.history_length:
            while len(guild[guild_id].history) >= guild[guild_id].options.history_length:
                guild[guild_id].history.pop(0)

        video = guild[guild_id].now_playing

        # if loop is enabled and video is Radio class, add video to queue
        if guild[guild_id].options.loop:
            to_queue(guild_id, video, position=None, copy_video=True)

        # set now_playing to None
        guild[guild_id].now_playing = None

        # strip not needed data
        set_stopped(video)
        video.chapters = None

        # add video to history
        guild[guild_id].history.append(video)

        # save json and push update
        save_json()
        push_update(guild_id)

def to_queue(guild_id: int, video: VideoClass, position: int = None, copy_video: bool=True) -> ReturnData or None:
    """
    Adds video to queue

    if return_message is True returns: [bool, str, VideoClass]

    :param guild_id: id of guild: int
    :param video: VideoClass
    :param position: int - position in queue to add video
    :param copy_video: bool - if True copies video
    :return: ReturnData or None
    """
    guild = get_guild_dict()

    if copy_video:
        video = copy.deepcopy(video)

    # strip video of time data
    video.played_duration = [{'start': {'epoch': None, 'time_stamp': None}, 'end': {'epoch': None, 'time_stamp': None}}]
    # strip video of discord channel data
    video.discord_channel = {"id": None, "name": None}
    # strip video of stream url
    video.stream_url = None
    # set new creation date
    video.created_at = int(time())

    if position is None:
        guild[guild_id].queue.append(video)
    else:
        guild[guild_id].queue.insert(position, video)

    push_update(guild_id)
    save_json()

    return f'[`{video.title}`](<{video.url}>) {tg(guild_id, "added to queue!")} -> [Control Panel]({WEB_URL}/guild/{guild_id}&key={guild[guild_id].data.key})'

def get_content_of_message(message: discord.Message) -> (str, list or None):
    """
    Returns content of message

    if message has attachments returns url of first attachment and list with filename, author and link of message

    if message has embeds returns str representation of first embed without thumbnail and None

    if message has embeds and content returns content of message and None

    :param message: message: discord.Message
    :return: content: str, probe_data: list or None
    """
    if message.attachments:
        url = message.attachments[0].url
        filename = message.attachments[0].filename
        message_author = f"Message by {get_username(message.author.id)}"
        message_link = message.jump_url
        probe_data = [filename, message_author, message_link]
    elif message.embeds:
        if message.content:
            url = message.content
            probe_data = None
        else:
            embed = message.embeds[0]
            embed_dict = embed.to_dict()
            embed_dict.pop('thumbnail')
            embed_str = str(embed_dict)
            url = embed_str
            probe_data = None
    else:
        url = message.content
        probe_data = None

    return url, probe_data

def get_username(user_id: int) -> str:
    """
    Returns username of user_id with bot.get_user

    if can't find user returns str(user_id)

    :param user_id: id of user
    :return: str - username of user_id or str(user_id)
    """
    bot = get_bot()
    # noinspection PyBroadException
    try:
        return bot.get_user(int(user_id)).name
    except:
        return str(user_id)