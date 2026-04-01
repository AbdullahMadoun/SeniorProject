# Bound Media Drop Zone

Place optional `.mp4`, `.webm`, or `.mov` recordings here to bind them into the replay bundle.

Supported sources:
- Gazebo screen recordings
- QGroundControl screen recordings
- any judge-facing supporting flight video

Optional manifest:
- `manifest.json`

README-driven binding is also supported:
- add media filenames directly in this README, for example:
  - `gazebo.mp4`
  - `qgc_recording.webm`

Example:

```json
{
  "media": [
    {
      "id": "gazebo_recording",
      "label": "Gazebo Flight",
      "kind": "video",
      "path": "gazebo.mp4"
    }
  ]
}
```

After adding media, rebuild:

```powershell
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_latest_replay_bundle.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_showcase.py
python D:\downloads\SeniorProject\Skylink2\autonomy\scripts\build_dashboard.py
```
