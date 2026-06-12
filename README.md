# wan2gp-pulsebar

Floating Windows progress bar for Wan2GP generations.

## What it does

- Hooks Wan2GP generation progress without changing the generation flow.
- Writes a tiny `status.json` file with the current queue/task state.
- Includes a Windows-only WinForms companion app that stays always on top.
- Lets you hide the bar to the Windows tray while keeping live progress in the tooltip.
- Shows native tray notifications when a generation completes or fails.

## Resource profile

The desktop bar reads `status.json` once per second. It does not embed a browser, run
Electron, open a server, or touch the GPU. CPU usage should stay near zero.

## Files

```text
wan2gp-pulsebar/
  plugin.py
  plugin_info.json
  settings.json
  status.json
  desktop/
    Wan2GP.PulseBar.csproj
    LegacyPulseBar.cs
    build-legacy.ps1
    Program.cs
    FloatingBarForm.cs
```

## Usage

1. Enable the plugin in Wan2GP Plugin Manager.
2. Restart Wan2GP.
3. Open the `Pulsebar` tab.
4. Click `Launch floating bar`.

The plugin launches a published executable first:

```text
desktop/publish/Wan2GP.PulseBar.exe
```

If it does not exist, it falls back to `dotnet run` for the included WinForms
project.

This plugin also includes a .NET Framework single-file build that works on
Windows without installing the .NET SDK:

```powershell
.\desktop\build-legacy.ps1
```

For a lean executable, publish it once:

```powershell
dotnet publish .\desktop\Wan2GP.PulseBar.csproj -c Release -r win-x64 --self-contained false -o .\desktop\publish
```

After publishing, the plugin will launch:

```text
desktop/publish/Wan2GP.PulseBar.exe
```

## Status file

The plugin writes `status.json` in this folder by default:

```json
{
  "state": "running",
  "task_id": "unknown",
  "percent": 43,
  "stage": "sampling",
  "message": "Step 36/81",
  "queue": {
    "current": 1,
    "total": 2,
    "remaining": 1
  },
  "updated_at": "2026-06-12T18:30:00Z"
}
```
