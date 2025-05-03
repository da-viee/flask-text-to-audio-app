# Text to Audio Converter with Background Music

A web application built with Flask (Python) that converts text (typed or from PDF) into speech using Piper TTS, optionally mixing it with user-uploaded background music. Includes voice selection, speed control, and volume adjustment for background audio. Features a simulated read-along transcript display.

## Features

*   Text-to-Speech using local Piper TTS engine.
*   PDF text extraction for TTS input (requires PyMuPDF).
*   Selectable TTS voices (requires downloading Piper models).
*   Adjustable speech speed.
*   Upload custom background music (MP3, WAV, etc.).
*   Adjustable background music volume relative to speech.
*   Audio mixing (requires ffmpeg).
*   Unique output filenames for each conversion.
*   Time-based cleanup of old generated/uploaded files.
*   Simulated read-along transcript highlighting (works only for a specific example sentence).
*   Fullscreen read-along mode.

## Prerequisites

*   Python 3.9+
*   `pip` (Python package installer)
*   `ffmpeg`: Must be installed and accessible in the system's PATH. ([Download ffmpeg](https://ffmpeg.org/download.html))
*   Piper TTS:
    *   Download the Piper executable for your OS from [Piper Releases](https://github.com/rhasspy/piper/releases).
    *   Extract it into a `piper` subfolder within this project directory.
    *   Download desired voice models (both `.onnx` and `.onnx.json` files) from [Piper Voices](https://huggingface.co/rhasspy/piper-voices/tree/main).
    *   Place the voice model files inside a `piper/voices` subfolder.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd text_to_audio_app
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # Windows PowerShell:
    .\venv\Scripts\Activate.ps1
    # Windows CMD:
    # .\venv\Scripts\activate.bat
    # macOS / Linux:
    # source venv/bin/activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    # If using Python 3.13+ and encountering audioop errors:
    # pip install audioop-lts
    ```
4.  **Configure Voices:**
    *   Ensure Piper and voice files are placed correctly as described in Prerequisites.
    *   Edit the `AVAILABLE_VOICES` dictionary near the top of `app.py` to match the voice models you have downloaded and want to offer. Update `DEFAULT_VOICE_KEY` if needed.

## Running the Application

1.  Make sure your virtual environment is activated.
2.  Ensure `ffmpeg` is in your system PATH.
3.  Run the Flask development server:
    ```bash
    python app.py
    ```
4.  Open your web browser and navigate to `http://127.0.0.1:5000` (or `http://<your-local-ip>:5000` if accessing from another device on your network).

## Notes

*   The read-along highlighting feature is a simulation and only works accurately for the specific example sentence defined in `app.py` when using default speed (1.0x). Real-time alignment for arbitrary text requires integrating additional tools like MFA or aeneas.
*   Set the `FLASK_SECRET_KEY` environment variable for production environments.
*   Use a production WSGI server (like Gunicorn or Waitress) instead of the Flask development server for deployment.