# Moving usesignals.app's engine from Railway to Render

The engine runs on Render from `render.yaml`. Moving it means three things:
- create the service,
- copy the store over (follows, alerts sent, the trader directory, the Worth following result),
- point usesignals.app at it.

Telegram alerts stay off on Render until the switch, so only one bot ever runs. Do steps 4–8 back to back: anything
Railway writes after the copy (a new follow, an alert) doesn't reach Render.

## 1. Create the service (once)

In Render, choose New → Blueprint, then pick `uselayer/signals`. Render reads `render.yaml` and asks for the keys:

- `LAYER_API_KEY` and `SIGNALS_METRICS_KEY`: new values. Railway's security notice says to replace them.
- `USELAYER_POLYGON_RPC`: a new value if its URL holds a provider key; otherwise the same one.
- `CLERK_PUBLISHABLE_KEY` and `SIGNALS_POSTHOG_KEY`: the same values. Both are public by design.
- `TELEGRAM_BOT_TOKEN`: leave it empty for now.

Create it and wait until the deploy says Live. Note two things:
- its service id (`srv-…`),
- its address (`https://signals-….onrender.com`).

## 2. Let your machine reach it over SSH (once)

In Account settings → SSH Public Keys, add `~/.ssh/id_ed25519.pub` (`pbcopy < ~/.ssh/id_ed25519.pub`). The service's
Connect → SSH tab shows its address, `srv-…@ssh.oregon.render.com`.

## 3. Check it answers

```
curl -s https://signals-….onrender.com/api/config
```

## 4. Copy the store out of Railway

```
railway ssh --service signals -i ~/.ssh/railway_research_key -- python3 - < deploy/render/export.py > signals-store.b64
```

It reads only, and finishes with a `store copied: … sha256 …` line. A database whose copy fails its check stops the
copy instead of writing a broken one.

## 5. Copy it into Render

```
ssh srv-…@ssh.oregon.render.com 'mkdir -p /data/incoming && base64 -d | tar xzf - -C /data/incoming && touch /data/incoming/.ready && ls -la /data/incoming' < signals-store.b64
```

It waits in `/data/incoming`, untouched by the engine still running there.

## 6. Restart the service on Render

In the dashboard, choose Manual Deploy → Restart service. On start, `deploy/start.sh` moves each copied file over the
one of its name before anything opens it, with that database's journal files. The logs say
`Copied store: moved directory.db into /data`, and the same for each file.

## 7. Check it holds the store

On `https://signals-….onrender.com`, the Leaderboard lists traders and a trader page opens.

## 8. Point usesignals.app at Render

In `web/vercel.json`, change the last rewrite's destination to `https://signals-….onrender.com/$1`. Then, from `web/`:

```
vercel deploy --prod
```

Check `https://usesignals.app/api/config` answers.

## 9. Turn alerts on, on Render only

In BotFather, `/revoke` the bot's token: Railway's bot stops. Take the new token, set it as `TELEGRAM_BOT_TOKEN` in
the Render service's Environment, and save; that redeploys it. Same bot, same chats: followers keep their alerts.

## 10. Afterwards

After a day on Render, remove the Railway service, along with its volume. Revoke the old `LAYER_API_KEY` and
`SIGNALS_METRICS_KEY`.

To deploy, choose Manual Deploy → Deploy latest commit, or run `render deploys create srv-…`. Commits never deploy on
their own.
