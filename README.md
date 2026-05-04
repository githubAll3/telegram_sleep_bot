# Telegram Sleep Tracker Bot
A Telegram bot for tracking a child's sleep patterns, built with Python 3.14 and `python-telegram-bot`. Tracks night and day sleep, generates 7-day sleep charts, and supports manual sleep entry.

## Features
- Track night sleep (ended via `start` button or `/start` command)
- Track multiple day naps per day (ended via `awake` button)
- Manual sleep entry if `awake` pressed with no active session
- 7-day grouped bar chart (night vs day sleep totals)
- Timezone support (Europe/Moscow GMT+3, no DST)
- Lightweight SQLite database for data persistence
- Dockerized deployment (single service via docker-compose)

## Project Structure
```
telegram_sleep_bot/
├── bot.py              # Main bot logic, handlers, and state management
├── database.py         # SQLite database initialization and CRUD operations
├── config.py           # Reads Telegram token and timezone from telegram.conf
├── plot.py             # Generates 7-day sleep bar chart using matplotlib
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker image configuration (Python 3.14-slim)
├── docker-compose.yml  # Docker Compose setup for single service deployment
├── telegram.conf       # Bot token and timezone configuration
├── data/               # Directory for persistent SQLite database
└── .gitignore          # Ignored files/directories
```

## Prerequisites
- Python 3.14+ (for local setup)
- Docker & Docker Compose (for containerized setup)
- Telegram bot token (get from [@BotFather](https://t.me/BotFather))

## Setup
1. Replace the bot token in `telegram.conf` with your own (default token is pre-filled for testing):
   ```ini
   secret = 'YOUR_BOT_TOKEN_HERE'
   timezone = 'Europe/Moscow'
   ```
   The timezone is pre-configured to Europe/Moscow (GMT+3).

## Run Locally
1. Activate the virtual environment:
   ```powershell
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Run the bot:
   ```powershell
   python bot.py
   ```

## Run with Docker
1. Build and start the service:
   ```powershell
   docker-compose up --build -d
   ```
2. View logs (optional):
   ```powershell
   docker logs -f telegram-sleep-bot
   ```
3. Stop the service:
   ```powershell
   docker-compose down
   ```

## Bot Usage
The bot uses a persistent reply keyboard with 3 buttons (responds only to private chats):
- **`start`**: Ends ongoing night sleep, starts a new day, and sends a 7-day sleep chart. Can also be triggered via `/start` command.
- **`sleep`**: Starts a new sleep session linked to the current day. Blocks if an active session already exists.
- **`awake`**:
  - If active sleep session exists: Ends the session as day sleep, displays total day sleep.
  - If no active session: Prompts for manual sleep duration entry with an inline "Отмена" (Cancel) button to abort.

### Manual Sleep Entry
When prompted for manual sleep duration, use formats like:
- `1ч 30м` / `1h 30m` → 90 minutes
- `90м` / `90m` / `90` → 90 minutes
- `1.5ч` / `1.5h` → 90 minutes

### 7-Day Sleep Chart
The chart sent via `start` shows:
- X-axis: Dates (MSK, DD.MM format) for the last 7 days
- Y-axis: Total sleep hours
- Grouped bars: Blue (Ночной сон / Night sleep), Orange (Дневной сон / Day sleep)

## Database
- Uses SQLite for lightweight data storage
- Database file: `data/sleep.db` (persisted via Docker volume `./data:/app/data`)
- Schema:
  - `days`: Tracks days started via `start` button
  - `sleep_sessions`: Tracks all sleep sessions (night/day, multiple per day)

## Dependencies
- `python-telegram-bot>=20.0`: Telegram Bot API wrapper
- `matplotlib>=3.8`: Chart generation (configured for headless use in Docker)
