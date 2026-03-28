import streamlit as st
import streamlit.components.v1 as components
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
        .subtitle { color: #888; font-size: 0.95rem; margin-top: -12px; margin-bottom: 24px; }
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
            width: 100%;
        }
        .stButton > button:hover { background-color: #1ed760; }
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
        .song-index { font-family: 'Space Mono', monospace; color: #1DB954; font-size: 0.75rem; min-width: 28px; }
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
# SESSION STATE
# ─────────────────────────────────────────────
if "songs_data" not in st.session_state:
    st.session_state.songs_data = []
if "csv_bytes" not in st.session_state:
    st.session_state.csv_bytes = None
if "token" not in st.session_state:
    st.session_state.token = ""


# ─────────────────────────────────────────────
# STEP 1 — FETCH TOKEN FROM USER'S BROWSER
# The JS runs IN the user's browser (their IP, not the server's).
# Spotify happily returns the token because it's coming from a real browser.
# The token is then sent back to Streamlit via postMessage / query param trick.
# ─────────────────────────────────────────────
st.markdown("### Step 1 — Fetch Spotify Token")
st.markdown("Click the button below. Your browser will fetch the token directly from Spotify — no copy-paste needed.")

# This HTML+JS component runs entirely in the user's browser.
# It fetches the Spotify token from the user's side (bypassing server IP block),
# then displays it in a text box so the user can copy it into the field below.
token_fetcher_html = """
<style>
    body { background: transparent; margin: 0; font-family: 'Space Mono', monospace; }
    button {
        background: #1DB954;
        color: #000;
        border: none;
        border-radius: 50px;
        padding: 10px 24px;
        font-family: 'Space Mono', monospace;
        font-weight: 700;
        font-size: 0.85rem;
        cursor: pointer;
        width: 100%;
    }
    button:hover { background: #1ed760; }
    #status { margin-top: 10px; font-size: 0.78rem; color: #aaa; }
    #tokenBox {
        margin-top: 10px;
        width: 100%;
        padding: 8px;
        background: #1a1a1a;
        border: 1px solid #1DB954;
        border-radius: 6px;
        color: #1DB954;
        font-family: 'Space Mono', monospace;
        font-size: 0.72rem;
        word-break: break-all;
        display: none;
    }
    #copyBtn {
        display: none;
        margin-top: 6px;
        background: #222;
        color: #1DB954;
        border: 1px solid #1DB954;
        border-radius: 50px;
        padding: 6px 16px;
        font-family: 'Space Mono', monospace;
        font-size: 0.75rem;
        cursor: pointer;
        width: auto;
    }
</style>

<button onclick="fetchToken()">🔑 Fetch Token from Spotify</button>
<div id="status">Click to fetch your token automatically.</div>
<textarea id="tokenBox" rows="3" readonly></textarea>
<button id="copyBtn" onclick="copyToken()">📋 Copy Token</button>

<script>
async function fetchToken() {
    document.getElementById('status').innerText = '⏳ Fetching from Spotify...';
    try {
        const res = await fetch(
            'https://open.spotify.com/get_access_token?reason=transport&productType=web_player',
            {
                credentials: 'include',   // sends your Spotify cookies = real browser session
                headers: { 'Accept': 'application/json' }
            }
        );
        const data = await res.json();
        const token = data.accessToken || data.access_token;
        if (token) {
            document.getElementById('tokenBox').value = token;
            document.getElementById('tokenBox').style.display = 'block';
            document.getElementById('copyBtn').style.display = 'inline-block';
            document.getElementById('status').innerText = '✅ Token fetched! Copy it and paste below.';
        } else {
            document.getElementById('status').innerText = '❌ No token in response. Are you logged into Spotify?';
        }
    } catch(e) {
        document.getElementById('status').innerText = '❌ Error: ' + e.message +
            ' — Make sure you are logged into open.spotify.com';
    }
}

function copyToken() {
    const box = document.getElementById('tokenBox');
    box.select();
    document.execCommand('copy');
    document.getElementById('copyBtn').innerText = '✅ Copied!';
    setTimeout(() => document.getElementById('copyBtn').innerText = '📋 Copy Token', 2000);
}
</script>
"""

components.html(token_fetcher_html, height=180)

st.markdown("**Paste the token here:**")
token_input = st.text_input(
    label="Spotify Token",
    placeholder="Paste token here…",
    type="password",
    label_visibility="collapsed",
    key="token_field",
)

# Save token to session state so it persists across reruns
if token_input:
    st.session_state.token = token_input

if st.session_state.token:
    st.markdown(
        '<div class="status-box">✅ Token saved — valid for ~1 hour.</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")


# ─────────────────────────────────────────────
# STEP 2 — PLAYLIST URL + OUTPUT DIR
# ─────────────────────────────────────────────
st.markdown("### Step 2 — Paste your Spotify Playlist URL")
playlist_url = st.text_input(
    label="Playlist URL",
    placeholder="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    label_visibility="collapsed",
)

st.markdown("### Step 3 — Download Folder")
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
# HELPERS
# ─────────────────────────────────────────────
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


def scrape_all_tracks(playlist_url: str, token: str) -> list:
    """
    Fetch ALL tracks using the token obtained from the user's browser.
    Token comes from a real browser IP so Spotify accepts it.
    Paginates in batches of 100 until all tracks are fetched.
    """
    match = re.search(r"playlist/([A-Za-z0-9]+)", playlist_url)
    if not match:
        raise ValueError("Invalid Spotify playlist URL.")
    playlist_id  = match.group(1)
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
            raise RuntimeError("Token expired (401). Click 'Fetch Token' again to get a fresh one.")
        if r.status_code == 404:
            raise RuntimeError("Playlist not found (404). Double-check the URL.")
        r.raise_for_status()

        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Spotify API error: {data['error']['message']}")

        for item in data.get("items", []):
            track = item.get("track")
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

        if not data.get("next"):
            break
        offset += limit

    return tracks


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
    if not st.session_state.token:
        st.markdown(
            '<div class="error-box">⚠ No token found. Click "Fetch Token from Spotify" first.</div>',
            unsafe_allow_html=True,
        )
    elif not playlist_url.strip():
        st.markdown(
            '<div class="error-box">⚠ Please paste a Spotify playlist URL.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown("---")
        with st.spinner("🌐 Fetching all tracks from Spotify…"):
            try:
                tracks = scrape_all_tracks(playlist_url.strip(), st.session_state.token)

                if not tracks:
                    st.markdown(
                        '<div class="error-box">No tracks found. Make sure the playlist is public.</div>',
                        unsafe_allow_html=True,
                    )
                else:
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
                st.markdown(f'<div class="error-box">❌ {e}</div>', unsafe_allow_html=True)

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
                '<div class="status-box">⚠ ffmpeg not found — files will download in native '
                'format. Add <code>ffmpeg</code> to <code>packages.txt</code> for MP3.</div>',
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
                log_lines[-1] = f"[{i}/{total}] ❌ {title} — {artist}  ({err.strip()[:80]})"

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
