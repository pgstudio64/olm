# Getting Started — OLM on Windows 11

Step-by-step guide to install and run OLM on a Windows 11 machine (no admin rights required).

---

## 1. Prerequisites

### Python 3.10 or later

Check if Python is already installed: open a **Command Prompt** (Win+R, type `cmd`, Enter) and run:

```
python --version
```

You need **Python 3.10, 3.11, or 3.12**. If Python is not installed or the version is too old:

**Option A — Anaconda (recommended if already installed)**

If you have Anaconda, Python is included. Open an **Anaconda Prompt** and verify:

```
python --version
```

All commands below should be run from the Anaconda Prompt.

**Option B — Python.org installer (no admin rights)**

1. Go to https://www.python.org/downloads/
2. Download Python 3.12.x (Windows installer 64-bit)
3. Run the installer — **check "Add python.exe to PATH"** at the bottom
4. Choose "Install Now" (installs in your user profile, no admin needed)
5. Verify: open a new Command Prompt and run `python --version`

---

## 2. Project structure

Create a folder on your machine (e.g. `C:\Users\YourName\OLM`) and copy the following files into it:

```
OLM/
├── install.bat           ← double-click to install
├── launch.bat            ← double-click to start
├── requirements.txt      ← Python dependencies
├── pyproject.toml        ← project metadata
├── olm/                  ← application code (entire folder)
│   ├── core/
│   ├── server/
│   ├── static/
│   ├── templates/
│   ├── ingestion/
│   └── tests/
└── project/              ← your data (create this folder)
    ├── config.json       ← settings
    ├── catalogue/
    │   └── patterns.json ← pattern catalogue
    └── plans/            ← floor plan images (optional)
```

### Minimal `project/config.json`

Create the file `project\config.json` with this content:

```json
{
  "room_code": "14",
  "standard_labels": {
    "STANDARD_1": "Standard 1",
    "STANDARD_2": "Standard 2"
  },
  "default_door_width_cm": 90,
  "desk_width_cm": 180,
  "desk_depth_cm": 80,
  "grid_cell_cm": 10,
  "matching": {
    "w_density": 0.5,
    "w_comfort": 0.5,
    "min_desks_drop_ratio": 0.3
  },
  "spacing": {
    "STANDARD_1": {
      "chair_clearance_cm": 70,
      "front_access_cm": 60,
      "access_single_desk_cm": 100,
      "passage_behind_one_row_cm": 160,
      "passage_between_back_to_back_cm": 230,
      "passage_cm": 90,
      "door_exclusion_depth_cm": 180,
      "desk_to_wall_cm": 20,
      "max_island_size": 4,
      "min_block_separation_cm": 90,
      "main_corridor_cm": 140
    },
    "STANDARD_2": {
      "chair_clearance_cm": 70,
      "front_access_cm": 60,
      "access_single_desk_cm": 90,
      "passage_behind_one_row_cm": 120,
      "passage_between_back_to_back_cm": 180,
      "passage_cm": 90,
      "door_exclusion_depth_cm": 180,
      "desk_to_wall_cm": 10,
      "max_island_size": 6,
      "min_block_separation_cm": 90,
      "main_corridor_cm": 140
    }
  }
}
```

You can rename the standards, change the values, and add more standards as needed. All values are in centimetres.

### Minimal `project/catalogue/patterns.json`

Create the folder `project\catalogue\` and the file `patterns.json`:

```json
{
  "patterns": []
}
```

The catalogue starts empty. You will create patterns using the built-in editor.

---

## 3. Install

**Option A — Double-click (simplest)**

Double-click `install.bat`. It will:
1. Create a Python virtual environment (`venv\`)
2. Install the 4 dependencies (flask, numpy, opencv-python, Pillow)

Wait for "Installation complete." then close the window.

**Option B — Manual (if .bat doesn't work)**

Open a Command Prompt in the OLM folder:

```
cd C:\Users\YourName\OLM

python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

### What gets installed

| Package | Size | Role |
|---------|------|------|
| flask | ~2 MB | Web server |
| numpy | ~30 MB | Grid computation (circulation analysis) |
| opencv-python | ~40 MB | Image processing (floor plan ingestion) |
| Pillow | ~10 MB | Image I/O (floor plan ingestion) |

Total: ~80 MB. No internet connection needed after install.

---

## 4. Launch

**Option A — Double-click**

Double-click `launch.bat`. A terminal opens with:

```
=== OLM - Office Layout Matching ===
Starting server on http://localhost:5051
```

**Option B — Manual**

```
cd C:\Users\YourName\OLM
venv\Scripts\python -m olm.server.app
```

Then open your browser at: **http://localhost:5051**

To stop the server: press **Ctrl+C** in the terminal, or close the terminal window.

---

## 5. First steps in the UI

### Create a spacing standard

If you used the minimal config above, two standards are pre-loaded. You can view and edit them in **Settings** (gear icon, top-right) > **Spacing** section.

### Create your first pattern

1. Go to the **Catalogue** tab > **Editor** sub-tab
2. Set the room dimensions (width and depth in cm)
3. Add blocks (BLOCK_1, BLOCK_2_FACE, BLOCK_4_FACE, etc.)
4. Position them using the DSL or the controls
5. Click **Save** — the pattern is added to your catalogue

### Import rooms

1. Go to the **Import** tab
2. Either:
   - Paste room JSON data manually
   - Upload a floor plan image (PNG/JPEG) for automatic extraction (experimental)

### Match patterns to rooms

1. Go to the **Design** tab
2. Select a room — OLM proposes the best matching pattern from your catalogue
3. Review the layout, circulation paths, and scores
4. Navigate between rooms with the arrows

---

## 6. Troubleshooting

### "python is not recognized"

Python is not in your PATH. Either:
- Use the full path: `C:\Users\YourName\AppData\Local\Programs\Python\Python312\python.exe`
- Or reinstall Python and check "Add python.exe to PATH"
- Or use Anaconda Prompt instead of Command Prompt

### "No module named olm"

Make sure you are running from the OLM root folder (the one containing `olm/` and `project/`), not from inside `olm/`.

### The UI shows no standards

`project/config.json` is missing or has an empty `spacing` section. Create it following the template above.

### Port 5051 is already in use

Another instance is running, or another program uses port 5051. Either stop it or change the port:

```
venv\Scripts\python -c "from olm.server.app import app; app.run(port=5055)"
```

### Changes in Settings don't appear

Hard refresh the browser: **Ctrl+Shift+R**
