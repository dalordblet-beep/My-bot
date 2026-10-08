# Username Scanner Bot

A Telegram bot that checks, analyses and searches Telegram usernames.
Premium-style interface, real checks, an honest `UNKNOWN` when Telegram does
not give a trustworthy answer.

```
/start -> LANGUAGE -> CAPTCHA -> required subscriptions -> access granted -> main menu
```

## Deploy on a server (Docker, one command)

The repository ships a `Dockerfile` and a `docker-compose.yml` (bot + Postgres +
Redis), so a server needs only Docker installed:

```bash
git clone https://github.com/dalordblet-beep/My-bot.git
cd My-bot
cp .env.example .env      # fill BOT_TOKEN, ADMIN_IDS, REQUIRED_SUBSCRIPTIONS, API_ID/API_HASH
docker compose up -d --build
docker compose logs -f bot
```

The bot waits for the Postgres and Redis healthchecks. Its database lives on the
`pgdata` volume and the MTProto session on the `mtproto_session` volume, so
`docker compose up -d --build` after a code update keeps both.

The bot authorises its MTProto session **automatically as the bot** from
`BOT_TOKEN` on startup, so a fresh deploy just needs `docker compose up -d
--build` — no interactive login step. A manual phone login is only needed if you
want a *user* session (see §11).

To inspect which account the current session belongs to (and whether it is a
bot):

```bash
docker compose run --rm bot python scripts/login_mtproto.py --status
```

`login.bat` on Windows does the same `--status` check; pass `--force` to replace
the session with an interactive phone login if you specifically need a user
session. Without any MTProto session the bot still runs, but availability is
then only as good as the Bot API (see §11). To run without Docker:
`pip install -r requirements.txt`, fill `.env`, then `python -m app.main`
(or `start.bat` on Windows).

> The bot uses **long polling**: it needs **no open inbound port and no domain** —
> only outbound HTTPS to `api.telegram.org`.

## Collectible usernames — how to turn them on

Collectible lookup uses **Telegram's own API**: MTProto method
`fragment.getCollectibleInfo`. No scraping, no third-party service — Telegram
returns the purchase date, the original price and the Fragment URL. It is
disabled until a **user session** exists, because that method needs to be called
as a logged-in account, not as a bot.

### Step 1 — run the login helper

Double-click **`login.bat`** in the project folder (or run
`python scripts/login_mtproto.py`). It checks dependencies, then starts the
Telethon login.

### Step 2 — answer two prompts

```
Please enter your phone (or bot token): +7XXXXXXXXXX
Please enter the code you received: 12345
```

- The phone number is the account that will perform the lookups. Your own
  account is fine — it is only used to read public Fragment data.
- The code arrives **inside the Telegram app**, not by SMS. If you have two-step
  verification enabled, it will also ask for your password.

### Step 3 — restart the bot

Close the bot window and start it again with `start.bat`. You should now see:

```
mtproto connected and authorised
```

That is it. The Fragment lookup is now used automatically as the second half of
the search's double check: a name that Telegram confirms free is only offered
when Fragment does not list it for auction or sale.

```
💎 @durov — listed on Fragment, not claimable free
✅ @yourname — Telegram free, Fragment clear -> shown with its N/5 verdict
```

### What the session file is

`username_scanner_session.session` — created next to the project. It contains
the authorisation for the account you logged in with, so:

- never commit it (already in `.gitignore`),
- never send it to anyone,
- delete it and re-run `login.bat` to revoke access.

### If you do not want to log in

The bot keeps working: everything except collectible lookup and definitive
`AVAILABLE` answers. Basic checks still detect occupied channels, groups and
bots, and the public preview page still confirms ownership of personal accounts.

You can also try the best-effort web parser, but it is not recommended — it
reads Fragment's HTML, breaks when the layout changes, and cannot report prices
reliably:

