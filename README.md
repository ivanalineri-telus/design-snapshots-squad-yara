# design-snapshots-squad-yara

Capture a verifiable snapshot of a Figma frame at the moment a task is picked up, so the developer can later detect if the design changed underneath them. Built by squad **Yara**, useful for both iOS and Android squads.

> **Status:** MVP. Snapshots are triggered **manually** from GitHub Actions. Jira integration and automatic change detection are planned for later phases.

---

## Why this exists

Designers sometimes update Figma after a task is already in progress. Native Figma branching and email notifications didn't stick — devs missed them. This repo solves the *"what did the design look like when I started this task?"* problem by storing a snapshot (PNG + metadata) directly in git.

---

## How to take a snapshot

You only need two things: a Figma URL pointing to the frame you care about, and a task ID.

### 1. Get the right Figma URL

Open the file in Figma and **click directly on the frame** you want to capture. Then either:

- Right-click → **Copy link to selection**, or
- Press **`Cmd + L`** (Mac) / **`Ctrl + L`** (Windows).

The link looks like:

```
https://www.figma.com/design/<FILE_KEY>/<TITLE>?node-id=<NODE_ID>
```

The `node-id` parameter is the key — it tells the bot which frame to snapshot.

> 💡 **Important:** if your task only touches 1–2 screens out of a 12-screen flow, **don't snapshot the whole flow**. Click on just the screens that change. A focused snapshot will make the future change-detection alerts precise to your task — otherwise you'll get noise every time anything else in the flow moves.

#### Capturing multiple frames at once

Select the frames you want with `Shift+click`, then `Cmd/Ctrl + L`. The URL will contain comma-separated IDs (`?node-id=A,B,C`). Each frame is saved as a separate `frame_<NODE_ID>.png` in the same snapshot folder.

### 2. Run the workflow

1. Go to the [**Actions** tab](../../actions) of this repo.
2. Open **Manual Snapshot** → click **Run workflow** (top right).
3. Fill in:
   - **`figma_url`** — the link from step 1.
   - **`task_id`** — your ticket ID (e.g. `IOS-1234`, `AND-5678`). This becomes the folder name, so use something stable.
4. Click the green **Run workflow** button.

About a minute later, a new commit appears on `main`:

```
snapshots/
└── <TASK_ID>/
    └── <TIMESTAMP>/             # UTC, format YYYYMMDD-HHMMSS
        ├── frame.png            # rendered at 2× for retina / HiDPI
        └── metadata.json        # see below
```

Link the resulting `frame.png` from your PR description (or paste it into the ticket) and you have an immutable record of the design at that point in time.

---

## What's in `metadata.json`

```json
{
  "task_id": "IOS-1234",
  "captured_at_utc": "2026-05-06T19:37:53Z",
  "figma": {
    "url": "<original URL>",
    "file_key": "<FILE_KEY>",
    "node_ids": ["70149:40114"],
    "current_version_id": "2350166552046825356",
    "current_version_created_at": "2026-05-05T19:32:03Z",
    "current_version_label": null
  },
  "frames": [
    {
      "node_id": "70149:40114",
      "name": "Frame name as it appears in Figma",
      "image_file": "frame.png"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `captured_at_utc` | When the snapshot was taken (UTC). |
| `figma.current_version_id` | ID of the most recent Figma **version checkpoint** at capture time. |
| `figma.current_version_created_at` | Approximate timestamp of the last meaningful edit to the file. |
| `figma.current_version_label` | Manual version label, if the designer added one (usually `null`). |

> Figma creates a version checkpoint as people edit (auto-saved every few minutes, or manually labeled). The `current_version_*` fields are what the change-detection phase will compare against to decide *"has the design changed since this snapshot?"*.

---

## Local development (optional)

Useful if you want to debug the script or test before pushing changes.

```bash
git clone https://github.com/ivanalineri-telus/design-snapshots-squad-yara.git
cd design-snapshots-squad-yara
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export FIGMA_TOKEN='figd_...'   # your personal Figma token
export FIGMA_URL='https://www.figma.com/design/.../?node-id=1-2'
export TASK_ID='TEST-001'
python scripts/snapshot.py
```

Generate a Figma personal access token at **Figma → Settings → Security → Personal access tokens** with scopes `file_content:read` and `file_metadata:read`.

---

## Repository setup (one-time, already done)

- Secret **`FIGMA_TOKEN`** is configured under **Settings → Secrets and variables → Actions**.
- The workflow has `permissions: contents: write` so the bot can push the snapshot back.
- Snapshots are committed by `github-actions[bot]` with the message `snapshot: <task_id> @ <timestamp>`.

---

## Limitations & current scope

- The token's owner must have access to the Figma file. Files in workspaces they don't belong to will return 403 / 404.
- **No automatic change detection yet.** You snapshot manually; comparison is manual (`git log snapshots/<TASK_ID>/`).
- **No Jira integration yet.** Trigger is manual via Actions.
- No visual diff between snapshots yet.

These are intentional cuts — this is the MVP layer. The next phases (cron-based change detection, then Jira webhook) will be added once this manual flow is validated.
