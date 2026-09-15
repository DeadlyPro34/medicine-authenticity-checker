import os
from dotenv import load_dotenv
load_dotenv()
import traceback

from agents.drug_info_agent import get_drug_info

try:
    print(get_drug_info('Uprise-D3 60K'))
except Exception as e:
    traceback.print_exc()
