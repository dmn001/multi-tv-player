# multi-tv-player

A Python application to display multiple IPTV streams simultaneously using VLC. It features a robust PySide6-based UI, interactive video overlays (muting, EPG data, subtitles, screenshots), scroll navigation, and seamless group switching.

![Example screenshot](2026-07-02_screenshot.png)

![Controls](controls.png)

---

## Key Features

* **Dynamic Grid Layout:** Play multiple VLC streams simultaneously in customizable grid layouts (e.g., 2x2, 3x3) defined via your configuration file.
* **Live EPG Overlays:** Automatically fetches and displays live Electronic Program Guide (EPG) data (Program Name, Start/End Time, Channel Name) seamlessly at the bottom of each video feed.
* **Single-Fullscreen & Scroll Surfing:** Double-click any channel in the grid to isolate it in full-screen. While in full-screen, **use your mouse scroll wheel** to surf up and down through the channels. Double-click again to return to the grid.
* **Instant Click-to-Mute:** Single-click any video to instantly toggle its audio (and mute all other streams). A clear "VOL" or "MUTE" indicator will flash to confirm your action. 
* **Interactive Hover Controls:** Move your mouse over any feed to reveal quick actions: Mute, Subtitles, Screenshot, and Fullscreen toggles.
* **Numpad Quick-Switch:** Press keys `1`–`9` to instantly isolate the corresponding channel, expanding it to full screen and soloing its audio.
* **Global Control Panel:** A floating companion window provides system-wide toggles (Mute All, Unmute All, Subs, Combined Screenshots) and lets you instantly switch between your predefined channel groups.

⚠️ **Note:** This player currently only works on **Windows** (uses `widget.winId()` with `set_hwnd`, and the audio backend is Windows-specific).

---

## Requirements

- **TVHeadend server** or any HTTP playlist serving an M3U-style list (must be accessible at a URL)
- Python 3.8+
- VLC media player installed and available in your system PATH
- Python packages:
  - `PySide6`
  - `python-vlc`
  - `screeninfo`
  - `requests`
  - `Pillow`
  - `PyYAML`

Install dependencies via:

```bash
pip install -r requirements.txt
```

---

## Keyboard Shortcuts

- `M` – Toggle mute/unmute all players
- `Up Arrow` – Unmute all players
- `Down Arrow` – Mute all players
- `S` – Toggle subtitles on/off all players  
- `1`–`9` – Instantly isolate the specified player (fullscreen + solo audio). Press the same number again to return to the grid.
- `0` / `F` / `F11` – Toggle True Borderless Fullscreen for the application window.
- `Mouse Scroll Wheel` – (While in single-fullscreen mode) Surf up and down through the available channels.
- `*` – Instantly close the application

Screenshots are saved to: `~/Downloads/tvplayer_screenshots`
Files are named with the timestamp and safe channel name. Combined screenshots merge the grid into one image.

---

## Configuration (`config.yaml`)

All application settings are managed through a **YAML configuration file**. 

A file named `config.yaml` (or `example_config.yaml`) should be present in the same directory as the script. If `config.yaml` doesn't exist, the script will fall back to `example_config.yaml`. It's recommended to **rename `example_config.yaml` to `config.yaml`** and then modify it with your personal settings.

Here's an example of the `config.yaml` structure:

```yaml
# Rename this file to config.yaml for custom settings.

playlist_url: "http://192.168.1.73:9981/playlist" # Your M3U playlist URL
epg_url: "http://192.168.1.73:9981/xmltv/channels" # Optional EPG URL

stream_groups: # Define groups of channel numbers for quick switching
  3x3: ['101', '102', '103', '104', '105', '204', '203', '107', '106']
  2x2: ['101', '102', '103', '104']
  BBC News SD: ['231']
```

---

## Running the App

```bash
python multi_tv_player.py
```

This launches the full-screen video grid. The floating global control panel will appear automatically.

---

## Notes & Limitations

- **Windows-only**: uses `player.set_hwnd`, and the video/audio backends are optimized for Direct3D11 and DirectSound.
- Limited subtitle support, selects first available track.
- Only supports M3U-style playlists served via HTTP.

---

### Simultaneous Playback in TVHeadend 📺

For simultaneous channel playback in **TVHeadend**, a key understanding lies in how digital broadcasts are structured and delivered.

**Muxes (Multiplexes)**  
In **DVB-T/T2** broadcasts, channels are organized into groups called **"muxes"** (multiplexes). Each mux is transmitted on a specific frequency. A single tuner, once tuned to a particular mux, can access all the channels carried on that frequency without requiring additional tuners. *(Note: For Freeview HD in the UK, it's common for multiple HD channels to be grouped on the same high-capacity DVB-T2 mux, allowing a single tuner to access them concurrently.)*

**Multiple Tuners for Different Muxes**  
To view channels from **different muxes concurrently**, you'll need **multiple tuners**. For instance, if BBC ONE HD and BBC News SD are broadcast on separate muxes, watching both at the same time will necessitate two distinct tuners.

**IPTV/Streaming Sources**  
For **IPTV playlists** or servers that provide independent streams, the limitations imposed by muxes generally **do not apply**. Each stream is handled independently, provided your server and network infrastructure can manage the load.

## License

MIT License
