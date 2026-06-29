# APRS Status Board + Watch Commands

Replaces the old "post every hit" APRS feed with a **single pinned status
board** that's edited in place, plus Discord **slash commands** so anyone
can manage the watch list.

## Pieces

| Component | What it is | Trigger |
|-----------|-----------|---------|
| `aprs-to-discord` → Lambda **`HamPals-APRS-Watch`** | Board updater. Reads the watch list, queries aprs.fi, edits the one pinned board message. | EventBridge cron (~10 min) |
| `aprs-watch-commands` → Lambda **`HamPals-APRS-Commands`** | Slash-command handler (`/watch`, `/unwatch`, `/watchlist`). | Lambda **Function URL** = Discord "Interactions Endpoint URL" |
| DynamoDB **`evsrt-aprs-watch`** | The watch list: one item per `(callsign, user_id)` pair. | — |
| SSM param **`/evsrt/aprs/board_message_id`** | Stores the board message id so it persists across runs. | — |

The board is edited with the **webhook** itself (`PATCH /webhooks/{id}/{token}/messages/{message_id}`) — no bot token needed at runtime. A bot token is used only once, locally, to register the slash commands.

Region throughout: **us-east-1** (matches the existing functions).

---

## 1. DynamoDB table

```bash
aws dynamodb create-table \
  --table-name evsrt-aprs-watch \
  --attribute-definitions AttributeName=callsign,AttributeType=S AttributeName=user_id,AttributeType=S \
  --key-schema AttributeName=callsign,KeyType=HASH AttributeName=user_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

`callsign` is the enrolled token (e.g. `K3MGM-9`, `WZ1EEE*`); `user_id` is the Discord user who added it. A call stays on the board while ≥1 user watches it; only the user who added an entry can `/unwatch` it.

---

## 2. IAM roles

### Board updater (`HamPals-APRS-Watch`)
Needs: read the watch table, read/write the SSM param, write logs.

```bash
cat > board-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect":"Allow","Action":["dynamodb:Scan"],
     "Resource":"arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/evsrt-aprs-watch"},
    {"Effect":"Allow","Action":["ssm:GetParameter","ssm:PutParameter"],
     "Resource":"arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/evsrt/aprs/board_message_id"},
    {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
     "Resource":"arn:aws:logs:us-east-1:ACCOUNT_ID:*"}
  ]
}
JSON
# attach board-policy.json to the role HamPals-APRS-Watch already uses
aws iam put-role-policy --role-name HamPals-APRS-Watch-role \
  --policy-name aprs-board --policy-document file://board-policy.json
```

### Commands handler (`HamPals-APRS-Commands`)
Needs: read/write the watch table, write logs.

```bash
cat > commands-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect":"Allow","Action":["dynamodb:Scan","dynamodb:PutItem","dynamodb:DeleteItem"],
     "Resource":"arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/evsrt-aprs-watch"},
    {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
     "Resource":"arn:aws:logs:us-east-1:ACCOUNT_ID:*"}
  ]
}
JSON

# create the role + function (the board function already exists; this is the new one)
aws iam create-role --role-name HamPals-APRS-Commands-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam put-role-policy --role-name HamPals-APRS-Commands-role \
  --policy-name aprs-commands --policy-document file://commands-policy.json
```

---

## 3. Create the commands Lambda + Function URL

```bash
# placeholder zip; CI (deploy.yml) pushes real code on merge
echo 'def lambda_handler(e,c): return {}' > lambda_function.py && zip placeholder.zip lambda_function.py

aws lambda create-function --function-name HamPals-APRS-Commands \
  --runtime python3.11 --handler lambda_function.lambda_handler \
  --role arn:aws:iam::ACCOUNT_ID:role/HamPals-APRS-Commands-role \
  --timeout 10 --memory-size 256 \
  --zip-file fileb://placeholder.zip --region us-east-1

