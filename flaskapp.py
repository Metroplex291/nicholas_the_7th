import json
import math
from time import time, sleep
from pathlib import Path

from flask import Flask, render_template, request, url_for, redirect, send_file, abort, Response, send_from_directory
from flask import session as flask_session
from werkzeug.utils import safe_join

from classes.data_classes import WebData
from classes.discord_classes import DiscordUser

from utils.convert import struct_to_time, convert_duration
from utils.log import log, collect_data
from utils.files import getReadableByteSize, getIconClassForFilename
from utils.translate import ftg
from utils.video_time import video_time_from_start
from utils.checks import check_isdigit
from utils.web import *

import config
from oauth import Oauth

authorized_users = config.AUTHORIZED_USERS
my_id = config.OWNER_ID
bot_id = config.CLIENT_ID
prefix = config.PREFIX
vlc_logo = config.VLC_LOGO
default_discord_avatar = config.DEFAULT_DISCORD_AVATAR
d_id = 349164237605568513

import asyncio

# -------------------------------------------- Database -------------------------------------------- #

from database.main import *
from database.guild import *

# db connect
session = connect_to_db()

# --------------------------------------------- LOAD DATA --------------------------------------------- #

with open(f'{config.PARENT_DIR}db/radio.json', 'r', encoding='utf-8') as file:
    radio_dict = json.load(file)

with open(f'{config.PARENT_DIR}db/languages.json', 'r', encoding='utf-8') as file:
    languages_dict = json.load(file)
    text = languages_dict['en']
    authorized_users += [my_id, 349164237605568513]

# --------------------------------------------- FUNCTIONS --------------------------------------------- #
def check_admin(session_data):
    if session_data is None:
        raise ValueError('Session data is None')

    user_id = int(session_data['discord_user']['id'])
    if user_id in authorized_users:
        return guild_ids()

    return session_data['mutual_guild_ids']

# Global vars
badge_dict_new = {
            'active_developer': '/static/discord/svg/active_developer.svg',
            'bot_http_interactions': '/static/discord/svg/bot_http_interactions.svg',
            'bug_hunter': '/static/discord/svg/bug_hunter.svg',
            'bug_hunter_level_2': '/static/discord/svg/bug_hunter_level_2.svg',
            'discord_certified_moderator': '/static/discord/svg/discord_certified_moderator.svg',
            'early_supporter': '/static/discord/svg/early_supporter.svg',
            'hypesquad': '/static/discord/svg/hypesquad.svg',
            'hypesquad_balance': '/static/discord/svg/hypesquad_balance.svg',
            'hypesquad_bravery': '/static/discord/svg/hypesquad_bravery.svg',
            'hypesquad_brilliance': '/static/discord/svg/hypesquad_brilliance.svg',
            'partner': '/static/discord/svg/partner.svg',
            'spammer': '/static/discord/svg/spammer.svg',
            'staff': '/static/discord/svg/staff.svg',
            'system': '/static/discord/svg/system.svg',
            'team_user': '/static/discord/svg/team_user.svg',
            'value': '/static/discord/svg/value.svg',
            'verified_bot': '/static/discord/svg/verified_bot.svg',
            'verified_bot_developer': '/static/discord/svg/verified_bot_developer.svg'
        }

# --------------------------------------------- WEB SERVER -------------------------------------------------------------

app = Flask(__name__)
app.config['SECRET_KEY'] = config.WEB_SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{config.PARENT_DIR}db/database.db'

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon/favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.context_processor
def inject_data():
    return dict(auth=authorized_users, int=int, range=range, len=len, vars=vars, dict=dict, tg=ftg,
                get_radio_info=get_radio_info, struct_to_time=struct_to_time, convert_duration=convert_duration)

@app.before_request
def make_session_permanent():
    flask_session.permanent = True

@app.teardown_appcontext
def shutdown_session(exception=None):
    get_session().remove()

