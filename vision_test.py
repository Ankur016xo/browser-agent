from ollama import chat

response = chat(
    model="qwen2.5vl:3b",
    messages=[
        {
            "role": "user",
            "content": "Describe what you can do in one sentence."
        }
    ]
)

print(response.message.content)