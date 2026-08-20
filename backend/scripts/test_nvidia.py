import os

from openai import OpenAI

client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = "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"
)



completion = client.chat.completions.create(
  model="deepseek-ai/deepseek-v4-flash",
  messages=[{"role":"user","content":"你是谁？"}],
  temperature=0.6,
  top_p=0.95,
  max_tokens=65536,
  extra_body={"chat_template_kwargs":{"enable_thinking":True},"reasoning_budget":16384},
  stream=False
)

reasoning = getattr(completion.choices[0].message, "reasoning_content", None)
if reasoning:
  print(reasoning)
print(completion.choices[0].message.content)