```
FRAGMENT_ENABLED=true
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `API_ID / API_HASH are missing` | Fill them in `.env` (§4). |
| The code never arrives | Check the Telegram app on the account's own device; SMS is not used. |
| `SessionPasswordNeededError` | You have two-step verification — enter your cloud password when prompted. |
| Availability checks fail after a fresh deploy | The bot auto-logs in as the bot via `BOT_TOKEN`; if it still fails, check `API_ID`/`API_HASH` are set and restart the bot. |
| `AuthKeyDuplicatedError` | The session file was copied between machines. Delete it and log in again. |

## Features

### Search
One search hunts **beautiful, unoccupied, premium usernames worth reselling**.
You tune the criteria; the bot builds names that fit them and only ever shows a
name that survives a **double check**:

1. **Telegram** — the public page screens candidates for free, then MTProto (the
   only channel allowed to declare a name AVAILABLE) confirms the survivors. A
   taken name is never dressed up as a result.
2. **Fragment** — a confirmed-free name is then checked against the Fragment
   marketplace. If it is listed for auction or sale there it is not claimable, so
   it is rejected and the hunt continues.

There is **no user-facing rating filter** — the bot applies its own taste. Every
candidate is judged on five premium criteria and shown as **N/5** (see below).

Candidates come from **two merged streams** — desirable word-like names (real
words, brands, hybrids) and readable coinages. The word-like names are the most
attractive *and* the most taken, so the coinages are interleaved rather than left
to the end: a genuinely free name shows up within the first few lookups instead
of the search burning its whole budget on saturated dictionary words and
reporting "everything is taken".

- **Length** — 5 to 16 characters, or any.
- **Digits** — allow or forbid.
- **Mask** — fix the shape of the name: `?` one letter, `#` one digit,
  `*` any letters. `??ged` matches `moged`. It is saved to your settings, so it
  survives leaving the wizard and is re-applied on the next open.
- **Username Watch** — open it from its own main-menu button, add a taken name,
  and get an uppercase alert when a check confirms it free. The first check
  starts within about a second; the default repeat interval is 15 seconds per
  name. Telegram provides no username-release event, so one-second polling cannot
  be guaranteed. Checks share a paced worker; with many watches or a Telegram
  rate-limit, the interval can stretch. The screen shows each name's last check
  and result, and lets you check or remove it.

> Two honest notes. Short names are almost all taken, so raising the length
> matters. And most candidates are already owned — that is what makes the free
> ones valuable.

#### The verification engine: one call, and only the right one

Telegram rate-limits everything here, and the two available methods are not
interchangeable. The engine is built around that distinction.

**`account.checkUsername` is the availability verdict.** The API documentation
describes it as the method that *"validates a username and checks availability"*,
and it is the only call that separates all four real outcomes:

