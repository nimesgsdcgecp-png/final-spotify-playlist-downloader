import streamlit as st
from playwright.sync_api import sync_playwright
import csv
import os
import subprocess
import threading
import asyncio
import tempfile
import shutil
import io

# ─────────────────────────────────────────────
# INSTALL PLAYWRIGHT BROWSERS ON STREAMLIT CLOUD
# Runs once per container boot via cache_resource.
# ─────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def install_playwright_browsers():
    subprocess.run(["playwright", "install", "chromium"], capture_output=True)
    subprocess.run(["playwright", "install-deps", "chromium"], capture_output=True)
    return True

install_playwright_browsers()


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
st.markdown('<p class="subtitle">Scrape → CSV → Download. No API needed.</p>', unsafe_allow_html=True)
st.markdown("---")


# ─────────────────────────────────────────────
# SESSION STATE — survives Streamlit reruns
# ─────────────────────────────────────────────
if "songs_data" not in st.session_state:
    st.session_state.songs_data = []
if "csv_bytes" not in st.session_state:
    st.session_state.csv_bytes = None


# ─────────────────────────────────────────────
# STEP 1 — INPUTS
# ─────────────────────────────────────────────
st.markdown("### Step 1 — Paste your Spotify Playlist URL")
playlist_url = st.text_input(
    label="Playlist URL",
    placeholder="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    label_visibility="collapsed",
)

st.markdown("### Step 2 — Choose Download Folder")

# On Streamlit Cloud only /tmp is writable. Locally use ~/spotify_downloads.
_is_cloud = bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_CLOUD"))
_default_dir = (
    os.path.join(tempfile.gettempdir(), "spotify_downloads")
    if _is_cloud
    else os.path.join(os.path.expanduser("~"), "spotify_downloads")
)

output_dir = st.text_input(
    label="Download folder",
    value=_default_dir,
    help="On Streamlit Cloud only /tmp paths are writable. Locally use any path.",
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

def _playwright_worker(url: str, result_bucket: list, error_bucket: list):
    """
    YOUR ORIGINAL PLAYWRIGHT SCROLL LOGIC — completely untouched.

    Runs in its own thread with a fresh asyncio event loop to avoid
    the Windows/Streamlit NotImplementedError conflict.
    The two extra browser args (--no-sandbox, --disable-dev-shm-usage)
    are required on Streamlit Cloud's Linux container — ignored locally.
    """
    asyncio.set_event_loop(asyncio.new_event_loop())

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()
            page.goto(url)

            page.wait_for_timeout(3000)          # Wait for initial load

            prev_count = 0
            while True:
                rows = page.query_selector_all("div[data-testid='tracklist-row']")

                if len(rows) == prev_count:
                    break                        # Nothing new loaded

                prev_count = len(rows)

                rows[-1].scroll_into_view_if_needed()   # Triggers lazy load
                page.wait_for_timeout(2000)

            # Scrape all loaded rows  ← your original line
            rows = page.query_selector_all("div[data-testid='tracklist-row']")
            for row in rows:
                result_bucket.append(row.inner_text())

            browser.close()
    except Exception as e:
        error_bucket.append(e)


def scrape_playlist(url: str) -> list:
    """
    Spawns _playwright_worker in a thread and waits for it to finish.
    Keeps Playwright isolated from Streamlit's event loop on all platforms.
    """
    result_bucket: list = []
    error_bucket:  list = []

    t = threading.Thread(
        target=_playwright_worker,
        args=(url, result_bucket, error_bucket),
    )
    t.start()
    t.join()

    if error_bucket:
        raise error_bucket[0]

    return result_bucket


def parse_song(raw_text: str) -> tuple:
    """
    Spotify tracklist inner_text looks like:
        '1\\nSong Title\\nArtist Name\\n3:45'
    """
    parts = [p.strip() for p in raw_text.strip().split("\n") if p.strip()]
    title  = parts[1] if len(parts) > 1 else parts[0]
    artist = parts[2] if len(parts) > 2 else "Unknown Artist"
    return title, artist


def raw_to_tracks(raw_songs: list) -> list:
    """Convert list of inner_text strings → list of track dicts."""
    tracks = []
    for i, raw in enumerate(raw_songs, start=1):
        title, artist = parse_song(raw)
        tracks.append({
            "index":        i,
            "title":        title,
            "artist":       artist,
            "search_query": f"{title} {artist}",
        })
    return tracks


def tracks_to_csv_bytes(tracks: list) -> bytes:
    buf = io.StringIO()
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
    Search YouTube for `query` and download as MP3 via yt-dlp.
    Falls back to best native audio if ffmpeg is absent.
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
        st.markdown("### Scraping playlist…")
        status = st.empty()
        status.markdown(
            '<div class="status-box">🌐 Launching browser & scrolling through playlist…</div>',
            unsafe_allow_html=True,
        )

        try:
            raw_songs = scrape_playlist(playlist_url.strip())

            if not raw_songs:
                st.markdown(
                    '<div class="error-box">No tracks found. '
                    'Make sure the playlist is public and the URL is correct.</div>',
                    unsafe_allow_html=True,
                )
            else:
                tracks = raw_to_tracks(raw_songs)

                # Persist in session state — survives button reruns
                st.session_state.songs_data = tracks
                st.session_state.csv_bytes  = tracks_to_csv_bytes(tracks)

                status.markdown(
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
                '<code>packages.txt</code> to fix this on Streamlit Cloud.</div>',
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
