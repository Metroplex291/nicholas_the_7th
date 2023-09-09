import classes.data_classes
from utils.globals import get_bot
from utils.save import save_json

import discord
from discord.ext import commands

def ctx_check(ctx: commands.Context or classes.data_classes.WebData) -> (bool, int, int, discord.Guild):
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
    if type(ctx) == classes.data_classes.WebData:
        bot = get_bot()
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