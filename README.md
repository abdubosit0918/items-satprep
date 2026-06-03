## IELTS/SAT Prep Telegram Bot

Referral bot that unlocks **50 IELTS Reading & Listening materials** after a user invites 3 friends who also subscribe to the public channel.

### Flow

1. User starts the bot and subscribes to the public channel (`CHANNEL_USERNAME`)
2. User shares their personal invite link
3. Each invited friend must:
   - open the bot through that invite link
   - subscribe to the public channel
4. After **3 valid invites**, the user receives the private materials channel link

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```bash
BOT_TOKEN=your_bot_token
CHANNEL_USERNAME=@ieltssat_prep
MATERIALS_CHANNEL_LINK=https://t.me/+3qyYbWSfcoZlNWYy
ADMIN_IDS=7897407913
```

### Run

```bash
python bot.py
```

### Admin panel

Send `/admin` from an account listed in `ADMIN_IDS` to view:

- total users
- subscribed users
- valid/pending referrals
- materials unlocked count
- top referrers

### Notes

- The bot must be an **admin** in the public channel to verify subscriptions.
- Referrals are saved even if a friend is not subscribed yet; they become valid once the friend subscribes.
