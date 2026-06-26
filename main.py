import os
import time

from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from groq import Groq, RateLimitError
from supabase import create_client

# Read SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GROQ_API_KEY from the .env file
# into the environment. (On Render these come from the dashboard instead.)
load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Connect to the database. We use the SERVICE_ROLE key because this file runs on
# the server — the machine WE control. This key bypasses every rule, so it must
# never leave the server and never appear in the frontend. (The `anon` key is
# the public one; it is not used here.)
supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)

app = FastAPI(title="Workflow Diagnoser API")

@app.get("/")
def read_root():
    return {"message": "Hello, builder"}


def get_user_id(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """Who is asking? Read the identity from the JWT — never trust a claim in
    the request body.

    The frontend runs on a machine THEY control, so anything it *says* ("I am
    Aarav") can be forged. The JWT is a passport signed by Supabase: we hand the
    token back to Supabase, and it tells us the real user id.

    We keep this OPTIONAL so the thin L06 frontend (which sends no token) still
    works: no header -> no user_id. In production you would make it required by
    using `Header(...)` and rejecting a missing token. A *bad* token is always
    rejected.
    """
    if authorization is None:
        return None
    token = authorization.replace("Bearer ", "")
    res = supabase.auth.get_user(token)
    if res is None or res.user is None:
        raise HTTPException(status_code=401, detail="Who are you?")
    return res.user.id


# ---------------------------------------------------------------------------
#  Two prompts, one machine. The architecture never moves — only what the
#  product is FOR. Changing that is a one-line change, because we own the
#  shape now, not just the app. We ship BOTH prompts and flip a flag, so the
#  reveal is one keystroke with no redeploy (a redeploy risks a cold start).
# ---------------------------------------------------------------------------

WORKFLOW_PROMPT = (
    "You are a workflow diagnosis assistant. Analyze the described workflow and "
    "respond in plain text with repeatable steps, automation opportunities, and "
    "a suggested MVP."
)

JOURNEY_PROMPT = (
    "You are a builder-journey diagnostician for 100xEngineers. The person describes "
    "where they are, what they are trying to build or learn, and what feels stuck. "
    "Do four things, in plain text, in this order. "
    "First, locate them on the builder ladder: Consumer (uses AI tools), Assisted "
    "builder (builds with heavy help), Accelerated builder (builds fast with AI as a "
    "force multiplier), Autonomous builder (directs agents to build), Ships to real "
    "users (has shipped something people use). Name the single stage that fits best "
    "and give one sentence of evidence from what they said. "
    "Second, name the gap between where they are and where they want to go, concretely. "
    "Third, name their single current bottleneck. Not a list. One. The one thing that, "
    "if removed, unblocks the most. "
    "Fourth, give one action they can take this week to remove it. "
    "Be specific, kind, and short. Do not flatter. Do not hedge."
)

# Start in "workflow" mode. Env var sets the boot default; the /admin/mode
# route flips it live, in memory, with zero latency.
PROMPT_MODE = os.environ.get("PROMPT_MODE", "workflow")


def current_system_prompt() -> str:
    return JOURNEY_PROMPT if PROMPT_MODE == "journey" else WORKFLOW_PROMPT


def call_groq(user_content: str):
    """The L06 brain, now wearing a meter.

    Returns (text, meta). `meta` carries the numbers the dashboard needs:
    how many tokens we spent, and — crucially — how many requests Groq will
    still let us make this minute. We read that from the RAW response headers
    (`with_raw_response`), because the limit that breaks a launch first is the
    LLM rate cap, and you can only watch a budget drain if you read it.
    """
    raw = client.chat.completions.with_raw_response.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": current_system_prompt()},
            {"role": "user", "content": user_content},
        ],
    )
    # Groq reports your remaining budget in a response header.
    remaining = raw.headers.get("x-ratelimit-remaining-requests")
    completion = raw.parse()  # the normal object you're used to
    meta = {
        "input_tokens": completion.usage.prompt_tokens,
        "output_tokens": completion.usage.completion_tokens,
        "groq_remaining_rpm": int(remaining) if remaining is not None else None,
    }
    return completion.choices[0].message.content, meta


def log_event(route, status, latency_ms, user_id=None, meta=None):
    """Write one row to the `events` table — the whole observability story.

    No new infra: the same database that gives us MEMORY now gives us METRICS.
    """
    meta = meta or {}
    supabase.table("events").insert({
        "route": route,
        "status": status,
        "latency_ms": latency_ms,
        "user_id": user_id,
        "input_tokens": meta.get("input_tokens"),
        "output_tokens": meta.get("output_tokens"),
        "groq_remaining_rpm": meta.get("groq_remaining_rpm"),
    }).execute()


