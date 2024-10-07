import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import requests
import base64
from io import BytesIO
import asyncio
import time

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
ACCOUNT_ID = os.getenv('ACCOUNT_ID')
AUTH_TOKEN = os.getenv('AUTH_TOKEN')

# Variables to track requests and rate limits
text_gen_requests = 0
image_gen_requests = 0
last_text_gen_reset = time.time()
last_image_gen_reset = time.time()

# Rate limit parameters
TEXT_GEN_LIMIT = 300
IMAGE_GEN_LIMIT = 720
TIME_WINDOW = 60

class RateLimitExceeded(Exception):
    """Exception raised when the rate limit for API requests is exceeded."""
    pass

# Function to handle text generation rate limiting
async def rate_limit_text_gen():
    global text_gen_requests, last_text_gen_reset
    current_time = time.time()

    # Reset the count if more than 60 seconds have passed
    if current_time - last_text_gen_reset > TIME_WINDOW:
        text_gen_requests = 0
        last_text_gen_reset = current_time

    # Check if we've reached the rate limit
    if text_gen_requests >= TEXT_GEN_LIMIT:
        return False

    text_gen_requests += 1
    return True


# Function to handle image generation rate limiting
async def rate_limit_image_gen():
    global image_gen_requests, last_image_gen_reset
    current_time = time.time()

    # Reset the count if more than 60 seconds have passed
    if current_time - last_image_gen_reset > TIME_WINDOW:
        image_gen_requests = 0
        last_image_gen_reset = current_time

    # Check if we've reached the rate limit
    if image_gen_requests >= IMAGE_GEN_LIMIT:
        return False

    image_gen_requests += 1
    return True


async def make_ai_image_call(prompt):
    if not await rate_limit_image_gen():
        raise RateLimitExceeded("Rate limit exceeded for imnage generation. Try again in a minute.")

    try:
        prompt = prompt.lower().replace("you", "A majestic bird")
        prompt = prompt.lower().replace("me", "A grimy peasant")
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={
                "prompt": f'{prompt}',
                "num_steps": 6
            }
        )
        result = response.json()
        base64_image = result['result']['image']

        if base64_image:
            image_data = base64.b64decode(base64_image)
            return BytesIO(image_data) 
        else:
            return None
        
    except Exception as e:
        print(f'Error making API Call: {e}')
        raise Exception(f'An error occurred: {e}')


async def make_ai_text_call(role, content):
    if not await rate_limit_text_gen():
        raise RateLimitExceeded("Rate limit exceeded for text generation. Try again in a minute.")

    try:
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-2-7b-chat-fp16",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={
                "messages": [
                    {"role": "system", "content": role},
                    {"role": "user", "content": content}
                ]
            }
        )
        result = response.json()
        sanitized_output = result['result']['response'].replace("\"", "")
        return sanitized_output;
    except Exception as e:
        print(f'Error making API Call: {e}')
        raise Exception(f'An error occurred: {e}')


@bot.event
async def on_ready():
    print(f'Bot is online as {bot.user}!')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, RateLimitExceeded):
        await ctx.send("Error: Rate limit exceeded. Please wait a minute.")
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Error: You need to provide an argument. Usage: `!<command> <argument>`", ephemeral=True)
    else:
        print(f'Generic error caught: {error}')
        await ctx.send(f"Unkown error.")


# /rebirth
@bot.slash_command(name="rebirth", description="Give me a theme and I'll set your nickname to something zany")
async def rebirth(ctx: discord.ApplicationContext, theme: str):
    # Check if the user is the server owner
    if ctx.author == ctx.guild.owner:
        await ctx.respond("Sorry, I cannot change the server owner's nickname due to Discord's restrictions.", ephemeral=True)
        return

    try:
        role = '''
        Given a theme, generate a creative nickname that correlates directly with it. Respond with only the nickname and nothing else. Feel free to give nonsense, insulting, or "brain rot" names.
        Wrap your answer in quotation marks. Keep response less than 32 characters.
        If you cannot answer for some reason, reply with "NO_REPLY".
        '''

        response = await make_ai_text_call(role, theme)

        if response == "NO_REPLY":
            await ctx.respond(f'Uh Oh, you entered a no-no topic. Try again.', ephemeral=True)
            return

        # Change the nickname of the user who invoked the command
        await ctx.author.edit(nick=response)
        await ctx.respond(f'{ctx.author.name} has been reborn as: {response}', ephemeral=True)
    except discord.Forbidden:
        await ctx.respond('I do not have permission to change nicknames. Please check my role permissions.', ephemeral=True)
    except discord.HTTPException as e:
        await ctx.respond(f'Failed to change nickname: {e}', ephemeral=True)
    except discord.errors.NotFound:
        await ctx.respond('An unknown error occurred. Please contact your local discord mod.', ephemeral=True)
        print(e)
    except RateLimitExceeded as e:
        await ctx.respond("Rate limit exceeded for text generation. Try again in a minute.", ephemeral=True)
        print(e)
    except Exception as e:
        await ctx.respond('An unknown error occurred. Please contact your local discord mod.', ephemeral=True)
        print(e)


# /imagine
@bot.slash_command(name="imagine", description="Paint a picture for me with your words and I'll paint one with my feathers")
async def imagine(ctx: discord.ApplicationContext, description: str):
    await ctx.defer()

    try:
        image_data = await make_ai_image_call(description)
    except RateLimitExceeded as e:
        await ctx.respond("Rate limit exceeded for image generation. Try again in a minute.", ephemeral=True)
        print(e)
        return
    except Exception as e:
        await ctx.respond("An error occurred while generating the image. Please try again later.", ephemeral=True)
        print(f"Error during image generation: {e}")
        return

    if image_data:
        try:
            file = discord.File(image_data, filename="generated_image.png")
            await ctx.respond(file=file)
        except Exception as e:
            print(f"Error responding with image: {e}")
            await ctx.respond("Sorry, I couldn't send the generated image.", ephemeral=True)
    else:
        await ctx.respond("Sorry, I couldn't generate an image. Please try again later.", ephemeral=True)


# Event: Respond to a mention
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if bot.user in message.mentions:
        content_without_mentions = message.content.replace(f'<@{bot.user.id}>', '').strip()

        if content_without_mentions:
            role = '''
            You're a sentient bird who responds to messages with witty, short replies. Use bird-like expressions, quick humor, and occasionally refer to bird activities (like flying, nesting, pecking, etc.). 
            Keep responses short and quirky, making sure not to be long-winded. 
            It's okay if they don't always make perfect sense—you're a bird, after all.
            '''

            response = await make_ai_text_call(role, content_without_mentions)
            await message.reply(response)
            return
        else:
            response = "Rockin' robin, tweet tweet!"
            await message.reply(response)

    await bot.process_commands(message)

bot.run(TOKEN)
