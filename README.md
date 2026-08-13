# PC Monitor 2

This repository contains a Windows-first monitoring scaffold for a visible, consent-based server room monitoring setup.

It builds two executables:

- `access.exe`: runs on each monitored Windows PC, creates a visible Startup-folder shortcut when asked, generates a pairing code, publishes metadata to Firebase, and serves an MJPEG screen stream.
- `monitor.exe`: runs on the admin PC, stores multiple pairing codes, shows live previews and metadata, and includes a multi-view grid plus a consent toggle for remote interaction.

## Current scaffold status

This build is intentionally a foundation, not the finished system.

- Visible startup registration is wired.
- Firebase pairing and metadata registration are wired.
- Live MJPEG screen streaming is wired.
- Multi-PC monitoring, nicknames, offline timing, and multi-view are wired.
- Remote interaction is scaffolded only.
- The consent toggle in `monitor.exe` updates Firebase.
- `access.exe` shows a visible `Remote session active` indicator when that toggle is on.
- Mouse and keyboard relay are not implemented yet in this scaffold.

## Project structure

```text
app/
  access_app.py                  # access.exe entrypoint
  monitor_app.py                 # monitor.exe entrypoint
  pc_monitor/
    access/
      agent.py                   # background agent, startup shortcut, HTTP stream
      capture.py                 # screen capture loop
      overlay.py                 # visible remote-session indicator
      main.py                    # CLI entrypoint
    monitor/
      main.py                    # tkinter monitor UI
    shared/
      config.py                  # runtime paths and Firebase config loading
      firebase.py                # Firebase Realtime Database client
      models.py                  # persisted device state
      storage.py                 # JSON persistence helpers
      system_info.py             # metadata and host metrics
```

## Firebase config

Create `firebase_config.json` in the repo root, or place it in `%APPDATA%\PcMonitor2\firebase_config.json`.

Example:

```json
{
  "database_url": "https://your-project-default-rtdb.firebaseio.com",
  "auth_token": ""
}
```

## Install dependencies

```powershell
py -m pip install -r requirements.txt
```

## Run from source

Start the access agent:

```powershell
py app\access_app.py run
```

Print the pairing code:

```powershell
py app\access_app.py code
```

Install a visible Startup-folder shortcut:

```powershell
py app\access_app.py install-startup
```

Open the monitor UI:

```powershell
py app\monitor_app.py
```

## Build executables

```powershell
.\build.ps1
```

The executables are written to `dist\access.exe` and `dist\monitor.exe`.
