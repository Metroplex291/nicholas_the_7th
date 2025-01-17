from utils.global_vars import GlobalVars

from classes.data_classes import ReturnData

from utils.log import log
from utils.translate import tg

import commands.voice
from commands.utils import ctx_check

import asyncio

async def web_join(web_data, glob: GlobalVars, form) -> ReturnData:
    log(web_data, 'web_join', [form], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data, glob)

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

    task = asyncio.run_coroutine_threadsafe(commands.voice.join_def(web_data, glob, channel_id), glob.bot.loop)

    return task.result()

async def web_disconnect(web_data, glob: GlobalVars) -> ReturnData:
    log(web_data, 'web_disconnect', [], log_type='function', author=web_data.author)

    task = asyncio.run_coroutine_threadsafe(commands.voice.disconnect_def(web_data, glob), glob.bot.loop)

    return task.result()
