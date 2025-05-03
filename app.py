# --- app.py ---

# =========================================
# Part 1: Imports, Setup, Config, Helpers
# =========================================

import os
import subprocess
import shlex
import logging
import traceback
import uuid
import shutil
import time
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    logging.warning("PyMuPDF (fitz) not found. PDF processing will be disabled. Run: pip install PyMuPDF")
    PYMUPDF_AVAILABLE = False
    fitz = None # Define fitz as None if not available

from flask import (
    Flask, render_template, request, send_from_directory,
    url_for, flash, redirect, g
)
from werkzeug.utils import secure_filename
try:
    from pydub import AudioSegment
    from pydub.exceptions import CouldntDecodeError
    PYDUB_AVAILABLE = True
except ImportError:
    logging.error("*"*60)
    logging.error("FATAL: Failed to import pydub. Audio mixing will NOT work.")
    logging.error("Ensure 'pydub' is installed (`pip install pydub`).")
    logging.error("If using Python 3.13+, ensure 'audioop-lts' is installed (`pip install audioop-lts`).")
    logging.error("Also ensure ffmpeg is installed and in your system's PATH.")
    logging.error("*"*60)
    AudioSegment = None
    CouldntDecodeError = None
    PYDUB_AVAILABLE = False

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Flask App Setup ---
app = Flask(__name__)
# IMPORTANT: Replace 'dev-secret-key' with a real, random secret key in production!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key')

# --- Configuration ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
log.info(f"Application Base Directory: {BASE_DIR}")

PIPER_DIR = os.path.join(BASE_DIR, 'piper')
PIPER_EXE_PATH = os.path.join(PIPER_DIR, 'piper.exe')
PIPER_VOICES_DIR = os.path.join(PIPER_DIR, 'voices')

# --- Available Voices Configuration ---
# IMPORTANT: Ensure you have BOTH .onnx and .onnx.json files for each listed voice
AVAILABLE_VOICES = {
    "USA - Female 1 (Libritts)": "en_US-libritts_r-medium",
    "USA - Female 2 (Lessac)": "en_US-lessac-medium",
    "UK - Female (Southern)": "en_GB-southern_english_female-medium",
    # Add more voices here as you download them
}
DEFAULT_VOICE_KEY = "USA - Female 1 (Libritts)" # The key from AVAILABLE_VOICES to use by default

