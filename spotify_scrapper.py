import streamlit as st
from playwright.sync_api import sync_playwright
import csv
import os
import subprocess
import time
import threading
import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Install Playwright browser on first run (needed on Streamlit Cloud)
@st.cache_resource
def install_playwright():
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
    )

install_playwright()

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
# STEP 1 — INPUT
# ─────────────────────────────────────────────
st.markdown("### Step 1 — Paste your Spotify Playlist URL")
playlist_url = st.text_input(
    label="Playlist URL",
    placeholder="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    label_visibility="collapsed",
)

output_dir = st.text_input(
    label="Download folder (absolute path)",
    value=os.path.join(os.path.expanduser("~"), "spotify_downloads"),
    help="Songs will be saved as MP3 files in this folder.",
)

col1, col2 = st.columns(2)
with col1:
    run_scrape = st.button("🔍 Scrape Playlist")
with col2:
    run_download = st.button("⬇️ Download All Songs")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
CSV_PATH = "playlist_songs.csv"


def _playwright_worker(url: str, result_bucket: list, error_bucket: list):
    """
    Runs inside a plain thread so it gets a clean event loop —
    avoids the Windows asyncio NotImplementedError when Streamlit
    already owns the main loop.

    Spotify uses a VIRTUAL list — only ~50 rows exist in the DOM at
    any time, older ones are removed as you scroll.  We therefore
    accumulate tracks on EVERY scroll step rather than doing a single
    final scrape at the end.
    """
    asyncio.set_event_loop(asyncio.new_event_loop())

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url)

            page.wait_for_timeout(3000)   # Wait for initial load

            seen_keys = set()             # dedup key = (title, artist)
            accumulated = []              # final ordered list

            def harvest_visible():
                rows = page.query_selector_all("div[data-testid='tracklist-row']")
                for row in rows:
                    text = row.inner_text()
                    parts = [p.strip() for p in text.strip().split("\n") if p.strip()]
                    title  = parts[1] if len(parts) > 1 else parts[0]
                    artist = parts[2] if len(parts) > 2 else ""
                    key = (title, artist)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        accumulated.append(text)
                return rows

            no_new_count = 0
            while True:
                rows = harvest_visible()
                if not rows:
                    break

                prev_len = len(accumulated)
                rows[-1].scroll_into_view_if_needed()   # Trigger lazy load
                page.wait_for_timeout(2000)
                harvest_visible()

                if len(accumulated) == prev_len:
                    no_new_count += 1
                    if no_new_count >= 3:   # 3 consecutive empty scrolls → done
                        break
                else:
                    no_new_count = 0

            result_bucket.extend(accumulated)
            browser.close()
    except Exception as e:
        error_bucket.append(e)


def scrape_playlist(url: str):
    """
    Spawns _playwright_worker in a thread and waits for it to finish.
    This is the only change from the original — the logic inside is identical.
    """
    result_bucket = []
    error_bucket  = []

    t = threading.Thread(target=_playwright_worker, args=(url, result_bucket, error_bucket))
    t.start()
    t.join()

    if error_bucket:
        raise error_bucket[0]   # Re-raise any exception from the thread

    return result_bucket


def parse_song(raw_text: str):
    """
    Spotify tracklist rows look like:
        '1\nSong Title\nArtist Name\n3:45'
    We split on newline and extract title + artist.
    """
    parts = [p.strip() for p in raw_text.strip().split("\n") if p.strip()]
    title  = parts[1] if len(parts) > 1 else parts[0]
    artist = parts[2] if len(parts) > 2 else "Unknown Artist"
    return title, artist


def save_to_csv(songs_raw: list, path: str):
    """Save scraped rows to CSV with columns: index, title, artist, search_query."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "title", "artist", "search_query"])
        for i, raw in enumerate(songs_raw, start=1):
            title, artist = parse_song(raw)
            query = f"{title} {artist}"
            writer.writerow([i, title, artist, query])


def load_csv(path: str):
    """Load songs from existing CSV. Returns list of dicts."""
    songs = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            songs.append(row)
    return songs


def download_song(query: str, output_folder: str):
    """
    Use yt-dlp to search YouTube and download the best audio match,
    converted to MP3 via ffmpeg.
    """
    os.makedirs(output_folder, exist_ok=True)
    cmd = [
        "yt-dlp",
        f"ytsearch1:{query}",          # Search YouTube for 1 result
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",        # Best quality
        "--output", os.path.join(output_folder, "%(title)s.%(ext)s"),
        "--no-playlist",
        "--quiet",
        "--no-warnings",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


# ─────────────────────────────────────────────
# STEP 2 — SCRAPE
# ─────────────────────────────────────────────
if run_scrape:
    if not playlist_url.strip():
        st.markdown('<div class="error-box">⚠ Please paste a Spotify playlist URL first.</div>', unsafe_allow_html=True)
    else:
        st.markdown("---")
        st.markdown("### Step 2 — Scraping…")
        status = st.empty()
        status.markdown('<div class="status-box">🌐 Launching browser & loading playlist…</div>', unsafe_allow_html=True)

        try:
            raw_songs = scrape_playlist(playlist_url.strip())

            if not raw_songs:
                st.markdown('<div class="error-box">No tracks found. Check the URL or try again.</div>', unsafe_allow_html=True)
            else:
                save_to_csv(raw_songs, CSV_PATH)
                status.markdown(
                    f'<div class="status-box">✅ Found <b>{len(raw_songs)}</b> songs → saved to <code>{CSV_PATH}</code></div>',
                    unsafe_allow_html=True,
                )

                # Show the songs
                st.markdown(f"#### {len(raw_songs)} tracks found")
                songs_data = load_csv(CSV_PATH)
                for s in songs_data:
                    st.markdown(
                        f'<div class="song-card">'
                        f'<span class="song-index">#{s["index"]}</span>'
                        f'<span class="song-text"><b>{s["title"]}</b> — {s["artist"]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # Offer CSV download
                with open(CSV_PATH, "rb") as f:
                    st.download_button(
                        label="📥 Download CSV",
                        data=f,
                        file_name="playlist_songs.csv",
                        mime="text/csv",
                    )

        except Exception as e:
            st.markdown(f'<div class="error-box">❌ Error during scraping: {e}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# STEP 3 — DOWNLOAD
# ─────────────────────────────────────────────
if run_download:
    st.markdown("---")
    st.markdown("### Step 3 — Downloading Songs via yt-dlp")

    if not os.path.exists(CSV_PATH):
        st.markdown('<div class="error-box">⚠ No CSV found. Run scrape first.</div>', unsafe_allow_html=True)
    else:
        songs_data = load_csv(CSV_PATH)
        total = len(songs_data)
        st.markdown(f"Downloading **{total} songs** to `{output_dir}`…")

        progress_bar = st.progress(0)
        log_area    = st.empty()
        log_lines   = []

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
                log_lines[-1] = f"[{i}/{total}] ❌ {title} — {artist}  ({err.strip()[:60]})"

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