# public Function URL (Discord calls it unauthenticated; we verify the Ed25519 signature in code)
aws lambda create-function-url-config --function-name HamPals-APRS-Commands \
  --auth-type NONE --region us-east-1
aws lambda add-permission --function-name HamPals-APRS-Commands \
  --statement-id discord-url --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE --region us-east-1
# -> note the FunctionUrl it prints; that's the Interactions Endpoint URL
```

EventBridge cron for the board updater already exists for `HamPals-APRS-Watch`. If you ever need to recreate it:

```bash
aws events put-rule --name aprs-board-tick --schedule-expression 'rate(10 minutes)' --region us-east-1
aws lambda add-permission --function-name HamPals-APRS-Watch --statement-id evt \
  --action lambda:InvokeFunction --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:ACCOUNT_ID:rule/aprs-board-tick --region us-east-1
aws events put-targets --rule aprs-board-tick \
  --targets "Id"="board","Arn"="arn:aws:lambda:us-east-1:ACCOUNT_ID:function:HamPals-APRS-Watch" --region us-east-1
```

---

## 4. Environment variables

**`HamPals-APRS-Watch` (board updater):**

| Var | Value |
|-----|-------|
| `discord_webhook` | Webhook URL for the board's channel |
| `aprs_fi_api_key` | aprs.fi API key |
| `lookback_seconds` | optional, default `600` (the "active" window) |
| `watch_table` | optional, default `evsrt-aprs-watch` |
| `board_param` | optional, default `/evsrt/aprs/board_message_id` |

**`HamPals-APRS-Commands` (slash commands):**

| Var | Value |
|-----|-------|
| `discord_public_key` | Application **Public Key** (Discord dev portal → General Information) |
| `watch_table` | optional, default `evsrt-aprs-watch` |
| `max_callsigns` | optional, default `50` (cap on distinct watched calls) |

```bash
aws lambda update-function-configuration --function-name HamPals-APRS-Commands \
  --environment "Variables={discord_public_key=PUBLIC_KEY_HEX}" --region us-east-1
```

---

## 5. Discord setup

1. **Application** — https://discord.com/developers/applications → *New Application*. Copy the **Application ID** and **Public Key** (General Information).
2. **Bot** — *Bot* tab → add a bot → copy the **Bot Token** (used only for command registration below).
3. **Invite the bot** to the server with the `bot` + `applications.commands` scopes (OAuth2 URL Generator).
4. **Webhook** — in the board's channel: *Edit Channel → Integrations → Webhooks → New Webhook*; copy its URL into `discord_webhook`.
5. **Deploy** the commands Lambda (merge to `main`, CI pushes it) so the Function URL is live.
6. **Interactions Endpoint URL** — back in the dev portal (General Information), paste the Lambda Function URL. Discord sends a signed PING; the handler answers it, and Discord saves the URL only if verification passes. (So `discord_public_key` must be set first.)
7. **Register the commands:**
   ```bash
   cd aws/lambda/aprs-watch-commands
   DISCORD_APP_ID=...  DISCORD_BOT_TOKEN=...  DISCORD_GUILD_ID=<server id> \
     python3 register_commands.py
   ```
   With `DISCORD_GUILD_ID` set they appear instantly; without it they're global (~1h to propagate).
8. **Pin the board** — let the cron fire once (or invoke `HamPals-APRS-Watch` manually) so the board message posts, then right-click → Pin.

---

## How it behaves

- The board lists every watched callsign with a status dot: 🟢 active (heard within `lookback_seconds`), ⚪ idle (known but stale), ⚫ no APRS data — plus its `Via` (RF igate / DMR gateway / Internet) and an aprs.fi map link.
- Updated in place every cron tick; the channel stays a clean single board instead of a feed.
- If the board message is deleted, the next run recreates it and updates the stored id (you'll need to re-pin).
- `/watch K3MGM-9` (anyone) → appears on the next board update. `/unwatch` removes only your own entry. `/watchlist` shows the current set, flagging yours.
