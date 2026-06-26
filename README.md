# Build an AI Workflow Diagnoser — Step by Step

A beginner-friendly tutorial. By the end you'll have built and deployed a small
AI web app: a chat box where someone describes a task they repeat at work, and
an AI replies with the repeatable steps, automation opportunities, and a
suggested MVP.

You'll write **two tiny Python files** and learn the single most important idea
in AI apps: **keep your secret API key on the server, never in the frontend.**

```
  Browser (a person types)
        |
        v
  app_frontend.py   ← Gradio chat UI         (no secret here)
        |  POST /diagnose
        v
  main.py           ← FastAPI backend         (holds GROQ_API_KEY)
        |  calls the LLM
        v
  Groq (the AI model)
```

No prior experience with FastAPI, Gradio, or LLM APIs is needed. You just need
to be comfortable running a few commands in a terminal.

---

## What you'll need

- **Python 3.9 or newer.** Check with `python --version` (or `python3 --version`).
- **A free Groq API key.** Groq runs open LLMs (like Llama) very fast. Sign up
  at [console.groq.com](https://console.groq.com), then create an API key. Keep
  it secret — it's tied to your account.
- A terminal and a text editor.

> **What's an API key?** A password that lets your code talk to the AI service.
> Anyone who has it can spend on your account, so we never put it in code that
> runs in someone's browser.

---

## Step 0 — Set up your project folder

Create a folder and move into it:

```bash
mkdir workflow-diagnoser
cd workflow-diagnoser
```

It's good practice to use a **virtual environment** — an isolated sandbox for
this project's Python packages so they don't clash with anything else on your
machine:

```bash
python -m venv .venv
source .venv/bin/activate      # On Windows: .venv\Scripts\activate
```

You'll know it worked when your terminal prompt shows `(.venv)` at the start.

---

## Step 1 — List the libraries you need

Create a file called `requirements.txt`. This is just a shopping list of the
packages your app depends on:

```
fastapi
uvicorn
groq
gradio
requests
```

What each one does:

| Package    | Role                                                            |
| ---------- | -------------------------------------------------------------- |
| `fastapi`  | Builds the backend API (the part that holds the secret key)    |
| `uvicorn`  | The web server that runs your FastAPI app                      |
| `groq`     | Official client for talking to the Groq AI models             |
| `gradio`   | Builds the chat web UI with almost no code                     |
| `requests` | Lets the frontend send messages to the backend                |

Install them all at once:

```bash
pip install -r requirements.txt
```

---

## Step 2 — Build the backend (`main.py`)

The backend is the brain. It's the **only** part that knows your API key. It
exposes one endpoint, `/diagnose`, that takes a workflow description and returns
the AI's analysis.

Create `main.py`:

```python
import os

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from groq import Groq

# Read the secret key from the environment (never hard-code it!)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

app = FastAPI(title="Workflow Diagnoser API")


@app.get("/")
def read_root():
    # A tiny health check so you can confirm the server is alive
    return {"message": "Hello, builder"}


@app.post("/diagnose", response_class=PlainTextResponse)
def diagnose(body: dict):
    user_content = body.get("workflow_description", "")
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a workflow diagnosis assistant. Analyze the described workflow and "
                    "respond in plain text with repeatable steps, automation opportunities, and "
                    "a suggested MVP."
                ),
            },
            {"role": "user", "content": user_content},
        ],
    )
    return completion.choices[0].message.content
```

**What's happening here, line by line:**

- `os.environ.get("GROQ_API_KEY")` reads your key from an *environment
  variable* instead of writing it in the file. This keeps the secret out of
  your code (and out of GitHub).
- `app = FastAPI(...)` creates the web application.
- `@app.get("/")` defines a simple page you can open to check the server runs.
- `@app.post("/diagnose")` is the real endpoint. It receives JSON like
  `{"workflow_description": "..."}`, then asks the model to analyze it.
- The `messages` list is the AI conversation. The **system** message sets the
  AI's job; the **user** message is what the person typed.
- We return `completion.choices[0].message.content` — the model's text reply.

---

## Step 3 — Give the backend your key and run it

Tell your terminal the secret key (this lasts only for the current terminal
session):

```bash
export GROQ_API_KEY=your_key_here      # On Windows: set GROQ_API_KEY=your_key_here
```

Now start the backend:

```bash
uvicorn main:app --reload
```

`main:app` means "in `main.py`, use the variable named `app`." `--reload`
restarts the server automatically when you edit the file.

**Try it without any UI.** FastAPI gives you a free interactive page. Open your
browser to:

```
http://127.0.0.1:8000/docs
```

Click `POST /diagnose` → **Try it out**, paste this into the request body, and
hit **Execute**:

```json
{ "workflow_description": "Every Monday I copy sales numbers from email into a spreadsheet and send a summary." }
```

You should get back a plain-text diagnosis. 🎉 The backend works! Leave it
running and open a **second terminal** for the next step.

---

## Step 4 — Build the frontend (`app_frontend.py`)

The frontend is the chat box people actually use. It has **no API key**. When
someone sends a message, it forwards it to your backend and shows the reply.

Create `app_frontend.py`:

```python
import os
import gradio as gr
import requests

# Where the backend lives. Defaults to your local server for development.
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000/diagnose")


def diagnose(message, history):
    try:
        response = requests.post(
            BACKEND_URL,
            json={"workflow_description": message},
            timeout=60,
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        return f"Could not reach the backend.\n\n{e}"


demo = gr.ChatInterface(
    diagnose,
    title="Workflow Diagnoser",
    description="Describe one repeated task you do at work.",
)

if __name__ == "__main__":
    demo.launch()
```

**What's happening here:**

- `BACKEND_URL` points at your backend. Locally it's `127.0.0.1:8000`; in
  production you'll override it with an environment variable (Step 6).
- `diagnose(message, history)` is the function Gradio calls every time the user
  sends a message. It POSTs the message to the backend and returns the reply.
- The `try/except` shows a friendly error instead of crashing if the backend is
  unreachable.
- `gr.ChatInterface(...)` builds a full chat UI from that one function — no HTML
  or CSS required.

Run it (in your second terminal, with the backend still running in the first):

```bash
python app_frontend.py
```

Gradio prints a local URL like `http://127.0.0.1:7860`. Open it, type a task you
repeat at work, and watch the AI respond. You've built a working AI app!

---

## Step 5 — Why two files? (the key idea)

You could have crammed everything into one file. We didn't, on purpose:

- The **frontend** runs where users are (their browser, or a public Gradio
  page). Anything it knows, the world can see.
- The **backend** runs on a server you control. The API key lives only here.

So the secret stays safe, and you can swap or redeploy either half
independently. This frontend/backend split is how almost all real AI products
are structured.

---

## Step 6 — Deploy it, right-sized (find the real bottleneck)

It's perfect on localhost and useless to the world. The interesting question
isn't *how* to ship — it's *how big* to build. This is where most people
over-engineer: they reach for Kubernetes, autoscaling, a load balancer, Redis,
a queue… for an app nobody is using yet.

**Do the napkin math first.** Say we expect ~250 users, a few diagnoses each.
That's maybe 500–1,000 requests total, a few thousand short rows, a few
megabytes. Now hold that next to the free-tier ceilings:

| Layer | Free-tier ceiling that matters | Our 250-user load | Headroom |
| --- | --- | --- | --- |
| Supabase Postgres | ~500 MB (≈ 5M short messages) | a few MB | a rounding error |
| Supabase Auth | 50,000 monthly active users | 250 | ~0.5% of the ceiling |
| Groq LLM (`llama-3.3-70b-versatile`) | ~30 requests/min, ~1,000/day | 250 people clicking at once | **this is the one** |

**Conclusion, derived not asserted:** we need *none* of the things people
reach for. Over-engineering is paying in complexity for load you don't have.

**The limit that breaks you first is never the one you'd guess.** It isn't users
and it isn't storage. There are exactly two tripwires for this stack, and both
live *outside your own code*:

1. **The free database falls asleep** after ~7 days of no traffic and takes
   ~30 seconds to wake. That's an *operational* tripwire, not a scale one. The
   fix is a daily ping that keeps it warm, not a bigger plan.
2. **The LLM rate limit** is the one that bites in a real launch. ~30
   requests/min means if all 250 users press *diagnose* in the same minute,
   only 30 get through and the rest get a `429`. Your bottleneck is an external
   dependency. The fix is to throttle, queue, or upgrade *that one tier* — not
   to scale your box.

> Numbers move. Reconfirm on Groq's rate-limit docs and Supabase's pricing page
> before you architect around any specific cap.

Now deploy the two halves separately.

### Backend → Render

1. Push your code to GitHub.
2. On [Render](https://render.com): **New → Web Service** → connect your repo.
3. Runtime: **Python**. Start command:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
4. Under **Environment**, add three variables: `GROQ_API_KEY`, `SUPABASE_URL`,
   and `SUPABASE_SERVICE_ROLE_KEY` (the same values from your `.env`).
5. Deploy. Render gives you a URL like
   `https://your-service.onrender.com`. Your endpoint is that URL + `/diagnose`.

### Frontend → Hugging Face Spaces

1. On [Hugging Face](https://huggingface.co/spaces): **New Space** → SDK:
   **Gradio**.
2. Upload `app_frontend.py` and `requirements.txt`, and set the app file to
   `app_frontend.py`.
3. In the Space's **Settings → Variables**, add `BACKEND_URL` =
   `https://your-service.onrender.com/diagnose`.
4. The Space builds and gives you a public chat link to share.

Now anyone can use your app, and your key never leaves Render.

> **Keep it warm.** Free hosts and the free database both sleep on idle, so the
> first request after a quiet spell is slow. Before a live demo, hit the URL
> once to wake it. For the database's 7-day pause, a tiny daily cron that calls
> `/` is enough — you're mitigating the exact tripwire you just learned to name.

---

## Troubleshooting

- **`401` / authentication error from the backend** → `GROQ_API_KEY` isn't set,
  or is wrong. Re-run the `export` and restart `uvicorn`.
- **Frontend says "Could not reach the backend"** → the backend isn't running,
  or `BACKEND_URL` points to the wrong place. Confirm Step 3 still works.
- **`command not found: uvicorn`** → your virtual environment isn't active, or
  `pip install` didn't finish. Re-activate (`source .venv/bin/activate`) and
  reinstall.
- **Port already in use** → another process is on that port. Stop it, or run
  uvicorn on another port: `uvicorn main:app --reload --port 8001`.

---

## Step 7 — Give it a memory (Supabase database)

Right now the app forgets. Close the tab and the plan is gone, because it only
ever lived in RAM — in the browser tab and in the server process. This step
moves the plan onto **disk** in a real Postgres database (via Supabase), so it
survives a closed tab and a server restart.

```
  Browser → app_frontend.py → main.py ──calls──► Groq (the AI)
                                  │
                                  └──writes/reads rows──► Supabase (Postgres)
                                         (holds SUPABASE_SERVICE_ROLE_KEY)
```

The work is split into small, readable files. Read them in order:

1. **`DOMAIN_MODEL.md`** — the shape of what we store: two entities
   (`conversation`, `message`), their attributes, the one-to-many relationship,
   and an ER diagram. *Model it before you store it.*
2. **`db/01_schema.sql`** — the model as real tables, with a **foreign key** and
   a **check constraint**. Includes the "ghost message" demo where the database
   refuses a bad row on purpose.
3. **`db/02_auth.sql`** — add a `user_id` so we know *who owns* each conversation,
   and meet the JWT "passport."
4. **`db/03_policies.sql`** — Row-Level Security: the rule "only read your own
   rows" moves into the database itself, deny-by-default.

### Set it up

1. Create a free project at [supabase.com](https://supabase.com) (region close
   to you). Save the database password.
2. In the Supabase **SQL Editor**, run `db/01_schema.sql`, then `db/02_auth.sql`,
   then `db/03_policies.sql`, in order.
3. Copy `.env.example` to `.env` and fill in `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY` (from **Settings → API**) alongside your
   `GROQ_API_KEY`.
4. Install the new libraries and run the backend:

   ```bash
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```

5. **Prove the memory survives.** Open `http://127.0.0.1:8000/docs`, run one
   `/diagnose`. Check the Supabase **Table Editor** — three new rows. Now stop
   the server (`Ctrl+C`), start it again, and call
   `GET /conversations/{conversation_id}/messages`. The messages are still there.

> **The two keys.** `service_role` is the master key — it lives only in your
> backend's `.env` / Render env vars and bypasses every rule. `anon` is the
> public key meant for frontends; it is safe *only because* RLS guards every row.
> Never put `service_role` anywhere a browser can see it.

---

## Step 8 — See it working (observability)

It's live. Is it working? For whom? How fast? When it breaks at 2am, what do
you even look at? Right now: nothing. The Verifier's Rule, one level up — only
**ship what you can observe.**

And it needs **no new infrastructure.** The same Postgres is your analytics
warehouse. Run `db/04_events.sql` to add one `events` table, then every
`/diagnose` logs a row: latency, tokens, status, and how much Groq budget is
left (read straight from Groq's rate-limit header).

Two routes turn those rows into a live view:

- **`GET /metrics`** — one SELECT over the last 500 events, rolled up into four
  numbers: total diagnoses, how many got rate-limited (`429`), average latency,
  and Groq requests left this minute.
- **`GET /admin`** — a tiny HTML page that polls `/metrics` every 2 seconds.
  Put it on a projector and watch the numbers tick.

The `events` table has RLS on with **no** read policy for ordinary users, so it
stays private automatically — only your `service_role` backend can read it. When
a SELECT stops being enough, graduate to PostHog or Sentry. Not before.

The payoff: under load, Groq's ~30 req/min cap returns a `429`, your `/diagnose`
turns that into a graceful "you are in line", and the `429` count climbs on the
dashboard. You can *see* the bottleneck, name it, and turn the one right knob
(upgrade that single tier) — instead of blindly scaling a server that was never
the problem.

---

## Step 9 — One product, one keystroke (the reveal)

The architecture never moves — only what the product is *for*. The backend
ships **two** system prompts and a flag:

- `WORKFLOW_PROMPT` — diagnose a task you repeat at work (where we started).
- `JOURNEY_PROMPT` — diagnose where a builder is, the gap to where they want to
  go, and their single current bottleneck.

`PROMPT_MODE` picks one. Its boot default comes from an env var, but you flip it
**live, in memory, with no redeploy** (a redeploy risks a cold start at the
worst moment):

```bash
curl -X POST 'http://127.0.0.1:8000/admin/mode?mode=journey'
```

Same auth, same RLS, same deploy, same dashboard. Only the prompt changed. That
is the whole lesson: once you own the shape — a thin UI, a backend that guards
the secret, a model that thinks, a database that remembers, identity, privacy,
a public address, and eyes on it — changing what a product *does* is a one-line
change.

---

## Where to go next

- Change the **system prompt** in `main.py` to make the AI an expert in
  something else entirely.
- Try a different Groq model by editing the `model=` line.
- Add input validation, save past diagnoses, or style the Gradio UI with themes.

You've learned the core shape of an AI app: a thin UI, a backend that guards the
secret, and a model doing the thinking. Everything else is a variation on this.
