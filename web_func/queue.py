from utils.global_vars import GlobalVars

from classes.video_class import Queue
from classes.data_classes import ReturnData

from utils.log import log
from utils.translate import tg
from utils.save import save_json
from utils.discord import to_queue
from utils.global_vars import radio_dict
from database.guild import guild

from commands.utils import ctx_check

async def web_queue(web_data, glob: GlobalVars, video_type, position=None) -> ReturnData:
    log(web_data, 'web_queue', [video_type, position], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data, glob)
    guild_id = web_data.guild_id
    db_guild = guild(glob, guild_id)

    if video_type == 'np':
        video = db_guild.now_playing
    else:
        try:
            index = int(video_type[1:])
            video = db_guild.history[index]
        except (TypeError, ValueError, IndexError):
            log(guild_id, "web_queue -> Invalid video type")
            return ReturnData(False, tg(ctx_guild_id, 'Invalid video type (Internal web error -> contact developer)'))

    if video.class_type == 'Radio':
        return await web_queue_from_radio(web_data, glob, video.radio_info['name'], position)

    try:
        to_queue(glob, guild_id, video, position=position)

        save_json(glob)
        log(guild_id, f"web_queue -> Queued: {video.url}")
        return ReturnData(True, f'{tg(ctx_guild_id, "Queued")} {video.title}', video)

    except Exception as e:
        log(guild_id, f"web_queue -> Error while queuing: {e}")
        return ReturnData(False, tg(ctx_guild_id, 'Error while queuing (Internal web error -> contact developer)'))

async def web_queue_from_radio(web_data, glob: GlobalVars, radio_name=None, position=None) -> ReturnData:
    log(web_data, 'web_queue_from_radio', [radio_name, position], log_type='function', author=web_data.author)
    is_ctx, ctx_guild_id, ctx_author_id, ctx_guild_object = ctx_check(web_data, glob)

    if radio_name in radio_dict.keys():
        video = Queue(glob, 'Radio', web_data.author_id, ctx_guild_id, radio_info=dict(name=radio_name))

        if position == 'start':
            to_queue(glob, web_data.guild_id, video, position=0, copy_video=False)
        else:
            to_queue(glob, web_data.guild_id, video, copy_video=False)

        message = f'`{video.title}` ' + tg(ctx_guild_id, 'added to queue!')
        save_json(glob)
        return ReturnData(True, message, video)

    else:
        message = tg(ctx_guild_id, 'Radio station') + f' `{radio_name}` ' + tg(ctx_guild_id, 'does not exist!')
        save_json(glob)
        return ReturnData(False, message)
