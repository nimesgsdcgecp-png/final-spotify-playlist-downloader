import streamlit as st
import requests
import re
import csv
import os
import subprocess
import tempfile
import shutil
import io

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Spotify Playlist Downloader",
    page_icon="🎵",
    layout="centered",
)

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600&display=swap');

        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif;
            background-color: #0a0a0a;
            color: #f0f0f0;
        }
        .stApp { background-color: #0a0a0a; }

        h1 {
            font-family: 'Space Mono', monospace;
            font-size: 2rem;
            color: #1DB954;
            letter-spacing: -1px;
        }
        .subtitle {
            color: #888;
            font-size: 0.95rem;
            margin-top: -12px;
            margin-bottom: 24px;
        }
        .stTextInput > div > div > input {
            background-color: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 8px;
            color: #f0f0f0;
            font-family: 'Space Mono', monospace;
            font-size: 0.85rem;
            padding: 12px;
        }
        .stButton > button {
            background-color: #1DB954;
            color: #000;
            font-family: 'Space Mono', monospace;
            font-weight: 700;
            border: none;
            border-radius: 50px;
            padding: 10px 28px;
            font-size: 0.9rem;
            transition: all 0.2s ease;
            width: 100%;
        }
        .stButton > button:hover {
            background-color: #1ed760;
            transform: scale(1.02);
        }
        .song-card {
            background: #141414;
            border: 1px solid #222;
            border-radius: 10px;
            padding: 10px 16px;
            margin-bottom: 6px;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .song-index {
            font-family: 'Space Mono', monospace;
            color: #1DB954;
            font-size: 0.75rem;
            min-width: 28px;
        }
        .song-text { color: #ddd; line-height: 1.4; }
        .status-box {
            background: #111;
            border-left: 3px solid #1DB954;
            border-radius: 4px;
            padding: 10px 14px;
            font-family: 'Space Mono', monospace;
            font-size: 0.78rem;
            color: #aaa;
            margin: 8px 0;
        }
        .error-box {
            background: #1a0a0a;
            border-left: 3px solid #e74c3c;
            border-radius: 4px;
            padding: 10px 14px;
            font-family: 'Space Mono', monospace;
            font-size: 0.78rem;
            color: #e74c3c;
            margin: 8px 0;
        }
        hr { border-color: #1e1e1e; }
    </style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
st.markdown("<h1>🎵 Spotify Playlist Downloader</h1>", unsafe_allow_html=True)
st.markdown('<p class="subtitle">Scrape → CSV → Download. No API key needed.</p>', unsafe_allow_html=True)
st.markdown("---")


# ─────────────────────────────────────────────
# SESSION STATE — survives Streamlit reruns
# ─────────────────────────────────────────────
if "songs_data" not in st.session_state:
    st.session_state.songs_data = []
if "csv_bytes" not in st.session_state:
    st.session_state.csv_bytes = None


# ─────────────────────────────────────────────
# INPUTS
# ─────────────────────────────────────────────
st.markdown("### Step 1 — Paste your Spotify Playlist URL")
playlist_url = st.text_input(
    label="Playlist URL",
    placeholder="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    label_visibility="collapsed",
)

st.markdown("### Step 2 — Choose Download Folder")

# On Streamlit Cloud only /tmp is writable.
# Locally this falls back to ~/spotify_downloads.
_is_cloud    = bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_CLOUD"))
_default_dir = (
    os.path.join(tempfile.gettempdir(), "spotify_downloads")
    if _is_cloud
    else os.path.join(os.path.expanduser("~"), "spotify_downloads")
)

output_dir = st.text_input(
    label="Download folder",
    value=_default_dir,
    help="On Streamlit Cloud only /tmp paths are writable. Locally, use any path.",
    label_visibility="collapsed",
)

col1, col2 = st.columns(2)
with col1:
    run_scrape = st.button("🔍 Scrape Playlist")
with col2:
    run_download = st.button("⬇️ Download All Songs")


# ─────────────────────────────────────────────
# SPOTIFY SCRAPING — pure requests, no browser
# ─────────────────────────────────────────────

# These headers make Spotify's server think we are a normal browser.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://open.spotify.com/",
}


def _get_spotify_token() -> str:
    """
    Fetch Spotify's anonymous web-player bearer token.
    This is the exact same token Spotify's own browser fetches
    before showing you a playlist — no credentials needed.

    Tries the primary endpoint first, falls back to scraping
    the HTML if the JSON endpoint changes.
    """
    # Primary: dedicated JSON endpoint
    try:
        r = requests.get(
            "https://open.spotify.com/get_access_token"
            "?reason=transport&productType=web_player",
            headers=_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data  = r.json()
        token = data.get("accessToken") or data.get("access_token")
        if token:
            return token
    except Exception:
        pass

    # Fallback: scrape token from the Spotify home page HTML
    r = requests.get("https://open.spotify.com/", headers=_HEADERS, timeout=15)
    r.raise_for_status()
    match = re.search(r'"accessToken"\s*:\s*"([^"]+)"', r.text)
    if match:
        return match.group(1)

    raise RuntimeError(
        "Could not retrieve a Spotify token.\n"
        "Possible causes:\n"
        "• Spotify changed their web-player endpoint\n"
        "• The server is temporarily blocking requests\n"
        "Try again in a minute."
    )


def scrape_all_tracks(playlist_url: str) -> list:
    """
    Fetch ALL tracks from a public Spotify playlist.

    Steps:
      1. Extract playlist ID from the URL.
      2. Get an anonymous bearer token from Spotify's web-player.
      3. Paginate through /v1/playlists/{id}/tracks in batches of 100
         until every track is collected.

    Returns a list of dicts:
        { index, title, artist, search_query }
    """
    match = re.search(r"playlist/([A-Za-z0-9]+)", playlist_url)
    if not match:
        raise ValueError(
            "Could not find a playlist ID in that URL.\n"
            "It should look like: https://open.spotify.com/playlist/XXXX"
        )
    playlist_id = match.group(1)

    token        = _get_spotify_token()
    auth_headers = {**_HEADERS, "Authorization": f"Bearer {token}"}

    tracks = []
    offset = 0
    limit  = 100

    while True:
        r = requests.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers=auth_headers,
            params={
                "limit":  limit,
                "offset": offset,
                "fields": "items(track(name,artists(name))),next,total",
            },
            timeout=20,
        )

        if r.status_code == 401:
            raise RuntimeError(
                "Spotify returned 401 Unauthorized.\n"
                "The playlist is likely private — set it to Public and try again."
            )
        if r.status_code == 404:
            raise RuntimeError(
                "Playlist not found (404). Double-check the URL."
            )
        r.raise_for_status()

        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Spotify API error: {data['error']['message']}")

        for item in data.get("items", []):
            track = item.get("track")
            # Skip None entries (deleted/unavailable tracks in a playlist)
            if not track or not track.get("name"):
                continue
            title   = track["name"]
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            tracks.append({
                "index":        len(tracks) + 1,
                "title":        title,
                "artist":       artists,
                "search_query": f"{title} {artists}",
            })

        # Spotify returns null for "next" when we've reached the last page
        if not data.get("next"):
            break

        offset += limit

    return tracks


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def tracks_to_csv_bytes(tracks: list) -> bytes:
    buf    = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["index", "title", "artist", "search_query"])
    writer.writeheader()
    writer.writerows(tracks)
    return buf.getvalue().encode("utf-8")


def show_songs(songs_data: list):
    for s in songs_data:
        st.markdown(
            f'<div class="song-card">'
            f'<span class="song-index">#{s["index"]}</span>'
            f'<span class="song-text"><b>{s["title"]}</b> — {s["artist"]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def download_song(query: str, output_folder: str) -> tuple:
    """
    Search YouTube for `query` and save as MP3 via yt-dlp.
    Falls back to native audio format if ffmpeg is not installed.
    """
    os.makedirs(output_folder, exist_ok=True)
    has_ffmpeg = shutil.which("ffmpeg") is not None

    cmd = [
        "yt-dlp",
        f"ytsearch1:{query}",
        "--extract-audio",
        "--audio-format", "mp3" if has_ffmpeg else "best",
        "--audio-quality", "0",
        "--output", os.path.join(output_folder, "%(title)s.%(ext)s"),
        "--no-playlist",
        "--quiet",
        "--no-warnings",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


# ─────────────────────────────────────────────
# ACTION — SCRAPE
# ─────────────────────────────────────────────
if run_scrape:
    if not playlist_url.strip():
        st.markdown(
            '<div class="error-box">⚠ Please paste a Spotify playlist URL first.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown("---")
        st.markdown("### Fetching playlist…")
        with st.spinner("🌐 Contacting Spotify…"):
            try:
                tracks = scrape_all_tracks(playlist_url.strip())

                if not tracks:
                    st.markdown(
                        '<div class="error-box">No tracks found. '
                        'Make sure the playlist is <b>public</b> and the URL is correct.</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    # Persist across reruns
                    st.session_state.songs_data = tracks
                    st.session_state.csv_bytes  = tracks_to_csv_bytes(tracks)

                    st.markdown(
                        f'<div class="status-box">✅ Found <b>{len(tracks)}</b> tracks</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"#### {len(tracks)} tracks found")
                    show_songs(tracks)

                    st.download_button(
                        label="📥 Download CSV",
                        data=st.session_state.csv_bytes,
                        file_name="playlist_songs.csv",
                        mime="text/csv",
                    )

            except Exception as e:
                st.markdown(
                    f'<div class="error-box">❌ {e}</div>',
                    unsafe_allow_html=True,
                )

# Keep showing previously scraped songs after any rerun
elif st.session_state.songs_data:
    st.markdown(f"#### {len(st.session_state.songs_data)} tracks (from last scrape)")
    show_songs(st.session_state.songs_data)
    if st.session_state.csv_bytes:
        st.download_button(
            label="📥 Download CSV",
            data=st.session_state.csv_bytes,
            file_name="playlist_songs.csv",
            mime="text/csv",
        )


# ─────────────────────────────────────────────
# ACTION — DOWNLOAD via yt-dlp
# ─────────────────────────────────────────────
if run_download:
    st.markdown("---")
    st.markdown("### Downloading Songs via yt-dlp")

    songs_data = st.session_state.songs_data

    if not songs_data:
        st.markdown(
            '<div class="error-box">⚠ No tracks in memory. Scrape the playlist first.</div>',
            unsafe_allow_html=True,
        )
    else:
        total = len(songs_data)
        st.markdown(f"Downloading **{total} songs** to `{output_dir}`…")

        if not shutil.which("ffmpeg"):
            st.markdown(
                '<div class="status-box">⚠ ffmpeg not found — files will download in '
                'native format instead of MP3. Add <code>ffmpeg</code> to '
                '<code>packages.txt</code> to enable MP3 on Streamlit Cloud.</div>',
                unsafe_allow_html=True,
            )

        progress_bar  = st.progress(0)
        log_area      = st.empty()
        log_lines:    list = []
        success_count = 0
        fail_count    = 0

        for i, song in enumerate(songs_data, start=1):
            query  = song["search_query"]
            title  = song["title"]
            artist = song["artist"]

            log_lines.append(f"[{i}/{total}] ⏳ {title} — {artist}")
            log_area.markdown(
                '<div class="status-box">' + "<br>".join(log_lines[-8:]) + "</div>",
                unsafe_allow_html=True,
            )

            ok, err = download_song(query, output_dir)

            if ok:
                success_count += 1
                log_lines[-1] = f"[{i}/{total}] ✅ {title} — {artist}"
            else:
                fail_count += 1
                log_lines[-1] = (
                    f"[{i}/{total}] ❌ {title} — {artist}  ({err.strip()[:80]})"
                )

            progress_bar.progress(i / total)
            log_area.markdown(
                '<div class="status-box">' + "<br>".join(log_lines[-8:]) + "</div>",
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.markdown(
            f"### Done!  ✅ {success_count} downloaded &nbsp;&nbsp; ❌ {fail_count} failed"
        )
        st.markdown(f"Files saved to: `{output_dir}`")
