# Video — just do these steps in order

No talking needed. Screen recording only. About 20 minutes start to finish.

---

## Step 1 — Close everything

Close VS Code. Close Edge/Chrome. Close everything except one terminal.

Wait 30 seconds so Windows frees the memory.

## Step 2 — Open one PowerShell window

Make the font big: right-click the title bar → Properties → Font → size 20.

## Step 3 — Start Ayekoo

Paste this:

```powershell
cd C:\Users\nanas\Desktop\ayekoo
C:\Users\nanas\Desktop\ADTC-2026\.venv\Scripts\python.exe -m ayekoo.ask --repl
```

Wait for:

```text
ready — 8,535 passages from Ghanaian agricultural sources
>
```

## Step 4 — Practice run (not recording yet)

Type each of these once, so nothing is slow later:

```text
When should I plant maize in Tamale, and which varieties are recommended?
```
```text
What is kokoo kokoram and how do I manage it?
```
```text
What is the capital city of Mongolia?
```

Check the answers look right. Then type `quit` and start it again, so the screen is clean.

## Step 5 — Start recording

Press `Win + G` → click the record button. (Or use OBS if you prefer.)

## Step 6 — Turn off the internet, on camera

**This is the most important part of the whole video.**

1. Click the network icon in the taskbar
2. Turn Wi-Fi **off** — slowly, so it's visible
3. Unplug the network cable if you have one
4. Click back on the terminal and type:

```powershell
ping -n 2 8.8.8.8
```

Let it fail on screen. Wait 2 seconds.

## Step 7 — Ask the three questions

Type them one at a time. Wait for each answer. Don't rush.

```text
When should I plant maize in Tamale, and which varieties are recommended?
```

```text
What is kokoo kokoram and how do I manage it?
```

```text
What is the capital city of Mongolia?
```

## Step 8 — Stop recording

Press `Win + G` → stop. The file is in `Videos\Captures`.

## Step 9 — Upload

1. Go to youtube.com → Create → Upload video
2. Choose the file
3. Title: `Ayekoo — offline farming assistant for Ghanaian farmers (ADTC 2026)`
4. Visibility: **Unlisted**
   - Not Private. Private means judges cannot open it and the submission fails.
5. Copy the link

## Step 10 — Paste into Devpost

Devpost → your project → Additional info → **Video demo link** → paste → Save.

---

## If it goes wrong

- **Answer takes a long time** — that's fine, leave it in. Real software.
- **An answer looks wrong** — stop, start recording again from Step 5.
- **Video is over 2 minutes** — record again and don't pause between questions.

---

## Optional: add captions afterwards

Only if you want to. Any free editor (Clipchamp is built into Windows).

```text
0:00  Ayekoo — an offline farming assistant for Ghanaian farmers
0:10  First: internet off. No Wi-Fi, no cable.
0:20  Everything after this runs on this laptop alone.
0:30  A farmer in Tamale asks when to plant maize
0:45  MoFA's exact planting window. Ghanaian varieties by name.
0:55  It flags the one step that is not from its sources.
1:05  "Kokoo kokoram" — what Ghanaian farmers call cocoa stem canker
1:20  Answered from the Ghana cocoa extension manual
1:30  And when it does not know, it says so
1:45  544 MB of memory. 7 GB limit. 50 Ghanaian agricultural documents.
1:55  Ayekoo — it works where the farmer is.
```

---

## The one thing that matters

If everything else goes wrong, **Step 6 must be in the video**. Judges can read
the code, the report and the corpus themselves. The only thing they cannot check
without watching is that the Wi-Fi was off and it still answered.
