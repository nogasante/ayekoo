# Ayekoo — 2-minute video, shot by shot

Everything you need is here. Don't plan anything; just follow it top to bottom.

**Total: 2:00.** Judges watch this before they read anything, and the one thing
it must prove beyond doubt is that it runs **offline**.

---

## Before you record (15 minutes, do it once)

**1. Open two windows and make the text big.**
A terminal and a browser. In the terminal, set the font to about 18–20pt —
judges may watch this on a laptop, and small text kills a demo.

**2. Start Ayekoo — one command, no server needed.**

In PowerShell:

```powershell
cd ~\Desktop\ayekoo
C:\Users\nanas\Desktop\ADTC-2026\.venv\Scripts\python.exe -m ayekoo.ask --repl
```

It prints:

```text
Ayekoo — offline farming assistant for Ghana
loading…
ready — 8,169 passages from Ghanaian agricultural sources
ask a question, or Ctrl-C to quit

>
```

Loading takes about twenty seconds and happens **once**. Every question after
that answers immediately, which is why the demo uses this rather than running
the command fresh each time — three separate runs would mean three twenty-second
waits on camera, and working software would look broken.

**Do a full dry run now.** Ask all three demo questions, check the answers look
right, then quit and restart it so the recording starts from a clean screen.

**3. Close everything else.** Slack, browser tabs, anything that might pop a
notification. Close them properly, not just minimise.

**4. Plug the laptop in** and disable sleep.

**5. Recorder.** OBS Studio (free) or Windows Game Bar (`Win+G`). Record the
whole screen at 1080p. Do a 15-second test first and play it back — check the
text is readable and your microphone is actually capturing.

---

## The shot list

### Shot 1 — Who it's for (0:00–0:15)

**On screen:** your face, or just the terminal with the repo README open.

**Say:**

> "Ayekoo is what you say to a farmer coming back from the farm. It means well
> done. This is a farming assistant for Ghanaian farmers, and it runs completely
> offline on an eight gigabyte laptop."

---

### Shot 2 — Kill the internet, on camera (0:15–0:30)

**This is the most important shot in the video.** Do not skip it or do it
off-screen.

**Do, slowly and visibly:**
1. Click the network icon in the system tray.
2. Turn **Wi-Fi off**. Let the "no internet" state show clearly.
3. Unplug the ethernet cable if you have one — hold it up to the camera.
4. In the terminal, prove it:

```powershell
ping -n 2 8.8.8.8
```

Let the failure show on screen.

**Say:**

> "First, I'm turning off the internet. No Wi-Fi, no cable. Everything after
> this is running on this laptop alone."

---

### Shot 3 — The planting question (0:30–1:00)

**At the `>` prompt, type:**

```text
When should I plant maize in Tamale, and which varieties are recommended?
```

**While it runs, say:**

> "A farmer in Tamale asks when to plant maize."

**When the answer appears, point at the screen and say:**

> "It knows Tamale is in the Guinea and Sudan savannah zone. It gives the exact
> planting window from the Ministry of Food and Agriculture — end of May to
> early July. It knows northern Ghana has no minor season. And it names the
> varieties: Mamaba, Obatanpa, Sanzal-sima, Kpari-Faako."

**Then point at the disclosure line and say — don't skip this, it's your best
moment:**

> "And look here. It tells me the step from Tamale to Northern Region is not
> from its sources. It only claims what it can show you."

---

### Shot 4 — The Twi question (1:00–1:25)

**At the `>` prompt, type:**

```text
What is kokoo kokoram and how do I manage it?
```

**Say:**

> "Kokoo kokoram is what Ghanaian farmers call cocoa stem canker. Not the
> textbook name — the name people actually use."

**When the answer appears:**

> "It answers from the Ghana cocoa extension manual, and names the fungi:
> Phytophthora palmivora and Phytophthora megakarya. No cloud model knows this
> word. It's in here because a Ghanaian document put it there."

---

### Shot 5 — What it refuses (1:25–1:45)

**At the `>` prompt, type:**

```text
What is the capital city of Mongolia?
```

**Say:**

> "And when it doesn't know, it says so instead of guessing. That matters more
> than it sounds. A small model asked something outside its sources will invent
> a confident, wrong answer. A farmer can't tell the difference. This one
> refuses."

---

### Shot 6 — The numbers (1:45–2:00)

**On screen:** show `submission.json`, or just say it over the terminal.

In a second window:

```powershell
type submission.json
```

**Say:**

> "Three hundred and thirty megabytes of memory, against a seven gigabyte
> limit. Forty-six Ghanaian agricultural documents. Every answer traceable to a
> source you can open. Ayekoo — it works where the farmer is."

**Stop recording.**

---

## If something goes wrong while recording

- **An answer is slow.** Keep talking — say what it's doing. Don't stop and
  restart; a small pause looks like real software.
- **An answer comes out wrong or odd.** Stop, fix nothing, just re-record that
  shot. Do not show a bad answer and explain it away.
- **You fluff a line.** Pause two seconds, say it again. Cut the fluff later, or
  leave it — judges are watching the system, not your delivery.

## After recording

1. Trim the start and end only. No music, no titles, no transitions. Production
   value gains you nothing here and eats your two minutes.
2. Check it is **under 2:00**. If it runs over, cut Shot 1 down to one sentence.
3. **Watch it once, muted.** If the offline proof in Shot 2 isn't obvious with
   the sound off, re-record that shot.
4. Upload to YouTube as **Unlisted**.
   - Not Private — judges won't be able to open it, which loses the submission.
   - Title: `Ayekoo — offline farming assistant for Ghanaian farmers (ADTC 2026)`
5. Paste the new link into Devpost's **Video demo link** field, replacing the
   placeholder.

## The one thing to get right

If you only nail one shot, nail **Shot 2**. Everything else in this submission
is written down and checkable. That the Wi-Fi is off and it still answers is the
only thing a judge can't verify from the repo — they have to see it.