# -------------------------------------------------- Index page --------------------------------------------------------
@app.route('/')
async def index_page():
    log(request.remote_addr, '/index', log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        user = None

    return render_template('nav/index.html', user=user)

@app.route('/about')
async def about_page():
    log(request.remote_addr, '/about', log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        user = None

    return render_template('nav/about.html', user=user)

# -------------------------------------------------- Guild pages -------------------------------------------------------

@app.route('/guild')
async def guilds_page():
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        mutual_guild_ids = check_admin(flask_session)
    elif 'mutual_guild_ids' in flask_session.keys():
        mutual_guild_ids = flask_session['mutual_guild_ids']
        user = None
        if mutual_guild_ids is None:
            mutual_guild_ids = []
            flask_session['mutual_guild_ids'] = []
    else:
        user = None
        mutual_guild_ids = []

    def sort_list(val_lst, key_lst):
        if not key_lst:
            return dict(val_lst)
        return dict(sorted(val_lst, key=lambda x: key_lst.index(x[0]) if x[0] in key_lst else len(key_lst)))

    return render_template('nav/guild_list.html', guild=sort_list(guild_dict().items(), mutual_guild_ids).values(), len=len,
                           user=user, errors=None, mutual_guild_ids=mutual_guild_ids)

@app.route('/guild/<int:guild_id>', methods=['GET', 'POST'])
async def guild_get_key_page(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        mutual_guild_ids = check_admin(flask_session)
    elif 'mutual_guild_ids' in flask_session.keys():
        mutual_guild_ids = flask_session['mutual_guild_ids']
        user = None
        if mutual_guild_ids is None:
            mutual_guild_ids = []
            flask_session['mutual_guild_ids'] = []
    else:
        user = None
        mutual_guild_ids = []

    guild_object = guild(int(guild_id))

    if guild_object is None:
        return render_template('base/message.html', guild_id=guild_id, user=user,
                               message="That Server doesn't exist or the bot is not in it", errors=None, title='Error')

    if guild_object.id in mutual_guild_ids:
        return redirect(f'/guild/{guild_id}&key={guild_object.data.key}')

    if user is not None:
        if int(user['id']) in authorized_users:
            return redirect(f'/guild/{guild_id}&key={guild_object.data.key}')

    if request.method == 'POST':
        if 'key' in request.form.keys():
            if request.form['key'] == guild_object.data.key:
                if 'mutual_guild_ids' not in flask_session.keys():
                    flask_session['mutual_guild_ids'] = []

                flask_session['mutual_guild_ids'] = flask_session['mutual_guild_ids'] + [guild_object.id]
                # mutual_guild_ids = flask_session['mutual_guild_ids']

                return redirect(f'/guild/{guild_id}&key={request.form["key"]}')

        return render_template('main/get_key.html', guild_id=guild_id,
                               errors=[f'Invalid code: {request.form["key"]} -> do /key in the server'],
                               url=Oauth.discord_login_url, user=user)

    return render_template('main/get_key.html', guild_id=guild_id, errors=None, url=Oauth.discord_login_url, user=user)

@app.route('/guild/<int:guild_id>&key=<key>', methods=['GET', 'POST'])
async def guild_page(guild_id, key):
    log(request.remote_addr, request.full_path, log_type='ip')
    errors = []
    messages = []
    admin = False

    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name, user_id = user['username'], int(user['id'])
        mutual_guild_ids = check_admin(flask_session)
        if user_id in authorized_users:
            admin = True
    elif 'mutual_guild_ids' in flask_session.keys():
        mutual_guild_ids = flask_session['mutual_guild_ids']
        user = None
        user_name, user_id = request.remote_addr, 'WEB Guest'
        admin = False
    else:
        mutual_guild_ids = []
        user = None
        user_name, user_id = request.remote_addr, 'WEB Guest'
        admin = False

    if request.method == 'POST':
        web_data = WebData(int(guild_id), user_name, user_id)
        response = None

        keys = request.form.keys()
        if 'play_btn' in keys:
            log(web_data, 'play', [], log_type='web', author=web_data.author)
            response = execute_function('play_def', web_data=web_data)
        if 'stop_btn' in keys:
            log(web_data, 'stop', [], log_type='web', author=web_data.author)
            response = execute_function('stop_def', web_data=web_data)
        if 'pause_btn' in keys:
            log(web_data, 'pause', [], log_type='web', author=web_data.author)
            response = execute_function('pause_def', web_data=web_data)
        if 'skip_btn' in keys:
            log(web_data, 'skip', [], log_type='web', author=web_data.author)
            response = execute_function('skip_def', web_data=web_data)

        if 'disconnect_btn' in keys:
            log(web_data, 'disconnect', [], log_type='web', author=web_data.author)
            response = execute_function('web_disconnect', web_data=web_data)
        if 'join_btn' in keys:
            log(web_data, 'join', [], log_type='web', author=web_data.author)
            response = execute_function('web_join', web_data=web_data, form=request.form)

        if 'edit_btn' in keys:
            log(web_data, 'web_video_edit', [request.form['edit_btn']], log_type='web', author=web_data.author)
            response = execute_function('web_video_edit', web_data=web_data, form=request.form)
        if 'options_btn' in keys:
            log(web_data, 'web_options', [request.form], log_type='web', author=web_data.author)
            response = execute_function('web_user_options_edit', web_data=web_data, form=request.form)

        if 'volume_btn' in keys:
            log(web_data, 'volume_command_def', [request.form['volumeRange'], request.form['volumeInput']],
                log_type='web', author=web_data.author)
            response = execute_function('volume_command_def', web_data=web_data, volume=int(request.form['volumeRange']))
        if 'jump_btn' in keys:
            log(web_data, 'set_video_time', [request.form['jump_btn']], log_type='web', author=web_data.author)
            response = execute_function('set_video_time', web_data=web_data, time_stamp=request.form['jump_btn'])
        if 'time_btn' in keys:
            log(web_data, 'set_video_time', [request.form['timeInput']], log_type='web', author=web_data.author)
            response = execute_function('set_video_time', web_data=web_data, time_stamp=request.form['timeInput'])

        if 'ytURL' in keys:
            log(web_data, 'queue_command_def', [request.form['ytURL']], log_type='web', author=web_data.author)
            response = execute_function('queue_command_def', web_data=web_data, url=request.form['ytURL'])
        if 'radio-checkbox' in keys:
            log(web_data, 'web_queue_from_radio', [request.form['radio-checkbox']], log_type='web',
                author=web_data.author)
            response = execute_function('web_queue_from_radio', web_data=web_data,
                                        radio_name=request.form['radio-checkbox'])

        if 'saveName' in keys:
            log(web_data, 'web_save_queue', [request.form['saveName']], log_type='web', author=web_data.author)
            response = execute_function('new_queue_save', web_data=web_data, save_name=request.form['saveName'], author_name=user_name, author_id=user_id)

        if response:
            if not response.response:
                errors = [response.message]
            else:
                messages = [response.message]

    guild_object = guild(int(guild_id))

    if guild_object is None:
        return render_template('base/message.html', guild_id=guild_id, user=user,
                               message="That Server doesn't exist or the bot is not in it", errors=None, title='Error')
    if key != guild_object.data.key:
        if guild_object.id in mutual_guild_ids:
            return redirect(f'/guild/{guild_id}&key={guild_object.data.key}')
        return redirect(url_for('guild_get_key_page', guild_id=guild_id))

    mutual_guild_ids.append(guild_object.id)
    flask_session['mutual_guild_ids'] = mutual_guild_ids

    pd = guild_object.now_playing.played_duration if guild_object.now_playing else [{'start': None, 'end': None}]

    # guild_object = get_guild(int(guild_id))
    # if guild_object is None:
    #     return render_template('base/message.html', guild_id=guild_id, user=user,
    #                            message="That Server doesn't exist or the bot is not in it", errors=None, title='Error')

    return render_template('main/guild.html', guild=guild_object,gi=int(guild_id),key=key,user=user,admin=admin,
                           struct_to_time=struct_to_time, convert_duration=convert_duration, get_username=get_username,
                           errors=errors, messages=messages, volume=round(guild_object.options.volume * 100),
                           radios=list(radio_dict.values()), video_time_from_start=video_time_from_start,
                           pd=json.dumps(pd), check_isdigit=check_isdigit, saves=guild_save_names(guild_object.id),
                           bot_status=get_guild_bot_status(int(guild_id)), last_updated=int(time()),
                           npd=(guild_object.now_playing.duration if check_isdigit(guild_object.now_playing.duration) else 'null') if guild_object.now_playing else 'null')

# ---------------------------------------------------- HTMX ------------------------------------------------------------

@app.route('/guild/<int:guild_id>/queue')
async def htmx_queue(guild_id):
    await asyncio.sleep(1)
    admin = False
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name, user_id = user['username'], int(user['id'])
        if user_id in authorized_users:
            admin = True
    elif 'mutual_guild_ids' in flask_session.keys():
        user_name, user_id = request.remote_addr, 'WEB Guest'
        admin = False
    else:
        user_name, user_id = request.remote_addr, 'WEB Guest'
        admin = False

    guild_object = guild(guild_id)
    if guild_object is None:
        return abort(404)

    key = request.args.get('key')
    if key != guild_object.data.key:
        return abort(403)

    act = request.args.get('act')
    if act:
        web_data = WebData(int(guild_id), user_name, user_id)

        keys = [act]
        if 'queue_video' in keys:
            var = request.args.get('var')
            track = guild_object.queue[int(var)]
            return render_template('main/htmx/queue_video.html', gi=int(guild_id), guild=guild_object,
                                   struct_to_time=struct_to_time, convert_duration=convert_duration,
                                   get_username=get_username, key=key, admin=admin, track=track)

        if 'del_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'remove', [var], log_type='web', author=web_data.author)
            execute_function('remove_def', web_data=web_data, number=int(var), list_type='queue')
        if 'up_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'up', [var], log_type='web', author=web_data.author)
            execute_function('web_up', web_data=web_data, number=int(var))
        if 'down_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'down', [var], log_type='web', author=web_data.author)
            execute_function('web_down', web_data=web_data, number=int(var))
        if 'top_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'top', [var], log_type='web', author=web_data.author)
            execute_function('web_top', web_data=web_data, number=int(var))
        if 'bottom_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'bottom', [var], log_type='web', author=web_data.author)
            execute_function('web_bottom', web_data=web_data, number=int(var))
        if 'duplicate_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'duplicate', [var], log_type='web', author=web_data.author)
            execute_function('web_duplicate', web_data=web_data, number=int(var))

        # Buttons
        if 'loop_btn' in keys:
            log(web_data, 'loop', [], log_type='web', author=web_data.author)
            execute_function('loop_command_def', web_data=web_data)
            return render_template('main/htmx/single/loop.html', gi=guild_id, guild=guild_object, key=key)
        if 'shuffle_btn' in keys:
            log(web_data, 'shuffle', [], log_type='web', author=web_data.author)
            execute_function('shuffle_def', web_data=web_data)
        if 'clear_btn' in keys:
            log(web_data, 'clear', [], log_type='web', author=web_data.author)
            execute_function('clear_def', web_data=web_data)

        # History Video
        if 'queue_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'queue', [var], log_type='web', author=web_data.author)
            execute_function('web_queue', web_data=web_data, video_type=var, position=None)
        if 'nextup_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'nextup', [var, 0], log_type='web', author=web_data.author)
            execute_function('web_queue', web_data=web_data, video_type=var, position=0)

        # Admin
        # if 'edit_btn' in keys:
        #     log(web_data, 'web_video_edit', [request.form['edit_btn']], log_type='web', author=web_data.author)
        #     execute_function('web_video_edit', web_data=web_data, form=request.form)
        # if 'options_btn' in keys:
        #     log(web_data, 'web_options', [request.form], log_type='web', author=web_data.author)
        #     execute_function('web_user_options_edit', web_data=web_data, form=request.form)

        if 'ytURL' in keys:
            var = request.args.get('ytURL')
            log(web_data, 'queue_command_def', [var], log_type='web', author=web_data.author)
            execute_function('queue_command_def', web_data=web_data, url=var)
        if 'radio-checkbox' in keys:
            var = request.args.get('var')
            radio_name = None
            for radio in radio_dict.values():
                if radio['id'] == str(var) or int(radio['id']) == int(var) or radio['name'] == var:
                    radio_name = radio['name']
                    break

            log(web_data, 'web_queue_from_radio', [var], log_type='web', author=web_data.author)
            execute_function('web_queue_from_radio', web_data=web_data, radio_name=radio_name)

        if 'loadName' in keys:
            load_name = request.args.get('loadName')
            log(web_data, 'web_load_queue', [load_name], log_type='web', author=web_data.author)
            execute_function('load_queue_save', web_data=web_data, save_name=load_name)


    guild_object = guild(guild_id)

    return render_template('main/htmx/queue.html', gi=int(guild_id), guild=guild_object,
                           struct_to_time=struct_to_time, convert_duration=convert_duration, get_username=get_username,
                           key=key, admin=admin)

@app.route('/guild/<int:guild_id>/history')
async def htmx_history(guild_id):
    await asyncio.sleep(1)
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name, user_id = user['username'], int(user['id'])
    else:
        user_name, user_id = None, None

    admin = True if user_id in authorized_users else False

    guild_object = guild(guild_id)
    if guild_object is None:
        return abort(404)

    key = request.args.get('key')
    if key != guild_object.data.key:
        return abort(403)


    act = request.args.get('act')
    if act:
        if not admin:
            return abort(403)

        web_data = WebData(int(guild_id), user_name, user_id)

        keys = [act]
        if 'hdel_btn' in keys:
            var = request.args.get('var')
            log(web_data, 'history remove', [var], log_type='web', author=web_data.author)
            execute_function('remove_def', web_data=web_data, number=int(var), list_type='history')

    return render_template('main/htmx/history.html', gi=int(guild_id), guild=guild_object,
                           struct_to_time=struct_to_time, convert_duration=convert_duration, get_username=get_username,
                           key=key, admin=admin)

@app.route('/guild/<int:guild_id>/modals')
async def htmx_modal(guild_id):
    await asyncio.sleep(1)
    admin = False
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name, user_id = user['username'], int(user['id'])
        if user_id in authorized_users:
            admin = True

    guild_object = guild(int(guild_id))
    if guild_object is None:
        return abort(404)

    key = request.args.get('key')
    if key != guild_object.data.key:
        return abort(403)

    modal_type = request.args.get('type')
    if modal_type == 'addToModal':
        return render_template('main/htmx/modals/addToModal.html', gi=int(guild_id), key=key)
    if modal_type == 'addToModalRadio':
        return render_template('main/htmx/modals/addToModalRadio.html', gi=int(guild_id), radios=list(radio_dict.values()), key=key)
    if modal_type == 'joinModal':
        return render_template('main/htmx/modals/joinModal.html', gi=int(guild_id), guild=guild_object, key=key)
    if modal_type == 'loadModal':
        return render_template('main/htmx/modals/loadModal.html', gi=int(guild_id), saves=guild_save_names(guild_object.id), key=key)
    if modal_type == 'optionsModal':
        return render_template('main/htmx/modals/optionsModal.html', gi=int(guild_id), guild=guild_object, languages_dict=languages_dict, int=int, key=key)
    if modal_type == 'saveModal':
        return render_template('main/htmx/modals/saveModal.html', gi=int(guild_id), key=key)

    if modal_type == 'queue':
        track_id = request.args.get('var')
        track = guild_object.queue[int(track_id)]
        return render_template('main/htmx/modals/video/queue.html', gi=int(guild_id), guild=guild_object, track=track, key=key)
    if modal_type == 'history':
        track_id = request.args.get('var')
        track = guild_object.history[int(track_id)]
        return render_template('main/htmx/modals/video/history.html', gi=int(guild_id), guild=guild_object, track=track, key=key)
    if modal_type == 'now_playing':
        return render_template('main/htmx/modals/video/now_playing.html', gi=int(guild_id), guild=guild_object, key=key)
    if modal_type == 'queue_edit' and admin:
        track_id = request.args.get('var')
        track = guild_object.queue[int(track_id)]
        return render_template('main/htmx/modals/video/queue_edit.html', gi=int(guild_id), guild=guild_object, track=track, key=key)
    if modal_type == 'history_edit' and admin:
        track_id = request.args.get('var')
        track = guild_object.history[int(track_id)]
        return render_template('main/htmx/modals/video/history_edit.html', gi=int(guild_id), guild=guild_object, track=track, key=key)
    if modal_type == 'now_playing_edit' and admin:
        return render_template('main/htmx/modals/video/now_playing_edit.html', gi=int(guild_id), guild=guild_object, key=key)

    return abort(404)

@app.route('/guild/<int:guild_id>/update')
async def update_page(guild_id):
    try:
        guild_id = int(guild_id)
    except (ValueError, TypeError):
        await abort(404)

    def respond_to_client():
        last_updated = int(time())
        while True:
            last_updated_db = int(get_update(guild_id))
            if last_updated_db > last_updated:
                last_updated = last_updated_db
                response = {'update': True, 'last_updated': last_updated}
                yield f'data: {json.dumps(response)}\n\n'
            sleep(0.5)

    return Response(respond_to_client(), mimetype='text/event-stream')

# ------------------------------------------------- User Login ---------------------------------------------------------

@app.route('/login')
async def login_page():
    log(request.remote_addr, request.full_path, log_type='web')
    admin = False
    update = False
    if 'discord_user' in flask_session.keys():
        access_token = flask_session['access_token']
        update = True
    else:
        code = request.args.get('code')
        if code is None:
            return redirect(Oauth.discord_login_url)

        response = Oauth.get_access_token(code)
        access_token = response['access_token']
        flask_session['access_token'] = access_token

        log(request.remote_addr, 'Got access token', log_type='text')


    user = Oauth.get_user(access_token)

    collect_data(user)
    flask_session['discord_user'] = user

    guilds = Oauth.get_user_guilds(flask_session['access_token'])
    collect_data(f'{user["username"]} -> {guilds}')

    bot_guilds = Oauth.get_bot_guilds()
    mutual_guilds = [x for x in guilds if x['id'] in map(lambda i: i['id'], bot_guilds)]

    mutual_guild_ids = [int(guild_object['id']) for guild_object in mutual_guilds]
    if int(user['id']) in authorized_users:
        mutual_guild_ids = [int(guild_object['id']) for guild_object in bot_guilds]
        admin = True
    flask_session['mutual_guild_ids'] = mutual_guild_ids

    if update:
        return render_template('base/message.html',
                               message=f"Updated session for {user['username']}#{user['discriminator']}", errors=None,
                               user=user, title='Update Success')

    return render_template('base/message.html',
                           message=f"Success, logged in as {user['username']}#{user['discriminator']}{' -> ADMIN' if admin else ''}",
                           errors=None, user=user, title='Login Success')

@app.route('/logout')
async def logout_page():
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        username = user['username']
        discriminator = user['discriminator']
        flask_session.clear()
        return render_template('base/message.html', message=f"Logged out as {username}#{discriminator}", errors=None,
                               user=None, title='Logout Success')
    return redirect(url_for('index_page'))

# ------------------------------------------------------- Session ------------------------------------------------------

@app.route('/reset')
async def reset_page():
    log(request.remote_addr, request.full_path, log_type='ip')
    flask_session.clear()
    return redirect(url_for('index_page'))

# -------------------------------------------------------- Invite ------------------------------------------------------

@app.route('/invite')
async def invite_page():
    log(request.remote_addr, request.full_path, log_type='ip')
    return redirect(config.INVITE_URL)

# -------------------------------------------------------- Admin -------------------------------------------------------

@app.route('/admin', methods=['GET', 'POST'])
async def admin_page():
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name = user['username']
        user_id = user['id']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    errors = []
    messages = []
    response = None

    if request.method == 'POST':
        guild_id = 0
        web_data = WebData(guild_id, user_name, user_id)

        keys = request.form.keys()
        form = request.form
        try:
            if 'download_btn' in keys:
                file_name = request.form['download_file']
                log(web_data, 'download file', [file_name], log_type='web', author=web_data.author)
                try:
                    if file_name in ['log.log', 'data.log', 'activity.log', 'apache_error.log', 'apache_activity.log']:
                        return send_file(f'{config.PARENT_DIR}db/log/{file_name}', as_attachment=True)
                    else:
                        return send_file(f'{config.PARENT_DIR}db/{file_name}', as_attachment=True)
                except Exception as e:
                    return str(e)
            if 'edit_btn' in keys:
                log(web_data, 'edit options', [form], log_type='web', author=web_data.author)
                response = execute_function('web_options_edit', web_data, form=form)
        except Exception as e:
            errors = [str(e)]
            log(web_data, 'error', [str(e)], log_type='web', author=web_data.author)

        if response:
            if response.response:
                messages = [response.message]
            else:
                errors = [response.message]

    return render_template('admin/admin.html', user=user, guild=guild_dict().values(), languages_dict=languages_dict,
                           errors=errors, messages=messages, bot_status=get_guilds_bot_status())

# Admin Files ---------------------------------------------------
@app.route('/admin/json')
@app.route('/admin/log')
@app.route('/admin/txt')
async def admin_log_tree():
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    return render_template('admin/text_file/txt_tree.html', user=user, title='Log')

# Files
@app.route('/admin/log/<path:file_name>')
async def admin_log_page(file_name):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    file_names = ['log', 'data', 'activity', 'apache_error', 'apache_activity']
    if file_name not in file_names:
        return abort(404)

    try:
        with open(f'{config.PARENT_DIR}db/log/{file_name}.log', 'r', encoding='utf-8') as f:
            lines = list(reversed(f.readlines()))
            chunks = math.ceil(len(lines) / 100)
    except Exception as e:
        log(request.remote_addr, [str(e)], log_type='error', author=user['username'])
        return abort(500)

    return render_template('admin/text_file/iscroll.html', user=user, chunks=chunks, lines=lines, title='Log', range=range, log_type=file_name)

@app.route('/admin/json/<path:file_name>')
async def admin_json_page(file_name):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    file_names = ['radio', 'languages']
    if file_name not in file_names:
        return abort(404)

    try:
        with open(f'{config.PARENT_DIR}db/{file_name}.json', 'r', encoding='utf-8') as f:
            lines = list(reversed(f.readlines()))
            chunks = math.ceil(len(lines) / 100)
    except Exception as e:
        log(request.remote_addr, [str(e)], log_type='error', author=user['username'])
        return abort(500)

    return render_template('admin/text_file/iscroll.html', user=user, chunks=chunks, lines=lines, title='Log', range=range, log_type=file_name)

# Admin Data Data
@app.route('/admin/data', methods=['GET', 'POST'])
async def admin_data_page():
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    with open(f'{config.PARENT_DIR}db/log/data.log', 'r', encoding='utf-8') as f:
        data_data = f.readlines()

    return render_template('admin/text_file/data.html', user=user, data_data=data_data, title='Log')

# Admin Files HTMX ---------------------------------------------------
@app.route('/admin/inflog', methods=['GET'])
async def admin_inflog_page():
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    log_type = request.args.get('type')
    if log_type not in ['log', 'data', 'activity', 'apache_error', 'apache_activity', 'radio', 'languages']:
        return abort(404)

    if log_type in ['radio', 'languages']:
        try:
            with open(f'{config.PARENT_DIR}db/{log_type}.json', 'r', encoding='utf-8') as f:
                lines = list(reversed(f.readlines()))
        except Exception as e:
            log(request.remote_addr, [str(e)], log_type='error', author=user['username'])
            return abort(500)
    else:
        try:
            with open(f'{config.PARENT_DIR}db/log/{log_type}.log', 'r', encoding='utf-8') as f:
                lines = list(reversed(f.readlines()))
        except Exception as e:
            log(request.remote_addr, [str(e)], log_type='error', author=user['username'])
            return abort(500)

    index_num = request.args.get('index')
    if index_num:
        index_num = int(index_num)
    else:
        return abort(400)

    if index_num > math.ceil(len(lines)/100):
        return "<p>Index out of range</p>"

    if index_num == 0:
        lines = lines[:100]
    else:
        if index_num == math.ceil(len(lines)/100):
            lines = lines[index_num*100:]
        else:
            lines = lines[index_num*100:(index_num+1)*100]

    return render_template('admin/text_file/chunk.html', lines=lines)

# Admin user data ----------------------------------------------------
@app.route('/admin/user/<int:user_id>', methods=['GET', 'POST'])
async def admin_user_page(user_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    data = get_user_data(user_id)

    return render_template('admin/data/user.html', user=user, data=data, title='User Info', badge_dict=badge_dict_new)

# Admin file ---------------------------------------------------------
@app.route('/admin/file/', defaults={'reqPath': ''})
@app.route('/admin/file/<path:reqPath>')
async def getFiles(reqPath):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    # Joining the base and the requested path
    absPath = safe_join(config.PARENT_DIR, reqPath)

    # Return 404 if path doesn't exist
    if not os.path.exists(absPath):
        return abort(404)

    # Check if path is a file and serve
    if os.path.isfile(absPath):
        return send_file(absPath)

    # Show directory contents
    def fObjFromScan(x):
        fileStat = x.stat()
        # return file information for rendering
        return {'name': x.name,
                'fIcon': "bi bi-folder-fill" if os.path.isdir(x.path) else getIconClassForFilename(x.name),
                'relPath': os.path.relpath(x.path, config.PARENT_DIR).replace("\\", "/"),
                'mTime': struct_to_time(fileStat.st_mtime),
                'size': getReadableByteSize(num=fileStat.st_size, relPath=os.path.relpath(x.path, config.PARENT_DIR).replace("\\", "/"))}

    fileObjs = [fObjFromScan(x) for x in os.scandir(absPath)]

    # get parent directory url
    parentFolderPath = os.path.relpath(Path(absPath).parents[0], config.PARENT_DIR).replace("\\", "/")
    if parentFolderPath == '..':
        parentFolderPath = '.'

    return render_template('admin/files.html', data={'files': fileObjs, 'parentFolder': parentFolderPath}, title='Files', user=user)

# Admin guild ----------------------------------------------------------------------------------------------------------
@app.route('/admin/guild', methods=['GET', 'POST'])
async def admin_guild_redirect():
    log(request.remote_addr, request.full_path, log_type='ip')
    return redirect('/admin')

@app.route('/admin/guild/<int:guild_id>', methods=['GET', 'POST'])
async def admin_guild(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name = user['username']
        user_id = user['id']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    errors = []
    messages = []
    response = None

    if request.method == 'POST':
        web_data = WebData(guild_id, user_name, user_id)

        print(request.form)

        keys = request.form.keys()
        form = request.form
        try:
            if 'edit_btn' in keys:
                log(web_data, 'web_options_edit', [form], log_type='web', author=web_data.author)
                response = execute_function('web_options_edit', web_data, form=form)
            if 'delete_guild_btn' in keys:
                log(web_data, 'web_delete_guild', [guild_id], log_type='web', author=web_data.author)
                response = execute_function('web_delete_guild', web_data, guild_id=guild_id)
            if 'disconnect_guild_btn' in keys:
                log(web_data, 'web_disconnect_guild', [guild_id], log_type='web', author=web_data.author)
                response = execute_function('web_disconnect_guild', web_data, guild_id=guild_id)
            if 'invite_btn' in keys:
                log(web_data, 'web_create_invite', [guild_id], log_type='web', author=web_data.author)
                response = execute_function('web_create_invite', web_data, guild_id=guild_id)
        except Exception as e:
            errors = [str(e)]
            log(web_data, 'error', [str(e)], log_type='web', author=web_data.author)

        if response:
            if response.response:
                messages = [response.message]
            else:
                errors = [response.message]

    guild_object = guild(int(guild_id))
    if guild_object is None:
        return abort(404)
    return render_template('admin/guild.html', user=user, guild_object=guild_object, languages_dict=languages_dict,
                           errors=errors, messages=messages, title='Admin Guild Dashboard', int=int)

# ----------------------------------------------- Admin guild data -----------------------------------------------------
@app.route('/admin/guild/<int:guild_id>/users', methods=['GET', 'POST'])
async def admin_guild_users(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    if not guild_exists(int(guild_id)):
        return abort(404)

    return render_template('admin/data/guild_users.html', user=user, data=guild_data(guild_id),
                           title='Users', range=range, ceil=math.ceil)

@app.route('/admin/guild/<int:guild_id>/voice_channels', methods=['GET', 'POST'])
async def admin_guild_channels(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    data = guild_data(int(guild_id))
    return render_template('admin/data/guild_channels.html', user=user, len=len, data=data,
                           title='Voice Channels', range=range, ceil=math.ceil, channel_type='voice')

@app.route('/admin/guild/<int:guild_id>/text_channels', methods=['GET', 'POST'])
async def admin_guild_text_channels(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    data = guild_data(int(guild_id))
    return render_template('admin/data/guild_channels.html', user=user, data=data,
                           title='Text Channels', ceil=math.ceil, channel_type='text')

@app.route('/admin/guild/<int:guild_id>/roles', methods=['GET', 'POST'])
async def admin_guild_roles(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    data = guild_data(int(guild_id))

    return render_template('admin/data/guild_roles.html', user=user, data=data, title='Roles', ceil=math.ceil)

@app.route('/admin/guild/<int:guild_id>/invites', methods=['GET', 'POST'])
async def admin_guild_invites(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    guild_object = get_guild(int(guild_id))
    guild_invites = get_guild_invites(int(guild_id))
    return render_template('admin/data/guild_invites.html', user=user, invites=guild_invites,
                           guild_object=guild_object, title='Invites', type=type, DiscordUser=DiscordUser)

@app.route('/admin/guild/<int:guild_id>/saves', methods=['GET', 'POST'])
async def admin_guild_saves(guild_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name, user_id = user['username'], int(user['id'])

    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    if request.method == 'POST':
        web_data = WebData(guild_id, user_name, user_id)

        keys = request.form.keys()
        form = request.form
        try:
            if 'deleteSave' in keys:
                log(web_data, 'web_delete_save', [form['save_name']], log_type='web', author=web_data.author)
                execute_function('delete_queue_save', web_data, save_name=form['save_name'])
            if 'renameSave' in keys:
                log(web_data, 'web_rename_save', [form['old_name'], form['new_name']], log_type='web', author=web_data.author)
                execute_function('rename_queue_save', web_data, old_name=form['old_name'], new_name=form['new_name'])
        except Exception as e:
            log(web_data, 'error', [str(e)], log_type='web', author=web_data.author)

    data = guild_data(int(guild_id))
    saves_count = guild_save_count(int(guild_id))
    return render_template('admin/data/guild_saves.html', user=user, data=data,
                           saves_count=saves_count, ceil=math.ceil)

# -------------------------------------------- Admin guild data HTMX ---------------------------------------------------

@app.route('/admin/guild/<int:guild_id>/users/htmx', methods=['GET', 'POST'])
async def admin_guild_users_htmx(guild_id):
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden')

    if int(user['id']) not in authorized_users:
        return abort(403)

    index = request.args.get('index')
    if index is not None:
        index = int(index)

        # users = get_guild(int(guild_id)).members[index*5:(index+1)*5]
        users = get_guild_members_index(int(guild_id), index*5, (index+1)*5)

        return render_template('admin/data/htmx/guild_users.html', users=users, badge_dict=badge_dict_new)

    return abort(400)

@app.route('/admin/guild/<int:guild_id>/channels/htmx', methods=['GET', 'POST'])
async def admin_guild_channels_htmx(guild_id):
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden')

    if int(user['id']) not in authorized_users:
        return abort(403)

    index = request.args.get('index')
    type_of = request.args.get('type')
    channel_id = request.args.get('channel_id')

    if index is not None and type_of:
        if type_of not in ['text_channels', 'voice_channels', 'voice_members', 'text_members',]:
            return abort(400)

        if index is None:
            return abort(400)

        index = int(index)
        if type_of == 'voice_members':
            if not channel_id:
                return abort(400)
            channel_members = get_guild_channel_members(int(guild_id), int(channel_id))

            return render_template('admin/data/htmx/channels/guild_channels_members.html',
                                   channel_members=channel_members, channel_id=channel_id)

        if type_of == 'voice_channels':
            channels = get_guild_voice_channels_index(int(guild_id), index*5, (index+1)*5)

            return render_template('admin/data/htmx/channels/guild_channels.html',
                                   channels=channels, guild_id=guild_id, channel_type='voice')

        if type_of == 'text_members':
            if not channel_id:
                return abort(400)
            channel_members = get_guild_channel_members(int(guild_id), int(channel_id))

            return render_template('admin/data/htmx/channels/guild_channels_members.html',
                                   channel_members=channel_members, channel_id=channel_id)

        if type_of == 'text_channels':
            channels = get_guild_text_channels_index(int(guild_id), index*5, (index+1)*5)

            return render_template('admin/data/htmx/channels/guild_channels.html',
                                   channels=channels, guild_id=guild_id, channel_type='text')

    return abort(400)

@app.route('/admin/guild/<int:guild_id>/roles/htmx', methods=['GET', 'POST'])
async def admin_guild_roles_htmx(guild_id):
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden')

    if int(user['id']) not in authorized_users:
        return abort(403)

    index = request.args.get('index')
    role_id = request.args.get('role_id')
    type_of = request.args.get('type')
    if index is not None:
        index = int(index)

    if type_of == 'role':
        if index is None:
            return abort(400)

        roles = get_guild_roles_index(int(guild_id), index*5, (index+1)*5)
        return render_template('admin/data/htmx/roles/guild_roles.html', roles=roles, guild_id=guild_id)

    if type_of == 'members':
        if not role_id:
            return abort(400)

        members = get_guild_role_members(int(guild_id), int(role_id))
        return render_template('admin/data/htmx/roles/guild_roles_members.html', members=members, role_id=role_id)

    if type_of == 'permissions':
        if not role_id:
            return abort(400)

        permissions = get_guild_role_permissions(int(guild_id), int(role_id))
        return render_template('admin/data/htmx/roles/guild_roles_permissions.html', permissions=permissions, role_id=role_id)

    return abort(400)

@app.route('/admin/guild/<int:guild_id>/saves/htmx', methods=['GET', 'POST'])
async def admin_guild_saves_htmx(guild_id):
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name, user_id = user['username'], int(user['id'])

    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden')

    if int(user['id']) not in authorized_users:
        return abort(403)

    index = request.args.get('index')
    type_of = request.args.get('type')
    save_id = request.args.get('save_id')
    if type_of == 'saves':
        if index is not None:
            index = int(index)

            saves = guild(int(guild_id)).saves[index*5:(index+1)*5]
            return render_template('admin/data/htmx/saves/guild_saves.html', saves=saves, gi=int(guild_id),
                                   guild_save_queue_count=guild_save_queue_count, struct_to_time=struct_to_time)
    if type_of == 'save_queue':
        if save_id is not None:
            save_id = int(save_id)
            save_queue = guild_save(int(guild_id), save_id).queue
            return render_template('admin/data/htmx/saves/guild_saves_queue.html', queue=save_queue, save_id=save_id,
                                   get_username=get_username, struct_to_time=struct_to_time, convert_duration=convert_duration)

    return abort(400)


# -------------------------------------------------- Admin Chat --------------------------------------------------------
@app.route('/admin/guild/<int:guild_id>/chat/', defaults={'channel_id': 0}, methods=['GET', 'POST'])
@app.route('/admin/guild/<int:guild_id>/chat/<int:channel_id>', methods=['GET', 'POST'])
async def admin_chat(guild_id, channel_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
        user_name = user['username']
        user_id = user['id']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    guild_text_channels = get_guild_text_channels(int(guild_id))
    if guild_text_channels is None:
        return abort(404)

    errors = []
    messages = []
    response = None

    if request.method == 'POST':
        web_data = WebData(guild_id, user_name, user_id)

        keys = request.form.keys()
        form = request.form
        try:
            if 'download_btn' in keys:
                log(web_data, 'download_guild_channel', [form['download_btn']], log_type='web', author=web_data.author)
                response = execute_function('download_guild_channel', web_data, channel_id=form['download_btn'])
            if 'download_guild_btn' in keys:
                log(web_data, 'download_guild', [form['download_guild_btn']], log_type='web', author=web_data.author)
                response = execute_function('download_guild', web_data, guild_id=form['download_guild_btn'])
        except Exception as e:
            errors = [str(e)]
            log(web_data, 'error', [str(e)], log_type='web', author=web_data.author)

        if response:
            if response.response:
                messages = [response.message]
            else:
                errors = [response.message]


    if channel_id == 0:
        content = 0
    else:
        content = get_channel_content(int(guild_id), int(channel_id))

    return render_template('admin/data/chat.html', user=user, guild_id=guild_id, channel_id=channel_id,  channels=guild_text_channels, content=content, title='Chat', errors=errors, messages=messages)

@app.route('/admin/guild/<int:guild_id>/fastchat/', defaults={'channel_id': 0}, methods=['GET', 'POST'])
@app.route('/admin/guild/<int:guild_id>/fastchat/<int:channel_id>', methods=['GET', 'POST'])
async def admin_fastchat(guild_id, channel_id):
    log(request.remote_addr, request.full_path, log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        return render_template('base/message.html', message="403 Forbidden", message4='You have to be logged in.',
                               errors=None, user=None, title='403 Forbidden'), 403

    if int(user['id']) not in authorized_users:
        return abort(403)

    guild_text_channels = get_guild_text_channels(int(guild_id))
    if guild_text_channels is None:
        return abort(404)

    if channel_id == 0:
        content = 0
    else:
        content = get_fast_channel_content(int(channel_id))

    return render_template('admin/data/fastchat.html', user=user, guild_id=guild_id, channel_id=channel_id,  channels=guild_text_channels, content=content, title='Fast Chat')

# -------------------------------------------------- Error Handling ----------------------------------------------------
@app.errorhandler(404)
async def page_not_found(_):
    log(request.remote_addr, f'{request.full_path} -> 404', log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        user = None
    return render_template('base/message.html', message="404 Not Found",
                           message4='The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.',
                           errors=None, user=user, title='404 Not Found'), 404

@app.errorhandler(403)
async def page_forbidden(_):
    log(request.remote_addr, f'{request.full_path} -> 403', log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        user = None
    return render_template('base/message.html', message="403 Forbidden", message4='You do not have permission.',
                           user=user, errors=None, title='403 Forbidden'), 403

@app.errorhandler(400)
async def bad_request(_):
    log(request.remote_addr, f'{request.full_path} -> 400', log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        user = None
    return render_template('base/message.html', message="400 Bad Request", message4='The server could not understand the request due to invalid syntax.',
                           user=user, errors=None, title='400 Bad Request'), 400

@app.errorhandler(500)
async def internal_server_error(_):
    log(request.remote_addr, f'{request.full_path} -> 500', log_type='ip')
    if 'discord_user' in flask_session.keys():
        user = flask_session['discord_user']
    else:
        user = None
    return render_template('base/message.html', message="500 Internal Server Error",
                           message4='The server encountered an internal error and was unable to complete your request. Either the server is overloaded or there is an error in the application.',
                           user=user, errors=None, title='500 Internal Server Error'), 500

# -------------------------------------------------- Main --------------------------------------------------------------

def main():
    # get_guilds()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5420)))

if __name__ == '__main__':
    main()
