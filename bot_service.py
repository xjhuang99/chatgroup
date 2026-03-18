import random
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class BotService:
    def __init__(self):
        self.client = None
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.client = OpenAI(api_key=api_key)
            print("✅ [BotService] OpenAI Client Connected.")
        else:
            print("⚠️ [BotService] No OpenAI Key found. Bots will use fallback phrases.")

        self.bot_profiles = {}
        self.load_profiles()
        self.counters = {}

    def load_profiles(self):
        try:
            with open('bots_config.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                for bot in data.get('bots', []):
                    self.bot_profiles[bot['name']] = bot
            print(f"✅ [BotService] Loaded {len(self.bot_profiles)} bot profiles.")
        except Exception as e:
            print(f"⚠️ [BotService] Failed to load bots_config.json: {e}")
            self.bot_profiles['default'] = {
                "prompt": "You are a helpful game assistant.",
                "msg_threshold": 1,
                "chance_to_respond": 1.0,
                "model": "gpt-4o"
            }

    def get_profile(self, bot_name):
        for key in self.bot_profiles:
            if bot_name.startswith(key):
                return self.bot_profiles[key]
        return self.bot_profiles.get('default')

    def get_config(self, bot_name):
        # Link the config fetcher to the actual profile
        return self.get_profile(bot_name)

    def should_respond(self, match_id, config):
        # Use the dynamic threshold from bots_config.json (which is now 1)
        threshold = config.get('msg_threshold', 1) if config else 1

        key = match_id
        if key not in self.counters: self.counters[key] = 0
        self.counters[key] += 1

        if self.counters[key] >= threshold:
            self.counters[key] = 0
            return True
        return False

    def generate_response(self, bot_name, chat_history):
        profile = self.get_profile(bot_name)
        if not profile:
            profile = self.bot_profiles.get('default', {})

        chance = profile.get('chance_to_respond', 1.0)
        if random.random() > chance:
            print(f"🎲 [BotSkip] {bot_name} decided not to speak (Chance: {chance})")
            return None

        opponent_msgs = [m for m in chat_history[-10:] if m['sender'] != bot_name]

        if not opponent_msgs:
            if random.random() < 0.5: return None
            context = "(Silence...)"
        else:
            context = "\n".join([f"{m['sender']}: {m['text']}" for m in opponent_msgs[-3:]])

        if not self.client:
            return "I am an AI bot (No API Key)."

        try:
            print(f"💬 [BotDebug] {bot_name} ({profile.get('name', 'Unknown')}) is thinking...")
            system_prompt = profile.get('prompt', "You are a player in a game.")

            user_prompt = f"""
            Context: You are in a chat room playing the Milk Tea Price War.
            Current Chat History:
            {context}

            Task: Reply directly and actively to the latest message based on your persona.
            Constraints:
            - Keep it short (under 15 words).
            - Do NOT include your name in the reply.
            - Do NOT use quotation marks.
            """

            response = self.client.chat.completions.create(
                model=profile.get('model', "gpt-4o"),  # Will use GPT-5 if in config, fallback to 4o
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_completion_tokens=600,
            )

            reply = response.choices[0].message.content.strip()
            reply = reply.replace('"', '').replace("'", "")
            print(f"✅ [BotReply] {bot_name}: {reply}")
            return reply

        except Exception as e:
            print(f"❌ [BotError] {e}")
            return None