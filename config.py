import os
from zoneinfo import ZoneInfo

def load_config():
    config = {}
    with open('telegram.conf', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            config[key] = value
    return config

CONFIG = load_config()
BOT_TOKEN = CONFIG['secret']
TIMEZONE = ZoneInfo(CONFIG.get('timezone', 'Europe/Moscow'))
MSK = TIMEZONE
