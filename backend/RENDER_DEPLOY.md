## Render Deployment

This backend is ready to deploy to Render as a FastAPI web service.

### Start command

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

### Environment variables

Set these in Render:

- `BOT_TOKEN`
- `APOLLO_API_KEY`

### Deploy steps

1. Push the project to GitHub.
2. Open the Render dashboard.
3. Create a new Web Service.
4. Connect the GitHub repo.
5. If Render asks for a root directory, use `backend`.
6. Set the start command to:

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

7. Add the environment variables:
   `BOT_TOKEN`
   `APOLLO_API_KEY`
8. Deploy the service.

### After deployment

Copy the Render URL. It will look like:

```text
https://loqi-backend.onrender.com
```

### Telegram webhook

Set the webhook with:

```text
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<RENDER_URL>/webhook
```

Example:

```text
https://api.telegram.org/bot123456:ABCDEF/setWebhook?url=https://loqi-backend.onrender.com/webhook
```

### Validation

1. Visit:

```text
https://your-render-url/
```

It should return:

```text
Loqi backend running
```

2. Open the Telegram bot.
3. Send `/start`.

### If the bot does not respond

- Check Render logs.
- Make sure the webhook is set correctly.
- Make sure `BOT_TOKEN` and `APOLLO_API_KEY` are correct in Render.
