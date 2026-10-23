import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

try:
    models = client.models.list()
    print(f"{'MODEL ID':<30} {'OWNED BY':<15}")
    print("-" * 45)
    for model in models.data:
        print(f"{model.id:<30} {model.owned_by:<15}")
except Exception as e:
    print(f"Error fetching models: {e}")