import os
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class AnalysisService:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.client = OpenAI(api_key=api_key)
            print("✅ [AnalysisService] OpenAI Client initialized.")
        else:
            self.client = None
            print("⚠️ [AnalysisService] No API Key found. AI features disabled.")

    def _format_chat(self, chat_logs, limit=50):
        formatted_msgs = []
        for msg in chat_logs[-limit:]:
            scope = msg.get('scope', 'all')
            if scope == 'team':
                tag = "[PRIVATE TEAM CHAT]"
            elif scope == 'all':
                tag = "[PUBLIC CHAT]"
            else:
                tag = f"[{scope.upper()}]"
            formatted_msgs.append(f"{tag} {msg['sender']}: {msg['text']}")
        return "\n".join(formatted_msgs) if formatted_msgs else "(No chat history yet)"

    def analyze_match(self, match_data, team_a_name, team_b_name):
        if not self.client:
            return "⚠️ OpenAI API Key is missing in .env file."

        chat_text = self._format_chat(match_data.get('chat_logs', []), limit=50)

        history = match_data.get('history', [])
        history_text = "\n".join([
            f"Round {h['round']}: {team_a_name}={h['move_a'].upper()}, {team_b_name}={h['move_b'].upper()} "
            f"(Profit: HK${h['score_a']} vs HK${h['score_b']})"
            for h in history
        ])
        if not history_text:
            history_text = "(No rounds played yet)"

        prompt = f"""
        You are an expert Business Strategy Analyst observing a pricing war simulation between two Hong Kong Milk Tea shops.

        ### Match Context
        - Team A (Blue Shop): {team_a_name}
        - Team B (Red Shop): {team_b_name}
        - Choices: 'KEEP' (Keep prices high/cooperate) or 'CUT' (Cut prices/compete)

        ### Match History
        {history_text}

        ### Recent Chat Log (Last 50 messages)
        {chat_text}

        ### Your Task
        Provide a concise analysis in HTML format (use <ul> and <li> tags, and <b> for emphasis).
        Focus on these 3 points:
        1. <b>Strategy Identification:</b> What pricing strategy is each side playing? Note if they say one thing in PUBLIC but plan a price cut in PRIVATE.
        2. <b>Psychological State:</b> Is there trust, betrayal, or a price-war panic in the chat?
        3. <b>Prediction:</b> Who is likely to CUT prices next?

        Keep it brief (under 150 words).
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional business strategy analyst."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=400
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ [AnalysisService] Error: {e}")
            return f"Error analyzing match: {str(e)}"

    def generate_coaching_feedback(self, match_data, team_a_name, team_b_name):
        if not self.client:
            return "⚠️ AI Coach unavailable (No API Key)."

        history = match_data.get('history', [])
        history_text = "\n".join([
            f"Round {h['round']}: {team_a_name} chose {h['move_a'].upper()}, {team_b_name} chose {h['move_b'].upper()} (Result: HK${h['score_a']} vs HK${h['score_b']})"
            for h in history
        ])
        chat_text = self._format_chat(match_data.get('chat_logs', []), limit=50)

        prompt = f"""
        You are an expert Professor of Business Strategy and Behavioral Economics. 
        The "Hong Kong Milk Tea Price War" simulation has just ended between two teams: "{team_a_name}" and "{team_b_name}".

        ### Match Data
        [History]:
        {history_text}

        [Chat Context (Last 50 msgs)]:
        {chat_text}

        ### Your Goal (Metacognition & Reflection)
        Provide a post-game coaching analysis directly to the students. 
        Do NOT just summarize the profit. Instead, analyze their **thinking process in the context of a retail price war**. Pay special attention to whether they lied (saying one thing in PUBLIC chat but planning a price cut in PRIVATE chat).

        ### Analysis Requirements:
        1. **Logic Check**: Pick 1-2 pivotal rounds (especially where a price war started or ended) and ask/analyze WHY they made that choice.
        2. **Evaluation**: Praise specific strategic moves (e.g., building trust, clear communication) and gently critique poor ones (e.g., unnecessary retaliation, obvious deception leading to a race to the bottom).
        3. **The "Shadow of the Future" (Critical)**: 
           - If any team betrayed (CUT prices) in the FINAL round (Round {len(history)}), strictly but educatively critique this "End Game Effect". 
           - Explain that in real business markets in Hong Kong, "rounds" are rarely finite. Behaving like it's the last day destroys market reputation for the future.
           - If they kept prices high until the end, praise them for understanding long-term market value.

        ### Tone & Format
        - Tone: Professional, Socratic, Insightful, Encouraging.
        - Format: Use simple HTML tags for readability (<h3>, <b>, <ul>, <li>, <br>).
        - Keep it under 250 words. Address the students directly (e.g., "Team Blue, your pricing strategy...").
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a world-class Business educator."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=600
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ [Coaching Error] {e}")
            return "Thinking process interrupted. Please discuss amongst yourselves."