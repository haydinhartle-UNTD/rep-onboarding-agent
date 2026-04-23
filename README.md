# Rep Onboarding Agent

A FastAPI service that automates the final steps of solar rep onboarding:

1. Receives a webhook from Zapier (fired after Gmail account creation)
2. Uses Claude Computer Use to fill the installer's Typeform with the rep's info
3. Texts you an iMessage via Blooio confirming success or describing the failure

---

## Local dev setup

**Prerequisites:** Python 3.11+, Git

```bash
cd rep-onboarding-agent

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright's Chromium browser (only needed for real browser mode)
playwright install chromium

# Copy env file and fill in your values
cp .env.example .env
# Edit .env with your keys

# Start the server (auto-reloads on file changes)
uvicorn main:app --reload
```

Server runs at `http://localhost:8000`. Visit `http://localhost:8000/docs` for
the interactive API explorer.

---

## Railway deploy walkthrough

### 1. Install the Railway CLI

```bash
npm install -g @railway/cli
railway login
```

### 2. Create a GitHub repo and push the code

```bash
cd rep-onboarding-agent
git init
git add .
git commit -m "Initial commit"
git remote add origin git@github.com:haydinhartle-UNTD/rep-onboarding-agent.git
git push -u origin main
```

> Make sure the repo is **private** (set when creating it on GitHub).

### 3. Link to your Railway project

```bash
railway link
# Select your existing Railway project from the list
```

### 4. Set environment variables in Railway

In the Railway dashboard → your project → **Variables**, add all six:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | From console.anthropic.com |
| `BLOOIO_API_KEY` | From your Blooio dashboard |
| `NOTIFY_PHONE_NUMBER` | Your cell in E.164 format (e.g. `+16025551234`) |
| `INSTALLER_TYPEFORM_URL` | `https://form.typeform.com/to/trmZGOwt` |
| `ZAPIER_WEBHOOK_SECRET` | A long random string (generate below) |
| `MAX_AGENT_ITERATIONS` | `40` |

Generate a webhook secret:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Deploy

Railway auto-deploys on every push to `main`. To deploy manually:

```bash
railway up
```

Watch the build in the Railway dashboard. The first build takes ~3–4 minutes
(downloading the Playwright Docker base image).

### 6. Get your public URL

In the Railway dashboard → your service → **Settings** → **Domains** →
click **Generate Domain**. Copy the URL (e.g. `https://rep-onboarding-agent-production.up.railway.app`).

---

## Zapier webhook setup

In your existing onboarding Zap (after the Gmail creation step):

1. Add a new **Webhooks by Zapier** action → **POST**
2. **URL:** `https://<your-railway-domain>/webhook/rep-onboarding`
3. **Payload Type:** `json`
4. **Headers:**
   - Key: `X-Webhook-Secret`
   - Value: *(the same value you set in Railway)*
5. **Data (JSON body):**

```json
{
  "first_name": "{{first_name}}",
  "last_name": "{{last_name}}",
  "personal_email": "{{personal_email}}",
  "new_gmail": "{{new_gmail}}",
  "phone": "{{phone}}",
  "address": "{{address}}",
  "city": "{{city}}",
  "state": "{{state}}",
  "zip_code": "{{zip_code}}",
  "start_date": "{{start_date}}",
  "ghl_contact_id": "{{ghl_contact_id}}"
}
```

Replace the `{{placeholders}}` with your actual GHL field mappings from earlier
steps in the Zap.

---

## Test with curl

Replace `<railway-url>` and `<your-secret>` with your actual values:

```bash
curl -X POST https://<railway-url>/webhook/rep-onboarding \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <your-secret>" \
  -d '{
    "first_name": "Test",
    "last_name": "Rep",
    "personal_email": "test@gmail.com",
    "new_gmail": "test.rep@mycompany.com",
    "phone": "+16025551234",
    "address": "123 Main St",
    "city": "Phoenix",
    "state": "AZ",
    "zip_code": "85001",
    "start_date": "2026-05-01",
    "ghl_contact_id": "test-curl-001"
  }'
```

**Expected response:**
```json
{"status": "accepted", "message": "Onboarding started for Test Rep"}
```

**Expected iMessage within ~5 seconds:**
```
✅ Onboarding complete: Test Rep — STUB — browser not implemented. Pipeline verified OK.
```

---

## Troubleshooting

### Zapier gets a 401
- The `X-Webhook-Secret` header value doesn't match `ZAPIER_WEBHOOK_SECRET` in Railway.
- Double-check there are no trailing spaces in either value.
- Re-generate and re-set both if unsure.

### Agent times out / no iMessage arrives
- Check Railway logs (Dashboard → Deployments → latest → Logs).
- In stub mode this should be nearly instant. If it's hanging, the server may not be running — check the health check at `GET /`.
- In real browser mode: the agent has a 90-second hard timeout and 40-iteration cap.

### iMessage doesn't arrive
- Confirm `BLOOIO_API_KEY` and `NOTIFY_PHONE_NUMBER` are set in Railway.
- Check Railway logs for `send_imessage failed` lines.
- Test your Blooio key directly: `curl -X POST https://backend.blooio.com/v2/api/chats/+1xxx/messages -H "Authorization: Bearer <key>" -H "Content-Type: application/json" -d '{"text": "test"}'`

### Playwright crash (real browser mode)
- Look for `[browser] Action ... failed` in Railway logs.
- The agent receives a screenshot of the error state and tries to recover.
- If it consistently fails at the same step, the form may have changed — run a fresh stub test and compare the field list in the iMessage.

### Zapier retries the webhook
- The service dedupes on `ghl_contact_id + first + last` with a 10-minute TTL.
- A retry within 10 minutes returns `{"status": "duplicate"}` and no second form submission happens.
