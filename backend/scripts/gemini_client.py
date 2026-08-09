import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

class Gemini_Client:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    client = genai.Client(api_key=GEMINI_API_KEY)

    def call_gemini(self, prompt, model = "gemini-3.5-flash-lite"):
        interaction = self.client.interactions.create(
            model = model,
            input = prompt
        )

        print(interaction.output_text)


if __name__ == "__main__":
    my_client = Gemini_Client()
    my_client.call_gemini("This is a test, respond with something cool")