| Answer | Meaning |
|---|---|
| `boolTrue` | free — claimable right now |
| `USERNAME_OCCUPIED` | taken |
| `USERNAME_PURCHASE_AVAILABLE` | for sale on [fragment.com](https://fragment.com) — not free, but **buyable**, which the bot reports instead of a bare "taken" |
| `USERNAME_INVALID` | reserved, cooling down, or otherwise not assignable |

It is also **user-only** — "Only users can use this method" — which is why the
bot session pool cannot help with availability at all.

**`contacts.resolveUsername` is not used for availability.** The documentation
describes it as *"resolve a @username to get peer info"*: a different question.
It cannot tell a reserved name from a free one, so running it as well cost a
second call per candidate and bought no extra certainty. It is still used for the
single-name *lookup* screen, where the entity title it returns is worth showing.

So one candidate costs **one** call, not two — and the four outcomes above come
back from that single answer.

**Local filtering happens before Telegram is ever asked.** Length and charset are
validated locally, the taste gates (quality floor, premium criteria, mask) reject
candidates for free, and the public `t.me` page screens out most taken names with
a plain HTTP GET that spends no quota at all. Only what survives that reaches the
API.

**Verdicts are cached, with a TTL per outcome.** A taken name stays taken and a
reserved one stays reserved, so those are remembered for a day — and a stale
"taken" can only ever cost a missed candidate, never a false "free". A *free*
verdict is remembered for 60 seconds only, because somebody can claim the name
within minutes. "We do not know" is never cached: that would turn a temporary
outage into a permanent wrong answer.

**A throttle is waited out, never reported.** If the session is rate-limited the
search holds on and asks about the very same name again, and the progress screen
says so. Stopping with "Telegram is limiting us" is the one answer the product
must never give, because it is not a result. The only path to that message is
`MAX_SEARCH_SECONDS` (default 240) running out.

**A stock of already-verified names.** While the bot is idle a background
harvester proves names free and stores them, so a search can serve one after a
single re-confirmation instead of paying for a whole hunt. A stored name is
*never* handed over on the strength of the old verdict — if Telegram no longer
answers "claimable" it is dropped and the search carries on. Tune it with
`NAME_STOCK_TARGET` (0 disables), `NAME_STOCK_INTERVAL`, `NAME_STOCK_TTL` and
`NAME_STOCK_HARVEST_SECONDS`.

##### What actually limits throughput

Since `account.checkUsername` is both the verdict and user-only, **the user
session is the ceiling on how many verified names per minute the bot can
produce** — not the bot pool, and not the number of bot tokens. On one account
that is roughly 20 per minute at the default `USER_SESSION_DELAY=3`.

To go faster, either lower `USER_SESSION_DELAY` (the session parks itself on a
`FloodWait`, so pushing too far degrades rather than breaks) or add accounts —
each one adds its own quota:

```
MTPROTO_USER_SESSIONS=username_scanner_user2,username_scanner_user3
```

Create each with `python scripts/login_user_steps.py --name <base> send <phone>`.

### Premium verdict
There is no 0-100 score any more. Every name is judged on **five yes/no
criteria** and shown as **N/5**, because that is what a buyer actually pays for:

| Criterion | Passes when |
|---|---|
| No digits | the handle contains no `0-9` |
| No separators | no `-` or `_` |
| Collectible length | 4 to 7 characters |
| Readable | clean, sayable letter flow |
| Real dictionary word | the whole handle is an English word |

5/5 clears every gate; 0/5 fails all five no matter how "average" it looks. The
bot never offers a name that clears fewer than three of the five.

### Check a list
Paste up to 25 usernames, one per line or comma separated. The bot scans them
and returns **only the free ones, ranked by the premium verdict** — a filtered
answer instead of a wall of results.

### Instant check
`/rate moged` returns the same five-criteria verdict a search result shows, and
**costs no search attempt** — it is computed from the string alone, with no
Telegram lookup.

### Top finds
A leaderboard of the best free names found by everyone using the bot, computed
from the real check history. Not a curated list — it is what people actually
found.

### Favourites
Press **Save** on any result to keep it. Favourites are sorted by the premium
verdict and removable with one tap. Capped at 50 per user.

### Achievements
Eleven achievements, every one computed from rows that already exist in the
database - no counters are invented, and each shows its own progress:

| Achievement | Unlocks on |
|---|---|
| First free name | 1 free name found |
| 10 / 50 free names | milestone counts |
| First collectible | a collectible lookup |
| First username watch | adding an exact username |
| Watch alert | a check confirms it free |
| First battle / Battle won | duels |
| A perfect 100 | a name scoring 100 |
| 100 checks | volume |
| 10 favourites | collection |

### Username Watch
The Watch screen is a separate main-menu destination. It supports up to ten
exact usernames per user and shows the last check and last result. A check that
cannot confirm availability is recorded as inconclusive; it never triggers a
"free" alert. The background worker checks due names sequentially with a shared
request delay and retries them on the next interval.
### Profile
Your Telegram id and username, privilege, language, join date, and real
activity: checks, searches, active username watches, battles and your best find.

### Username Battle
Two usernames, **five criteria that can actually be measured**, each scored out
of 10, averaged into a total:

| Criterion | What decides it |
|---|---|
| Length | shorter wins |
| Digits | fewer wins |
| Symbols | underscores and separators hurt |
| Readability | consonant/vowel alternation |
| Status | collectible (10) > taken (7) > free (3) |

The breakdown is shown for both sides so the verdict is auditable. "Better" is
a scoring model, not a valuation.

Two modes:
- **Manual duel** - enter your username and the rival's, get the result.
- **Send a challenge** - the bot opens Telegram's own chat picker. Choose any
  chat it is already in, and the challenge is posted there with an accept
  button. Whoever taps it becomes the rival, and the comparison runs in that
  same chat where everyone can see the result.

> The picker only lists chats the bot is already a member of, because it has to
> be able to post there. No BotFather setup is needed.

### Support
An FAQ of the five questions that actually come up, plus a button that opens a
direct chat with the developer (`SUPPORT_USERNAME`, default `mogeds2`).

### Settings
Defaults for the search wizard - length, digits and the saved **mask** - plus
the language. The old basic/collectible/all-in-one switch and the rating filter
are gone: the search now hunts one kind of name (beautiful, unoccupied,
resale-worthy) and the bot applies its own quality criteria.

The mask is stored in your settings, not only in the session: leaving the wizard
via **Main menu** no longer drops it, and it is re-applied the next time the
search screen opens.

### Daily Drop
A personal hunting service. Once a day (09:00 local) the bot runs **one search**
with your saved settings and sends the result here - a fresh name finds you
without opening the bot. The **Daily Drop** screen in Settings explains it,
shows the next run, toggles it on/off and offers **Get one now** so you can see
it work immediately. The delivered message carries the Daily Drop banner.

## Language

The very first thing after `/start` is the language picker. Nothing else is
shown until it is answered — the whole onboarding and the entire interface run
in the chosen language. It can be changed at any time in **Settings**.

Shipped languages: **Русский**, **English**. Adding another is one dict in
`app/services/i18n.py` — every user-visible string in the project goes through
`t(lang, "key")`, and a test enforces that all languages have identical key
sets.

## Onboarding applies to everyone

Administrators are **not** exempt: they pass the language picker, the captcha,
the channel and the chat like any other user. `/admin` is gated too, so an
operator who has not completed onboarding cannot open the panel. The admin role
only grants the admin *sections* once access is granted.

## 1. Requirements

| Component  | Version        |
|------------|----------------|
| Python     | 3.12+          |
| aiogram    | 3.27+ (button `style` requires it) |
| Database   | SQLite (zero setup, default) or PostgreSQL 14+ |
| Redis      | 6+ (optional, strongly recommended) |
| MTProto    | Telethon session (required for definitive availability) |

SQLite is the default and needs nothing installed — the bot creates
`username_scanner.db` next to the project on first start. Switch to PostgreSQL
by changing one line in `.env` (§7).

Redis is optional: without it the bot still runs, just without caching.
MTProto is optional but recommended — see §11.

## 0. Fastest path (no Docker, no PostgreSQL)

```bash
pip install -r requirements.txt
cp .env.example .env      # fill BOT_TOKEN, ADMIN_IDS, REQUIRED_*
python scripts/verify_setup.py    # confirms everything actually works
python -m app.main
```

`verify_setup.py` is the single most useful command here: it checks the token,
the database, the channel and chat, that the bot is an administrator of both,
and whether the configured admins will pass the gate. Run it before the bot
whenever something looks wrong.

## 2. Installation

```bash
cd username_scanner

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## 3. Create the bot in BotFather

1. Open [@BotFather](https://t.me/BotFather).
2. `/newbot`, pick a name and a username ending in `bot`.
3. Copy the token into `BOT_TOKEN` in `.env`.
4. `/setprivacy` is not required — the bot only reads messages addressed to it.

## 4. API_ID / API_HASH

1. Go to <https://my.telegram.org> → **API development tools**.
2. Create an application (any name; platform "Desktop").
3. Put `api_id` and `api_hash` into `.env`.

These are secrets. They are never logged and never editable from the bot.

## 5. Required subscriptions

The onboarding gate shows **one screen listing every required channel/chat at
once**, each with a "Subscribe" button (its invite link) and its own
**"I subscribed"** button. Pressing it makes the bot re-query Telegram — the
click itself is never trusted.

Configure any number of them with a JSON list (preferred):

```
REQUIRED_SUBSCRIPTIONS=[{"key":"main","title":"Main channel","id":-1001234567890,"invite_url":"https://t.me/+AbCdEfGhIjKl"},{"key":"chat","title":"Community chat","id":-1009876543210,"invite_url":"https://t.me/+HoM2axfR_2g1OTYy"},{"key":"extra","title":"Second channel","id":-1003732479316,"invite_url":"https://t.me/+MyreACukC0xmOTUy"}]
```

Each entry: `key` (opaque id used in the callback), `title` (shown to the user),
`id` (numeric `-100...` id, preferred), `username` (fallback) and `invite_url`
(what the Subscribe button points at). For a **private** channel there is no
`@username`, so set the numeric id and the invite link.

Add the bot as an **administrator** of every channel and an **administrator of
supergroups** — otherwise Telegram refuses `getChatMember` and the gate cannot
be verified.

#### Pending join requests count as a subscription

A **private** channel approves join requests by hand, and approval does not
always happen immediately. Waiting for a human to tap Approve would leave a user
who has already done their part stuck on the gate — so a **pending request is
treated as a subscription** and lets them through.

Two sources, cheapest and most certain first:

1. **The update Telegram pushes to the bot.** When the bot is an administrator
   of the channel it receives `chat_join_request`, which is remembered in the
   `join_requests` table. This needs nothing but admin rights and is instant.
2. **The request queue itself**, read over MTProto. This is what covers a request
   sent while the bot was offline (startup drops pending updates), or before this
   feature existed. Note that `messages.getChatInviteImporters` is refused to
   **bots** outright (`BotMethodInvalidError`, verified live), so this runs on
   the **user session** — the same login the claimability gate uses — and that
   account has to be an administrator of the channel.

Run `python scripts/check_join_requests.py` to see whether the user session can
read each channel's request queue, and how many requests are waiting.

The click is never trusted on its own: every gate check re-reads the record (and
the queue, when it can) rather than believing a button. A failure to read is
never read as "the request exists", or a stranger would be let in. A request
that is never approved — or is declined — stops counting after
`JOIN_REQUEST_TTL` (default 24 h); lower it if your admins decline requests and
you want a declined request to expire sooner.

When `REQUIRED_SUBSCRIPTIONS` is empty, the legacy pair below is used instead,
so an existing `.env` keeps working unchanged. Leave everything empty to skip
the step entirely.

> Do not guess these numbers. After the MTProto session exists, run
> `python scripts/list_ids.py` — it prints your user id plus every channel and
> group you belong to, already formatted as `.env` lines.

## 6. Legacy: REQUIRED_CHANNEL_* / REQUIRED_CHAT_*

Kept for backward compatibility with older deployments:

```
REQUIRED_CHANNEL_ID=-1001234567890
REQUIRED_CHANNEL_USERNAME=my_channel
REQUIRED_CHANNEL_INVITE_URL=https://t.me/+AbCdEfGhIjKl
REQUIRED_CHAT_ID=-1009876543210
REQUIRED_CHAT_USERNAME=my_chat
REQUIRED_CHAT_INVITE_URL=https://t.me/+HoM2axfR_2g1OTYy
```

Either `_ID` or `_USERNAME` is enough; the id is preferred and is required for
private channels.

Channel and chat are independent settings. Leave both empty to skip the step.

> The bot must be an administrator of both, otherwise Telegram refuses
> `getChatMember` and the gate cannot be verified.

## 7. Database

Default — SQLite, nothing to install:

```
DATABASE_URL=sqlite+aiosqlite:///./username_scanner.db
```

Production — PostgreSQL, easiest via Docker:

```bash
docker compose up -d postgres
```

```
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

Or point at an existing server. Tables are created automatically on first
start, for both backends.

## 8. Redis

```bash
docker compose up -d redis
```

```
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
```

Set `REDIS_ENABLED=false` if you do not want a cache. The bot degrades
gracefully either way.

## 9. `.env`

```bash
cp .env.example .env
```

Then fill in at least `BOT_TOKEN`, `DATABASE_URL` and `ADMIN_IDS`.
Every option is documented inline in `.env.example`.

## 10. First run

```bash
python -m app.main
```

Expected log lines:

```
database ready
redis connected            # or: redis unavailable, continuing without cache
mtproto connected and authorised   # or a warning
bot is up, polling
```

If `BOT_TOKEN` is empty the process exits with code 2; if PostgreSQL is
unreachable it exits with code 3. Both are logged with the reason.

## 11. MTProto session

Without it, the bot can still prove a username is **occupied**, but a name that
resolves to nothing stays `UNKNOWN` — because the Bot API cannot distinguish
"free" from "reserved".

Two ways to get `API_ID` / `API_HASH`:

**Your own (correct).** <https://my.telegram.org> → API development tools. If
the site errors out for your account, that is a known Telegram-side problem,
not something you configured wrong.

**Shared credentials (works, with caveats).** Telegram Desktop ships its own
pair in every binary, visible in its public source tree:

```
API_ID=2040
API_HASH=b18441a1ff607e10a989891a5462e627
```

Verified to be accepted by Telegram's servers. What this costs you: the id is
shared by a very large number of third-party clients, so Telegram may apply
rate limits or extra verification at login, and using another application's
credentials is against Telegram's ToS. Fine for a personal tool; not something
to build a business on.

**The phone login is now optional — bot auto-login is the default.** As long
as `BOT_TOKEN` is set, the bot authorises its MTProto session **as the bot
itself** using its own token on every startup (`MtprotoClient.start()`). No
phone number, no login code, nothing interactive. Telegram's availability answer
comes from `contacts.resolveUsername`, which a bot session can call directly —
that is all the search pipeline needs.

If the session file is missing or gets wiped (for example by an aborted manual
login), the bot **self-heals**: it drops the stale session and re-authorises as
the bot by token again. The "30 checked, none confirmed" outage that a dead
session used to cause no longer needs a human to fix it.

```bash
python scripts/login_mtproto.py --status   # show which account the session belongs to
```

`scripts/login_mtproto.py` is now only for inspecting the session, or — if you
specifically want a *user* session (see below) — doing an interactive phone
login with `--user`.

### Making "free" mean "claimable" (optional user session)

A **bot** cannot call `account.checkUsername` (Telegram answers
`BotMethodInvalidError`), and `contacts.resolveUsername` alone is not enough:
Telegram also answers `USERNAME_NOT_OCCUPIED` for names it will then *refuse to
assign* (reserved, recently-released cooldown, anti-abuse). A bot session
therefore reports some names as free that the app rejects with "incorrect
username" at claim time.

The only method that separates "unowned" from "unassignable" is the user-only
`account.checkUsername`. To use it, log in a **user** account (a spare one is
fine) into a **separate** session file:

```bash
python scripts/login_mtproto.py --user          # phone + code -> username_scanner_user.session
python scripts/login_mtproto.py --user --status # confirm it is a user, not a bot
```

On startup the bot loads that session automatically and gates every "free"
verdict through `checkUsername`: a name Telegram would not assign is skipped and
the search keeps hunting. Without the file the engine stays best-effort, exactly
as before. The user session is only used for this check — the bot's own
`resolveUsername` traffic is unaffected, and the two sessions use different
accounts.

**If you would rather skip MTProto entirely**, set:

```
ALLOW_BOT_API_AVAILABILITY=true
```

The bot is then fully functional using only the Bot API: occupied usernames are
detected definitively, and "chat not found" is treated as AVAILABLE. It is
lower confidence — that is exactly why it is opt-in.

## 11b. Collector tools

**Appraisal — `/appraise love`** (or the *Appraise a name* button). One answer:
is it claimable right now, is it on Fragment and at what price, what comparable
names of the same length are asking, a rarity score, and a trademark warning if
the handle matches a known brand. Availability comes from Telegram, prices from
Fragment — nothing is estimated, and it says "not financial advice".

**Comparables.** `FragmentClient.market_stats(length)` aggregates the *live*
Fragment listings by name length (low / median / high). It is asking price, not
sold price, and the UI labels it that way.

**Portfolio.** Add names you own; the bot keeps their latest Fragment value and
shows it on one screen. *Refresh* re-reads every holding from Fragment.

**Listing sniper.** On the Watch screen, *Watch listings* takes a keyword and
pings you when a **new** matching collectible appears on Fragment (the first
sweep only records a baseline, so you are never spammed with the existing set).
Watching a single name on Fragment (price / listed) is also available.

**Checker account pool.** One user account cannot carry every check without
FloodWait. Set `MTPROTO_USER_SESSIONS` to a comma-separated list of session base
names and the engine rotates across them, parking a rate-limited one and using
the next. Create each with:

```bash
python scripts/login_user_steps.py --name username_scanner_user2 send +7999...
python scripts/login_user_steps.py --name username_scanner_user2 sign 12345
```

## 12. Running the bot

```bash
python -m app.main
```

> **Only one instance may run per bot token.** Telegram allows a single
> `getUpdates` consumer; a second one causes `TelegramConflictError` and the two
> processes take turns replying. If an older interface ever flickers back, that
> is the cause — the bot now refuses to start a second copy and tells you so
> (exit code 5). Check the build stamp in Admin → System to confirm which code
> is live.

Run it under a process manager in production (systemd, supervisord, Docker).
The bot uses long polling; no public URL is needed.

## 13. Admin setup

Put your Telegram ID in `.env`:

```
ADMIN_IDS=123456789,987654321
```

Everyone listed becomes **SUPERADMIN** (full access). On the next `/start` the
privilege is written to the database automatically.

Roles:

| Role       | Can do                                                        |
|------------|---------------------------------------------------------------|
| SUPERADMIN | everything                                                    |
| ADMIN      | users, restrictions, privileges, statistics, logs, system     |
| MODERATOR  | blacklist and temporary restrictions only                     |

Open the panel with `/admin`. Available sections: Users, Blacklist,
Restrictions, Privileges, Statistics, Search Logs, Access Settings, Bot
Settings, System, Admin Logs.

Admins bypass the onboarding gate. Every admin action is written to
`admin_actions` with the actor, target, reason and timestamp.

## 14. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `BOT_TOKEN is not set` (exit 2) | Fill `BOT_TOKEN` in `.env`. |
| `Telegram rejected BOT_TOKEN` (exit 4) | The token is wrong or was revoked — re-copy it from BotFather. |
| `PostgreSQL is unreachable` (exit 3) | Is the container up? Check `DATABASE_URL`. |
| Every check says `Unknown` | MTProto session is missing or not authorised. The bot self-heals by re-authorising as the bot via `BOT_TOKEN` on restart; if it keeps happening, check `API_ID`/`API_HASH`/`BOT_TOKEN`, or set `ALLOW_BOT_API_AVAILABILITY=true`. |
| Channel verify always fails | The bot is not an administrator of the channel/chat, or `REQUIRED_*_ID` points at the wrong chat. |
| `Collectible engine is not configured` | Set `FRAGMENT_ENABLED=true`. Fragment has no public API; the lookup is a best-effort page read. |
| Checks are slow | That is the rate limiter working. Lower `REQUEST_DELAY` only if you accept FloodWait risk. |
| `Redis unavailable` | The bot keeps running without cache. Check `REDIS_URL`. |
| Bot shows a generic error | The real traceback is in the log — the user never sees it. |

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

307 tests. The suite drives the real dispatcher, middlewares, routers and
keyboards against a fake Telegram session — no network, no token. It covers the
full onboarding flow (including wrong, expired and exhausted CAPTCHAs),
access-guard bypass attempts, bans, temporary restrictions, the three check
modes, scanning, history, settings, both languages, the language picker,
HTML-injection safety, the button-style palette, the availability decision
table, the fact that admins also pass the gate, that no internal term ever
reaches a user-facing string, and that every menu button actually responds.

Two of those tests exist because a button shipped that did nothing at all:

- **Dead-button sweep** - walks the real keyboards screen by screen and presses
  every `callback_data`, asserting each one produces a visible screen or a
  toast. Adding a button without a handler now fails the build.
- **Keyboard inventory** - every keyboard factory in the project is listed in
  one table, so the design rules (colours, icons, plain labels) apply to all of
  them rather than to whatever someone remembered to include.

Both are lists, and a list is only as good as its upkeep: if you add a keyboard
or a screen, add it there too.

## Project structure

```
username_scanner/
├── app/
│   ├── bot/
│   │   ├── handlers/        start, language, captcha, subscription, finder,
│   │   │                    battle, profile, support, extras, username,
│   │   │                    search, history, settings, admin
│   │   ├── keyboards/       inline keyboards, button styles, callback contract
│   │   ├── middlewares/     database, access guard, admin guard, errors
│   │   ├── states/          FSM states
│   │   ├── gate.py          shared access screens
│   │   └── texts.py         all user-visible rendering
│   ├── telegram/            bot_api, mtproto, public_page, username_checker
│   ├── collectible/         checker, fragment
│   ├── search/              pattern, finder, traps, battle, generator, scanner
│   ├── database/            models, database, repository
│   ├── cache/               redis cache with graceful degradation
│   ├── services/            access, captcha, i18n, user, admin, statistics,
│   │                        achievements, runtime_config, emoji
│   ├── utils/               username, enums, results, ratelimit, singleton,
│   │                        buildinfo, logging
│   ├── config.py
│   └── main.py
├── start.bat                  launcher (start.bat verify runs the doctor)
├── login.bat                  one-time MTProto login
├── scripts/login_mtproto.py   phone login for MTProto (--force to redo, --status to inspect)
├── scripts/find_emoji.py      resolve + verify custom emoji ids
├── scripts/list_ids.py        prints every ID you need for .env
├── scripts/verify_setup.py    checks the whole .env before you start
├── scripts/check_username.py  check usernames from the CLI
├── tests/
├── .env.example
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Guards

A few invariants are enforced by tests rather than by discipline, because each
one has already been broken once:

| Guard | Prevents |
|---|---|
| Every menu button responds | A button whose callback no handler matches doing nothing at all |
| Router list is shared with production | A new router silently missing from the test environment |
| No internal term in user text | `.env`, `MTProto`, `login.bat` and raw source codes leaking into a message |
| Every config key has an accessor | A setting exposed in the admin panel that the code cannot read |
| Only supported button styles | `ButtonStyle.LINK`, which Telegram rejects |
| Row layout is consistent | A row mixing iconed and plain buttons |
| Row layout is consistent | A row mixing iconed and plain buttons |
| Translation parity | A key added to one language and forgotten in another |

## Design notes

**Colour encodes consequence, and nothing else.** Telegram gives an inline
button exactly three colours, which is the hard limit. So colour is not asked to
make a menu expressive — it says one thing:

| role | style | colour | used for |
|---|---|---|---|
| `POSITIVE` | `success` | green | gives the user something good, or confirms |
| `NAVIGATE` | `primary` | blue | navigation and neutral actions |
| `DESTRUCTIVE` | `danger` | red | removes, blocks, restricts, or is the admin area |
| `SECONDARY` | *(none)* | default | back, main menu, meta |

A screen gets **one** dominant colour. One green call to action reads as a
hierarchy; four different colours read as a rainbow. All of it lives in
`app/bot/keyboards/design.py`, and a test rejects any style that does not come
from those tokens.

aiogram also exposes `ButtonStyle.LINK`, but Telegram rejects it for inline
buttons with `Invalid button style specified` — a test enforces that too.

**Icons carry the identity.** Every icon is a real Telegram custom emoji from
`CUSTOM_EMOJI_IDS`, so the whole interface renders in one visual family. Three
layout rules keep it looking deliberate, all enforced by tests:

1. **A row is either fully iconed or fully plain.** Mixing inside a row is the
   single biggest source of "this looks unfinished".
2. **Value pickers are plain.** Numbers are data, not actions.
3. **A row either repeats one icon or uses distinct ones.** `10 min / 1 hour /
   24 hours` share a stopwatch on purpose — same action, different parameter.
   A row mixing both reads as an accident.

The Unicode prefix is dropped when a real custom-emoji id is configured, so buttons and message
text render as **premium emoji**. This requires Telegram Premium on the bot
owner's account (or a Fragment-purchased username); without it the plain
Unicode glyph is used automatically and nothing breaks.

`scripts/find_emoji.py` resolves and verifies ids for you — every candidate is
validated with `getCustomEmojiStickers`, because a single bogus id makes
Telegram reject the entire message.

**Every string is localised.** Nothing user-visible is hardcoded in handlers;
they call `t(lang, "key")`. Language is resolved per user in the middleware and
injected into handlers as a `lang` argument.

**`UNKNOWN` is not `AVAILABLE`.** A username is only reported as free when
MTProto says nobody owns it. Without MTProto the Bot API is *not* enough: it
cannot resolve usernames owned by personal accounts at all and answers "chat not
found" for them, which is indistinguishable from free. The public preview page
is therefore used as an independent confirmation, and only a confirmed-free name
may be reported as AVAILABLE (and only with `ALLOW_BOT_API_AVAILABILITY=true`).

**Telegram has two ways of saying "free".** `contacts.resolveUsername` raises
`USERNAME_NOT_OCCUPIED` for a handle nobody owns — and also `USERNAME_INVALID`,
which Telethon documents as *"Nobody is using this username, or the username is
unacceptable. If the latter, it must match `[a-zA-Z][\w\d]{3,30}[a-zA-Z\d]`"*.
A handle that matches that shape cannot be the latter, so for the names the bot
generates `USERNAME_INVALID` is simply the other way Telegram says "free".
Treating it as an error made the search discard real, free names — which is why
short searches ended with "everything is taken". `USERNAME_NOT_OCCUPIED` and
`USERNAME_INVALID` (for a valid handle) both map to AVAILABLE; a genuinely
malformed handle still maps to INVALID and is skipped.

**Callbacks are not trusted.** Every callback re-runs `AccessGuard` against the
database. Stale buttons, forged admin payloads and direct `/check` calls are all
gated. CAPTCHA answers never leave the server.

**Nothing is faked.** No invented Fragment prices, no made-up statistics, no
placeholder owners. When a source is unavailable the answer is `UNKNOWN`, and
the UI says so.

**Failures degrade, they do not crash.** Redis down → no cache. Fragment down →
basic checks keep working. Telegram FloodWait → the whole queue pauses and
resumes.
