from ollama import chat

response = chat(
    model="qwen2.5vl:3b",
    messages=[
        {
            "role": "user",
            "content": """
Look at this browser screenshot.

Your task is:
Search Google for "Galgotias University".

Return ONLY one JSON object describing the next action.

Possible actions:
- click
- type
- press
- done

For a click, include the target.
For typing, include the text.
For pressing a key, include the key.

Example:
{"action":"click","target":"search box"}

Do not explain anything.
""",
            "images": ["google.png"]
        }
    ]
)

print(response.message.content)