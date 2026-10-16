# onair · 别来烦我灯

A "do not disturb" lamp for meetings: when I'm in a meeting the lamp is
red (🔴 ON AIR), otherwise green (🟢).

Software prototype (step zero) of a future ESP32 hardware gadget for the
Muse Gadgets ecosystem — same spirit as [moodlamp](../moodlamp). The logic
lives behind an HTTP interface so a web page, a desktop widget, or a future
microcontroller can all consume it.

- `GET /` — the lamp: big glowing dot, current meeting, next meeting countdown (auto-refresh)
- `GET /api/status` — JSON: mode / busy / event / ends_at / next_in_min
- `POST /api/mode` — `{"mode": "auto|force-on|force-off"}` — manual override, like the physical button the real lamp will have

## Calendar providers

Pluggable. Two ship with it:

- **demo** (default): a fixed pretend schedule so the UI is testable without a calendar
- **gcal**: polls the Google Calendar connector (`hatch_gws_cli calendar +agenda --today`); goes idle gracefully when the calendar isn't connected — then demo is the honest fallback

```bash
python3 onair.py                    # demo provider, :8932
ONAIR_PROVIDER=gcal python3 onair.py  # real calendar (needs connected Google Calendar)
```

Stdlib only. Single file. The lamp polls the calendar every 60s; the page
refreshes every 30s. The physical version just needs to `GET /api/status`
and light up the dot.