# --- File/Directory Paths ---
OUTPUT_DIR = os.path.join(BASE_DIR, 'static', 'audio')
os.makedirs(OUTPUT_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Allowed File Extensions ---
ALLOWED_TEXT_EXTENSIONS = {'pdf'} if PYMUPDF_AVAILABLE else set()
ALLOWED_BG_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'}

# --- Cleanup Configuration ---
CLEANUP_FILE_AGE_SECONDS = 3600 # 1 hour

# --- FFMPEG Check ---
def check_ffmpeg():
    """Checks if ffmpeg and ffprobe are found in PATH and logs results."""
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    log.info(f"Checking for ffmpeg/ffprobe in system PATH...")
    found = True
    if ffmpeg_path:
        log.info(f"ffmpeg found at: {ffmpeg_path}")
    else:
        log.error("!!! ffmpeg executable NOT FOUND in system PATH!")
        log.error("!!! pydub may fail to load/export many audio formats.")
        log.error("!!! Ensure ffmpeg is installed and its 'bin' directory is added to your PATH environment variable.")
        found = False
    if ffprobe_path:
        log.info(f"ffprobe found at: {ffprobe_path}")
    else:
        log.warning("! ffprobe executable NOT FOUND in system PATH.")
        log.warning("! pydub might have issues reading metadata for some files.")
    if not found:
         log.error("! Audio conversion/mixing WILL LIKELY FAIL for many formats without ffmpeg.")
    return found
FFMPEG_FOUND = check_ffmpeg() # Check on startup
# --- End FFMPEG Check ---


# --- Example Sentence & Timings for Read-Along Demo ---
# NOTE: THESE ARE ESTIMATES and only work for the exact text + default speed/voice
EXAMPLE_SENTENCE = "Hello world, this is a demonstration."
EXAMPLE_TIMINGS = [
    {"text": "Hello", "start": 0.10, "end": 0.50}, {"text": "world,", "start": 0.50, "end": 0.90},
    {"text": "this", "start": 1.00, "end": 1.25}, {"text": "is", "start": 1.25, "end": 1.45},
    {"text": "a", "start": 1.45, "end": 1.55}, {"text": "demonstration.", "start": 1.55, "end": 2.40},
]
# --- End Read-Along Demo Data ---


log.info(f"Piper path: {PIPER_EXE_PATH}")
log.info(f"Static audio output: {OUTPUT_DIR}")
log.info(f"Upload directory: {app.config['UPLOAD_FOLDER']}")
log.info(f"PyMuPDF available (for PDF): {PYMUPDF_AVAILABLE}")
log.info(f"Pydub available (for Mixing): {PYDUB_AVAILABLE}")
log.info(f"FFmpeg found (for Mixing): {FFMPEG_FOUND}")


# --- Helper Functions ---
def allowed_text_file(filename):
    """Checks if the uploaded document file is allowed (PDF)."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_TEXT_EXTENSIONS

def allowed_bg_file(filename):
    """Checks if the uploaded background music file is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_BG_EXTENSIONS

# --- File Cleanup Function ---
def cleanup_old_files(directory, max_age_seconds):
    """Removes files older than max_age_seconds in the specified directory."""
    now = time.time()
    cleaned_count = 0
    log.debug(f"Running cleanup in directory: {directory}")
    try:
        for filename in os.listdir(directory):
            # Skip hidden files like .gitignore
            if filename.startswith('.'):
                continue
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                try:
                    file_age = now - os.path.getmtime(file_path)
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        log.info(f"Cleanup: Removed '{filename}' (age: {file_age:.0f}s)")
                        cleaned_count += 1
                except OSError as e:
                    log.error(f"Cleanup Error: Failed processing '{file_path}': {e}")
        # if cleaned_count > 0: log.info(f"Cleanup: Removed {cleaned_count} files from {directory}.")
    except FileNotFoundError:
        log.warning(f"Cleanup Warning: Directory not found: {directory}")
    except Exception as e:
        log.error(f"Cleanup Error: Failed listing '{directory}': {e}")

# --- Request Hooks ---
@app.before_request
def run_cleanup():
    """Run cleanup logic periodically before handling the request."""
    # Simple: Run every time. Could add time-based or random check later.
    log.debug("Running periodic cleanup...")
    cleanup_old_files(OUTPUT_DIR, CLEANUP_FILE_AGE_SECONDS)
    cleanup_old_files(UPLOAD_FOLDER, CLEANUP_FILE_AGE_SECONDS)


# =========================================
# Part 2: Flask Routes (/ and /process-text)
# =========================================

@app.route('/')
def home():
    """Renders the main page, passing defaults."""
    log.debug("Rendering home page.")
    # Pass the example sentence to the template's placeholder
    return render_template(
        'index.html',
        default_bg_volume=-12,
        default_speed=1.0,
        available_voices=AVAILABLE_VOICES,
        default_voice_key=DEFAULT_VOICE_KEY,
        pdf_enabled=PYMUPDF_AVAILABLE,
        example_sentence=EXAMPLE_SENTENCE
     )

@app.route('/process-text', methods=['POST'])
def process_text_route():
    """Handles form submission, processing, and renders result."""
    start_time = time.time()
    log.info("-" * 30); log.info("Processing request...")
    request_id = str(uuid.uuid4()); log.info(f"Request ID: {request_id}")

    # --- A. Get Form Data & Settings ---
    text_from_textarea = request.form.get('text_input', '').strip()
    pdf_file = request.files.get('pdf_file')
    final_text_to_convert = None
    source_description = "textarea"
    word_timings = None # For read-along

    try: bg_volume_adjust_db = max(-60, min(0, int(request.form.get('bg_volume', -12))))
    except: bg_volume_adjust_db = -12
    try:
        ui_speed = float(request.form.get('speed', 1.0)); ui_speed = max(0.5, min(1.5, ui_speed))
        piper_length_scale = round(1.0 / ui_speed, 2) if ui_speed > 0 else 1.0
    except: ui_speed = 1.0; piper_length_scale = 1.0
    selected_voice_key = request.form.get('voice', DEFAULT_VOICE_KEY)
    if selected_voice_key not in AVAILABLE_VOICES: selected_voice_key = DEFAULT_VOICE_KEY
    selected_voice_filename_base = AVAILABLE_VOICES[selected_voice_key]
    voice_model_path = os.path.join(PIPER_VOICES_DIR, f"{selected_voice_filename_base}.onnx")
    log.info(f"Params: Vol={bg_volume_adjust_db}dB, Speed={ui_speed}x (Scale={piper_length_scale}), Voice='{selected_voice_key}'")

    # --- B. Define Unique Filenames ---
    speech_filename = f"speech_{request_id}.wav"
    speech_filepath = os.path.join(OUTPUT_DIR, speech_filename)
    mixed_filename = f"mixed_{request_id}.mp3"
    mixed_filepath = os.path.join(OUTPUT_DIR, mixed_filename)
    bg_music_filepath = None
    uploaded_bg_filename = None
    uploaded_pdf_filename = None
    pdf_temp_filepath = None
    final_output_filename = None

    # --- C. Determine Text Source (PDF or Textarea) ---
    if pdf_file and pdf_file.filename:
        if not PYMUPDF_AVAILABLE: flash("PDF processing disabled.", "warning")
        elif allowed_text_file(pdf_file.filename):
            try:
                uploaded_pdf_filename = secure_filename(pdf_file.filename)
                pdf_filename_unique = f"doc_{request_id}.pdf"
                pdf_temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename_unique)
                pdf_file.save(pdf_temp_filepath)
                log.info(f"PDF saved as '{pdf_filename_unique}' for processing.")
                doc = fitz.open(pdf_temp_filepath)
                final_text_to_convert = "".join(page.get_text("text") for page in doc)
                doc.close(); final_text_to_convert = final_text_to_convert.strip()
                source_description = f"PDF ('{uploaded_pdf_filename}')"; log.info(f"Extracted {len(final_text_to_convert)} chars from PDF.")
                try: os.remove(pdf_temp_filepath); log.info(f"Removed temp PDF: {pdf_filename_unique}")
                except OSError as e: log.error(f"Failed to remove temp PDF {pdf_temp_filepath}: {e}")
                pdf_temp_filepath = None
            except Exception as e:
                log.exception(f"Error processing PDF '{uploaded_pdf_filename}'.")
                flash(f"Error reading PDF '{uploaded_pdf_filename}'. Is it valid?", "error")
                if pdf_temp_filepath and os.path.exists(pdf_temp_filepath):
                    try: os.remove(pdf_temp_filepath)
                    except OSError: pass
                return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key))
        else:
             flash("Invalid document file type (PDF only).", "error")
             return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key))
    # Use textarea if no PDF text extracted
    if not final_text_to_convert:
        final_text_to_convert = text_from_textarea
        source_description = "textarea"
    # Final check for any text
    if not final_text_to_convert:
        log.warning("No text found from PDF or textarea.")
        flash("Please enter text or upload a valid PDF.", "error")
        return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key))

    # --- D. Handle Background Music Upload ---
    if 'bg_music_file' in request.files:
         bg_file = request.files['bg_music_file']
         if bg_file and bg_file.filename:
             if allowed_bg_file(bg_file.filename):
                 try:
                     original_bg_filename = secure_filename(bg_file.filename)
                     file_ext = original_bg_filename.rsplit('.', 1)[1].lower()
                     uploaded_bg_filename_unique = f"bg_{request_id}.{file_ext}"
                     bg_music_filepath = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_bg_filename_unique)
                     bg_file.save(bg_music_filepath)
                     uploaded_bg_filename = original_bg_filename # Store original for messages
                     log.info(f"BG music '{original_bg_filename}' saved as '{uploaded_bg_filename_unique}'.")
                 except Exception as e:
                     log.exception(f"Error saving BG file '{original_bg_filename}'.")
                     flash(f"Error saving background music.", "error")
                     return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))
             else:
                 log.warning(f"Invalid BG file type: {bg_file.filename}")
                 flash(f"Invalid background music file type. Allowed: {', '.join(ALLOWED_BG_EXTENSIONS)}", "error")
                 return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))


    # --- E. Piper TTS Generation ---
    try:
        log.info(f"Generating speech ({speech_filename}) from {source_description}...")
        if not os.path.exists(PIPER_EXE_PATH): raise FileNotFoundError("Piper executable missing")
        if not os.path.exists(voice_model_path): raise FileNotFoundError(f"Voice model missing: {voice_model_path}")
        command = [
            PIPER_EXE_PATH, '--model', voice_model_path,
            '--output_file', speech_filepath,
            '--length_scale', str(piper_length_scale)
        ]
        log.info(f"Running Piper: {' '.join(map(shlex.quote, command))}")
        process = subprocess.run( command, input=final_text_to_convert.encode('utf-8'), capture_output=True, check=True, cwd=PIPER_DIR)
        log.debug(f"Piper stdout: {process.stdout.decode('utf-8', errors='ignore')}")
        log.debug(f"Piper stderr: {process.stderr.decode('utf-8', errors='ignore')}")
        if not os.path.exists(speech_filepath) or os.path.getsize(speech_filepath) == 0:
            raise Exception("Piper output file missing/empty.")
        log.info(f"Generated speech: {speech_filepath}")

    except subprocess.CalledProcessError as e:
        log.error(f"Piper execution failed (rc={e.returncode}): {e}", exc_info=False)
        log.error(f"Piper stderr: {e.stderr.decode('utf-8', errors='ignore') if e.stderr else 'N/A'}")
        flash("Audio generation failed: TTS engine error.", "error")
        return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))
    except FileNotFoundError as e:
        log.error(f"Missing file for Piper: {e}")
        flash(f"Server configuration error: {e}", "error")
        return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))
    except Exception as e:
        log.exception(f"Unexpected error during TTS: {e}")
        flash("Unexpected server error during speech generation.", "error")
        return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))


    # --- F. Word Timing Generation (SIMULATED) ---
    normalized_input = ' '.join(final_text_to_convert.lower().split())
    normalized_example = ' '.join(EXAMPLE_SENTENCE.lower().split())
    if normalized_input == normalized_example:
         log.info("Input matches example sentence. Using pre-defined timings for demo.")
         word_timings = EXAMPLE_TIMINGS
         if abs(piper_length_scale - 1.0) > 0.05:
             log.warning("Speed != 1.0x, example timings may mismatch audio!")
             flash("Read-along timings shown are for normal speed only.", "warning")
    else:
         log.info("Input doesn't match example. Read-along disabled.")


    # --- G. Audio Mixing ---
    try:
        final_output_filename = speech_filename # Default output
        final_output_filepath = speech_filepath

        if bg_music_filepath: # Mix only if BG music uploaded
            if not FFMPEG_FOUND or not PYDUB_AVAILABLE:
                log.warning("Mixing skipped (ffmpeg/pydub missing).")
                flash("Mixing unavailable due to server setup. Playing speech only.", "warning")
            else:
                log.info(f"Attempting mixing: Speech='{speech_filename}', BG='{uploaded_bg_filename}'")
                speech_audio = background_audio = mixed_audio = None
                try:
                    speech_audio = AudioSegment.from_file(speech_filepath)
                    log.info(f"Loaded speech ({len(speech_audio)/1000.0:.2f}s)")
                    background_audio = AudioSegment.from_file(bg_music_filepath)
                    log.info(f"Loaded background ({len(background_audio)/1000.0:.2f}s)")

                    # Perform Mixing with Looping Background
                    background_adjusted = background_audio + bg_volume_adjust_db
                    speech_duration = len(speech_audio); bg_duration = len(background_adjusted)
                    if bg_duration <= 0: raise ValueError("BG audio has no duration.")
                    log.debug(f"Speech duration: {speech_duration}ms, BG duration: {bg_duration}ms")
                    if bg_duration < speech_duration:
                        log.info("Looping background to match speech length.")
                        times_to_loop = (speech_duration // bg_duration) + 1
                        looped_background = background_adjusted * times_to_loop
                        background_final = looped_background[:speech_duration]
                    else:
                        log.info("Trimming background to match speech length.")
                        background_final = background_adjusted[:speech_duration]
                    log.debug(f"Final BG duration: {len(background_final)}ms")
                    mixed_audio = background_final.overlay(speech_audio, position=0)
                    log.info(f"Mixed audio created ({len(mixed_audio)/1000.0:.2f}s). Exporting...")
                    # Export
                    mixed_audio.export(mixed_filepath, format="mp3", bitrate="192k")
                    log.info("Audio mixing and export successful.")
                    final_output_filename = mixed_filename # Update final output
                    final_output_filepath = mixed_filepath

                except CouldntDecodeError as e:
                    log.exception(f"Pydub decode error (BG='{uploaded_bg_filename}').")
                    flash(f"Mixing Error: Could not decode '{uploaded_bg_filename}'. Playing speech only.", "warning")
                except FileNotFoundError as e:
                    log.exception(f"File not found during mixing: {e}")
                    flash("Mixing Error: Required audio file missing.", "error")
                except Exception as e:
                    log.exception(f"Unexpected error during mixing/export.")
                    flash("Mixing Error: Processing failed. Playing speech only.", "warning")
                finally: del speech_audio, background_audio, mixed_audio


        # --- H. Render Result ---
        if not final_output_filename:
             log.error("Critical error: No final output filename determined.")
             flash("Critical server error preparing result.", "error")
             return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))

        log.info(f"Rendering result page. Final audio: {final_output_filename}")
        processing_time = time.time() - start_time; log.info(f"Total request processing time: {processing_time:.2f} seconds")

        # Prepare context for rendering
        render_context = {
            'audio_filename': final_output_filename,
            'default_bg_volume': bg_volume_adjust_db,
            'text_input': text_from_textarea, # Original text area content
            'pdf_filename': uploaded_pdf_filename, # Name of PDF if used
            'available_voices': AVAILABLE_VOICES,
            'selected_voice_key': selected_voice_key,
            'default_voice_key': DEFAULT_VOICE_KEY,
            'default_speed': ui_speed,
            'pdf_enabled': PYMUPDF_AVAILABLE,
            'word_timings': word_timings, # Timing data (or None)
            'original_text': final_text_to_convert, # Text used for audio/timings
            'example_sentence': EXAMPLE_SENTENCE
        }
        return render_template('index.html', **render_context)

    except Exception as e:
        # Catch-all for unexpected errors during the main processing flow
        log.exception(f"Critical unexpected error during request processing.")
        flash("A critical server error occurred. Please check logs.", "error")
        return redirect(url_for('home', default_bg_volume=bg_volume_adjust_db, speed=ui_speed, voice=selected_voice_key, text_input=text_from_textarea))


# =========================================
# Part 3: Serve Audio Route & App Run
# =========================================

@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """Serves generated audio files securely from the output directory."""
    log.info(f"Serving audio file request: {filename}")
    if '..' in filename or filename.startswith('/'):
         log.warning(f"Attempted directory traversal: {filename}")
         return "Invalid filename.", 400
    try:
        file_path = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(file_path):
             log.error(f"Requested audio file not found: {file_path}")
             return "Audio file not found.", 404
        log.debug(f"Sending file: {file_path}")
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)
    except Exception as e:
         log.exception(f"Error serving audio file '{filename}': {e}")
         return "Error serving file.", 500

# --- Run the Flask App ---
if __name__ == '__main__':
    log.info("-" * 50)
    log.info("Starting Flask Text-to-Audio Application...")
    log.info(f"Debug mode: {app.debug}")
    # Use 0.0.0.0 to make accessible on local network (use with caution)
    app.run(debug=True, host='0.0.0.0', port=5000)