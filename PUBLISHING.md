# Publishing — the public site

Two halves.

**The front door** is a static page on GitHub Pages:
`https://jpryor812.github.io/convoy/`. It is always up and costs nothing. It
replays the showcase run (`showcase/`), and the leaderboard, ticker and thought
bubbles all work. GitHub Actions rebuilds it on every push to `main`
(`.github/workflows/site.yml`), and runs the test suite on every push to any
branch.

**The live side** is `serve.py --public`, running on this machine behind a
Cloudflare tunnel, only while you want it. It serves the live map, answers
questions, and takes emails.

The front door finds the live side by reading `live.json` from this repo's `live`
branch (`site/config.json` says where). `go_live.py` writes it when you start and
clears it when you stop.

## Going live

    python3 go_live.py

That starts the server, opens a tunnel, waits for it to answer, publishes the
address, and keeps the laptop awake. Start a simulation (`run_phase2.py ...`) in
another terminal whenever you like. The site turns LIVE when the run's log
starts moving. **Ctrl-C** closes everything and sets the site back to offline.

## What a visitor sees

| state | the page |
|---|---|
| nothing running | the showcase run, plus "No simulation is running right now", with an email box if a newsletter is configured |
| `go_live.py` running, no simulation yet | the same, but emails go to the server and chat is open (email first) |
| simulation running | "A simulation is live right now", with **Watch it live**, which goes to the live map |

**Watching is open; talking needs an email.** The first question from a browser
asks for an address. The server signs a pass for it (`serve.py`, `chat_pass`)
and every later question carries the pass. It proves an email was given, not
that the email is real.

## Cost controls

- **5 questions per email per day.** Counted on disk (`waitlist.usage.json`),
  so restarting the server does not reset it. `--asks-per-day` changes it.
- **100 questions per connection per day**, a backstop against someone making
  up a fresh email for every question. It is generous because a classroom
  shares one connection.
- **No overall ceiling by default.** `--model-calls-per-day N` adds one. It
  only ever counts visitors' questions; simulations run in their own process
  and are never affected.
- **A separate OpenRouter key.** Put `OPENROUTER_PUBLIC_API_KEY=...` in `.env`,
  made on OpenRouter with a small credit limit. The public server uses it
  instead of your main key. With no overall ceiling, this key's limit is the
  real cap on what visitors can spend.
- **Advice is off** on the public server.

## Emails

- Through the live server: `waitlist.jsonl` on this machine. It is gitignored
  and never served back. `waitlist.secret` beside it signs the chat passes; keep
  it.
- With no live server: only if `site/config.json` names a newsletter form. For
  Buttondown, copy the form action from its embed settings into:

      "waitlist_form": {"action": "<form action URL>", "field": "email"}

  Once that is set, every signup also goes there, so you keep one list.

Both forms say "You must be 13 or older" (US COPPA).
