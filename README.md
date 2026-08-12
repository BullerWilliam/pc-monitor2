# PC Monitor 2

This repository contains a local-only, visible remote monitoring prototype for Windows.

It builds two executables:

- `access.exe`: runs on the monitored PC, publishes pairing/status data to Firebase Realtime Database, and serves a local MJPEG screen stream.
- `monitor.exe`: lets you add paired PCs, view status, assign nicknames, see the latest metadata, and open a multi-view window.

Important safety note:

- This project does not implement hidden persistence, stealth startup, shell tampering, or remote keyboard/mouse lockout.
- Startup installation is opt-in and visible.
- Remote control is intentionally not included.

## Firebase config

Create a `firebase_config.json` file in the repo root, or place one in `%APPDATA%\PcMonitor2\firebase_config.json`.

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

Start the agent:

```powershell
py app\access_app.py run
```

Print the pairing code:

```powershell
py app\access_app.py code
```

Install a visible startup shortcut:

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
