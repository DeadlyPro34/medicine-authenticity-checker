import os
import traceback
from dotenv import load_dotenv
load_dotenv()
from groq import Groq

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
try:
    response = client.chat.completions.create(
        model='qwen/qwen3.8-27b',
        max_tokens=200,
        temperature=0,
        messages=[{'role': 'user', 'content': 'A user scanned a medicine pack and the text Uprise-D3 60K was read off the packaging. Respond with strict JSON only:\n{"recognized": true, "general_use": "..."}'}]
    )
    print('OUTPUT:', repr(response.choices[0].message.content))
except Exception as e:
    traceback.print_exc()
