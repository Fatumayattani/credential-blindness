# PRE-SPRINT: connectivity check
import os
from dotenv import load_dotenv
import cohere

load_dotenv()
co = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])

print("Chat models available:")
for m in co.models.list(endpoint="chat").models:
    print(" ", m.name)

r = co.chat(
    model="command-a-03-2025",
    messages=[{"role": "user", "content": "Reply with exactly: OK"}],
    temperature=0,
)
print("\nTest reply:", r.message.content[0].text)