@app.post("/diagnose", response_class=PlainTextResponse)
def diagnose(body: dict, user_id: Optional[str] = Depends(get_user_id)):
    user_content = body.get("workflow_description", "")
    started = time.time()  # start the stopwatch so we can log latency

    # Four beats: open a conversation, store the question, think, store the answer.
    # We wrap MEMORY around last week's brain — we don't replace it.

    # 1. open a conversation (the domain-model "conversation" gets a row).
    #    Stamp it with the caller's user_id from the JWT, so we know who owns it.
    convo = supabase.table("conversations").insert(
        {"title": user_content[:60], "user_id": user_id}
    ).execute()
    conversation_id = convo.data[0]["id"]

    # 2. store what the user said
    supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "role": "user",
        "content": user_content,
    }).execute()

    # 3. think (the L06 logic, now also handing back metrics).
    #    This is where the real tripwire lives: Groq's free tier allows only
    #    ~30 requests/min. If 250 people press "diagnose" at once, most get a
    #    429. We catch it and return a graceful "you are in line" — a queue
    #    state, not a crash — and log the 429 so it shows up on the dashboard.
    try:
        plan, meta = call_groq(user_content)
    except RateLimitError:
        latency_ms = int((time.time() - started) * 1000)
        log_event("/diagnose", 429, latency_ms, user_id)
        return PlainTextResponse(
            "You are in line. The model is at its limit right now. "
            "Try again in a few seconds.",
            status_code=429,
        )

    # 4. store what the model answered
    supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": plan,
    }).execute()

    # 5. record what just happened: a 200, how long it took, what it cost.
    latency_ms = int((time.time() - started) * 1000)
    log_event("/diagnose", 200, latency_ms, user_id, meta)

    # The plan still comes back as plain text, so the L06 frontend keeps working.
    # The new conversation_id is also returned in a header for anyone who wants it.
    return PlainTextResponse(plan, headers={"X-Conversation-Id": conversation_id})


@app.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str):
    """Read a conversation's history back — the proof that memory survives.

    Restart the server, then call this endpoint: the messages are still here,
    because they live on disk in Postgres, not in this process's RAM.
    """
    result = (
        supabase.table("messages")
        .select("role, content, created_at")
        .eq("conversation_id", conversation_id)  # only THIS conversation
        .order("created_at")                      # oldest first, in order
        .execute()
    )
    return result.data


@app.get("/metrics")
def metrics():
    """The whole dashboard, in one SELECT.

    Read the last 500 events and roll them up into the four numbers that matter:
    how many diagnoses, how many got rate-limited, average latency, and how much
    Groq budget is left. No Mixpanel, no Datadog — the same database, one query.
    (This runs on the service_role backend, which bypasses RLS, so it can read
    the otherwise-private events table.)
    """
    rows = (
        supabase.table("events")
        .select("status, latency_ms, groq_remaining_rpm, created_at")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
        .data
    )
    total = len(rows)
    rate_limited = sum(1 for r in rows if r["status"] == 429)
    avg_latency = round(sum(r["latency_ms"] or 0 for r in rows) / total) if total else 0
    # The most recent reading of "requests left this minute".
    remaining = next(
        (r["groq_remaining_rpm"] for r in rows if r["groq_remaining_rpm"] is not None),
        None,
    )
    return JSONResponse({
        "total": total,
        "rate_limited": rate_limited,
        "avg_latency_ms": avg_latency,
        "groq_remaining_rpm": remaining,
    })


@app.get("/admin", response_class=HTMLResponse)
def admin():
    """A tiny live dashboard for the projector. It polls /metrics every 2s.

    Numbers ticking up in real time — that's the whole point. Put this on the
    big screen and you can watch your own product hit the rate limit, then
    watch the queue drain after you turn the one right knob.
    """
    return """
    <html><body style="font-family:system-ui;text-align:center;padding:3rem">
      <h1 id="t">0</h1><p>diagnoses</p>
      <h2 id="e">0</h2><p>in line (429)</p>
      <h2 id="l">0 ms</h2><p>avg latency</p>
      <h2 id="g">-</h2><p>Groq requests left this minute</p>
      <script>
        async function tick(){
          const m = await (await fetch('/metrics')).json();
          t.textContent = m.total; e.textContent = m.rate_limited;
          l.textContent = m.avg_latency_ms + ' ms';
          g.textContent = m.groq_remaining_rpm ?? '-';
        }
        setInterval(tick, 2000); tick();
      </script>
    </body></html>
    """


@app.post("/admin/mode")
def set_mode(mode: str):
    """The reveal, in one call. Flip the product's purpose with no redeploy.

    The architecture does not move: same auth, same RLS, same deploy, same
    dashboard. Only the system prompt changes. That is the lesson — once you
    own the shape, changing what a product DOES is a one-line change.

        curl -X POST 'http://127.0.0.1:8000/admin/mode?mode=journey'
    """
    global PROMPT_MODE
    if mode not in ("workflow", "journey"):
        raise HTTPException(status_code=400, detail="mode must be 'workflow' or 'journey'")
    PROMPT_MODE = mode
    return {"mode": PROMPT_MODE}
