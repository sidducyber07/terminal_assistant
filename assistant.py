#!/usr/bin/env python3
"""
Nova — Voice Terminal Assistant

A terminal-based voice assistant that listens, understands, and replies.

Architecture:
  ┌─────────────┐     ┌──────────────┐     ┌───────────────┐
  │ Input Layer  │────▶│ CommandHandler│────▶│  Output Layer  │
  │ Text / Mic   │     │  (the brain)  │     │ Text / Speaker │
  └─────────────┘     └──────────────┘     └───────────────┘

Run:  python assistant.py
"""

# ============================================================
# IMPORTS
# ============================================================

import datetime
import random
import logging
import sys
import os
import json
import threading
import webbrowser
import re
import time
from pathlib import Path

# --- Optional: Text-to-Speech ---
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

# --- Optional: Speech Recognition ---
try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

VOICE_INPUT_AVAILABLE = SR_AVAILABLE and PYAUDIO_AVAILABLE


# ============================================================
# LOGGING SETUP
# ============================================================
# logging is better than print() for debugging.
# You can control: what gets shown, where it goes, and the format.
# In production code, ALWAYS use logging instead of print for
# diagnostic messages.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Nova")


# ============================================================
# CONFIGURATION
# ============================================================
# All configurable values live here. In a real app, you'd
# load these from a config file or environment variables.

class Config:
    """Central configuration for the assistant."""
    
    # Identity
    ASSISTANT_NAME = "Jarvis"
    
    # Data storage directory (created automatically)
    DATA_DIR = Path(__file__).parent / "data"
    NOTES_FILE = DATA_DIR / "notes.json"
    REMINDERS_FILE = DATA_DIR / "reminders.json"
    
    # Voice output settings
    VOICE_RATE = 180          # Words per minute
    VOICE_VOLUME = 0.9        # 0.0 to 1.0
    VOICE_INDEX = 1           # Voice index (0=male-ish, 1=female-ish, varies by OS)
    
    # Voice input settings
    LISTEN_TIMEOUT = 5        # Seconds to wait for speech to start
    PHRASE_TIME_LIMIT = 10    # Max seconds of speech
    AMBIENT_NOISE_DURATION = 0.5  # Seconds to calibrate for background noise
    
    # Behavior
    HISTORY_SIZE = 20         # How many past commands to remember
    
    # Music platforms
    MUSIC_PLATFORMS = {
        "youtube": "https://www.youtube.com/results?search_query={query}",
        "spotify": "https://open.spotify.com/search/{query}",
        "soundcloud": "https://soundcloud.com/search/sounds?q={query}",
    }
    DEFAULT_MUSIC_PLATFORM = "youtube"
    
    # Fun
    JOKES = [
        "Why do programmers prefer dark mode? Because light attracts bugs!",
        "Why did the Python developer go broke? Because he couldn't C!",
        "There are only 10 types of people: those who understand binary and those who don't.",
        "A SQL query walks into a bar, sees two tables, and asks: Can I join you?",
        "Why do Java developers wear glasses? Because they don't C#!",
        "What's a programmer's favorite hangout place? Foo Bar!",
    ]
    
    FACTS = [
        "The first computer bug was an actual bug — a moth found in a Harvard Mark II computer in 1947.",
        "Python was named after Monty Python's Flying Circus, not the snake.",
        "The first 1GB hard drive, announced in 1980, weighed about 550 pounds and cost $40,000.",
        "There are about 700 programming languages in the world.",
        "The word 'robot' comes from the Czech word 'robota', meaning forced labor.",
    ]


# ============================================================
# SERVICE: Note Manager
# ============================================================

class NoteManager:
    """
    Manages persistent notes stored in a JSON file.
    
    Notes are saved between sessions — they survive app restarts.
    Each note has an id, text, and timestamp.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.notes = []
        self._load()
    
    def _load(self):
        """Load notes from disk."""
        self.config.DATA_DIR.mkdir(exist_ok=True)
        try:
            if self.config.NOTES_FILE.exists():
                with open(self.config.NOTES_FILE, "r", encoding="utf-8") as f:
                    self.notes = json.load(f)
                logger.info("Loaded %d notes from disk", len(self.notes))
            else:
                self.notes = []
        except Exception as e:
            logger.warning("Failed to load notes: %s", e)
            self.notes = []
    
    def _save(self):
        """Save notes to disk."""
        try:
            self.config.DATA_DIR.mkdir(exist_ok=True)
            with open(self.config.NOTES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.notes, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save notes: %s", e)
    
    def add(self, text: str) -> str:
        """
        Add a new note. Returns a confirmation message.
        """
        note = {
            "id": len(self.notes) + 1,
            "text": text,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        }
        self.notes.append(note)
        self._save()
        return f"📝 Note saved! (Note #{note['id']})"
    
    def list_notes(self) -> str:
        """Return a formatted list of all notes."""
        if not self.notes:
            return "You don't have any notes yet. Say 'take a note: ...' to create one."
        
        lines = [f"📒 You have {len(self.notes)} note(s):"]
        for note in self.notes:
            lines.append(f"  #{note['id']} [{note['timestamp']}] {note['text']}")
        return "\n".join(lines)
    
    def clear(self) -> str:
        """Delete all notes."""
        count = len(self.notes)
        self.notes = []
        self._save()
        return f"🗑️ Cleared {count} note(s)."
    
    def delete(self, note_id: int) -> str:
        """Delete a specific note by ID."""
        for i, note in enumerate(self.notes):
            if note["id"] == note_id:
                removed = self.notes.pop(i)
                self._save()
                return f"🗑️ Deleted note #{note_id}: \"{removed['text']}\""
        return f"Note #{note_id} not found. Say 'show notes' to see your notes."


# ============================================================
# SERVICE: Reminder Manager
# ============================================================

class ReminderManager:
    """
    Manages timed reminders using background threads.
    
    Reminders fire after a specified delay, then alert the user
    via the output layer (text + voice).
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.reminders = []       # Active reminder trackers
        self._next_id = 1
        self._output = None       # Set later via set_output()
    
    def set_output(self, output: 'OutputLayer'):
        """Inject the output layer so reminders can speak when they fire."""
        self._output = output
    
    def add(self, task: str, delay_seconds: float) -> str:
        """
        Set a reminder. Fires after delay_seconds.
        Returns a confirmation message.
        """
        rid = self._next_id
        self._next_id += 1
        fire_time = datetime.datetime.now() + datetime.timedelta(seconds=delay_seconds)
        fire_time_str = fire_time.strftime("%I:%M %p")
        
        # Build a human-readable duration
        if delay_seconds >= 3600:
            hours = delay_seconds / 3600
            duration_str = f"{hours:.1f} hour(s)"
        elif delay_seconds >= 60:
            minutes = delay_seconds / 60
            duration_str = f"{minutes:.0f} minute(s)"
        else:
            duration_str = f"{delay_seconds:.0f} second(s)"
        
        # Create the timer thread
        timer = threading.Timer(delay_seconds, self._fire_reminder, args=[rid, task])
        timer.daemon = True  # Dies when main program exits
        timer.start()
        
        reminder = {
            "id": rid,
            "task": task,
            "fire_time": fire_time_str,
            "timer": timer,
            "active": True,
        }
        self.reminders.append(reminder)
        
        return f"⏰ Reminder set! I'll remind you to \"{task}\" in {duration_str} (at {fire_time_str})."
    
    def _fire_reminder(self, rid: int, task: str):
        """Called by the timer thread when a reminder fires."""
        # Mark as inactive
        for r in self.reminders:
            if r["id"] == rid:
                r["active"] = False
        
        # Alert the user
        alert_msg = f"🔔 REMINDER: {task}"
        print(f"\n{'=' * 50}")
        print(f"  {alert_msg}")
        print(f"{'=' * 50}\n")
        
        if self._output:
            self._output.say(f"Reminder! {task}")
    
    def list_reminders(self) -> str:
        """Return a formatted list of active reminders."""
        active = [r for r in self.reminders if r["active"]]
        if not active:
            return "No active reminders. Say 'remind me to [task] in [N] minutes' to set one."
        
        lines = [f"⏰ You have {len(active)} active reminder(s):"]
        for r in active:
            lines.append(f"  #{r['id']} \"{r['task']}\" — fires at {r['fire_time']}")
        return "\n".join(lines)
    
    def cancel_all(self) -> str:
        """Cancel all active reminders."""
        active = [r for r in self.reminders if r["active"]]
        count = 0
        for r in active:
            r["timer"].cancel()
            r["active"] = False
            count += 1
        return f"❌ Cancelled {count} reminder(s)."


# ============================================================
# SERVICE: Music Player
# ============================================================

class MusicPlayer:
    """
    Opens music in the user's browser on the specified platform.
    
    Supported platforms: YouTube, Spotify, SoundCloud.
    Falls back to YouTube if no platform is specified.
    """
    
    def __init__(self, config: Config):
        self.config = config
    
    def play(self, query: str, platform: str = None) -> str:
        """
        Search for and play music by opening the browser.
        
        Parameters:
            query: Song/artist name to search for
            platform: 'youtube', 'spotify', or 'soundcloud'
        
        Returns:
            Confirmation message
        """
        platform = (platform or self.config.DEFAULT_MUSIC_PLATFORM).lower()
        
        if platform not in self.config.MUSIC_PLATFORMS:
            available = ", ".join(self.config.MUSIC_PLATFORMS.keys())
            return f"Unknown platform '{platform}'. Available: {available}"
        
        # Build the URL
        url_template = self.config.MUSIC_PLATFORMS[platform]
        encoded_query = query.replace(" ", "+")
        url = url_template.format(query=encoded_query)
        
        # Open in browser
        try:
            webbrowser.open(url)
            return f"🎵 Playing \"{query}\" on {platform.capitalize()}!"
        except Exception as e:
            return f"Couldn't open browser: {e}"
    
    @staticmethod
    def extract_platform(text: str) -> tuple:
        """
        Extract the song query and platform from user text.
        
        Examples:
            "play bohemian rhapsody"           → ("bohemian rhapsody", None)
            "play bohemian rhapsody on spotify" → ("bohemian rhapsody", "spotify")
            "play shape of you on youtube"      → ("shape of you", "youtube")
        
        Returns:
            (query, platform) — platform is None if not specified
        """
        # Remove "play" keyword
        text = text.lower()
        text = re.sub(r"^play\s+", "", text)
        
        platform = None
        
        # Check for "on [platform]" pattern (e.g., "on youtube", "on spotify")
        match = re.search(r'\s+on\s+(youtube|spotify|soundcloud)\b', text)
        if match:
            platform = match.group(1)
            text = text[:match.start()] + text[match.end():]
        else:
            # Check for platform mentioned anywhere (e.g., "on youtube shape of you")
            match = re.search(r'\b(youtube|spotify|soundcloud)\b', text)
            if match:
                platform = match.group(1)
                text = text[:match.start()] + text[match.end():]
        
        query = text.strip()
        return query, platform


# ============================================================
# LAYER 1: OUTPUT — Voice and Text Output
# ============================================================

class OutputLayer:
    """
    Handles all output — both text (terminal) and voice (TTS).
    
    This layer knows nothing about HOW responses are generated.
    It only knows HOW to display/speak them.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.tts_engine = None
        
        if TTS_AVAILABLE:
            try:
                self.tts_engine = pyttsx3.init()
                self.tts_engine.setProperty('rate', config.VOICE_RATE)
                self.tts_engine.setProperty('volume', config.VOICE_VOLUME)
                
                voices = self.tts_engine.getProperty('voices')
                if voices and len(voices) > config.VOICE_INDEX:
                    self.tts_engine.setProperty('voice', voices[config.VOICE_INDEX].id)
                
                logger.info("TTS engine initialized (%d voices available)", len(voices) if voices else 0)
            except Exception as e:
                logger.warning("TTS initialization failed: %s", e)
                self.tts_engine = None
    
    def respond(self, text: str, speak: bool = True):
        """
        Output a response both as text and optionally as speech.
        
        Parameters:
            text: The response to output
            speak: Whether to also speak it aloud
        """
        # Always print to terminal
        name = self.config.ASSISTANT_NAME
        print(f"🤖 {name}: {text}")
        
        # Optionally speak
        if speak and self.tts_engine:
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
            except Exception as e:
                logger.warning("TTS speak failed: %s", e)
    
    def say(self, text: str):
        """Speak text without printing to terminal."""
        if self.tts_engine:
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
            except Exception:
                pass
    
    def list_voices(self):
        """Print all available TTS voices."""
        if not self.tts_engine:
            print("  No TTS engine available.")
            return []
        
        voices = self.tts_engine.getProperty('voices')
        print(f"  Available voices ({len(voices)}):")
        for i, voice in enumerate(voices):
            marker = " ◀ current" if i == self.config.VOICE_INDEX else ""
            print(f"    [{i}] {voice.name}{marker}")
        return voices
    
    def set_voice(self, index: int):
        """Switch to a different voice by index."""
        if not self.tts_engine:
            return False
        voices = self.tts_engine.getProperty('voices')
        if 0 <= index < len(voices):
            self.tts_engine.setProperty('voice', voices[index].id)
            self.config.VOICE_INDEX = index
            logger.info("Switched to voice: %s", voices[index].name)
            return True
        return False


# ============================================================
# LAYER 2: INPUT — Voice and Text Input
# ============================================================

class InputLayer:
    """
    Handles all input — both text (keyboard) and voice (microphone).
    
    This layer knows nothing about HOW responses are generated.
    It only knows HOW to capture user input.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.recognizer = None
        self.mode = "voice" if VOICE_INPUT_AVAILABLE else "text"
        
        if VOICE_INPUT_AVAILABLE:
            try:
                self.recognizer = sr.Recognizer()
                self.recognizer.dynamic_energy_threshold = True
                self.recognizer.pause_threshold = 0.8
                logger.info("Speech recognizer initialized")
            except Exception as e:
                logger.warning("Speech recognizer failed: %s", e)
                self.recognizer = None
                self.mode = "text"
    
    def get_input(self) -> str:
        """
        Get input from the user — via voice or text depending on mode.
        
        Returns:
            str: The user's input text, or empty string if nothing received.
        """
        if self.mode == "voice" and self.recognizer:
            return self._get_voice_input()
        else:
            return self._get_text_input()
    
    def _get_text_input(self) -> str:
        """Get input via keyboard."""
        try:
            user_input = input(f"\n👤 You: ")
            return user_input.strip()
        except (EOFError, KeyboardInterrupt):
            return "quit"
    
    def _get_voice_input(self) -> str:
        """
        Get input via microphone + speech recognition.
        
        The flow:
        1. Wait for user to press Enter (so they control when to speak)
        2. Open the microphone
        3. Capture audio
        4. Send to Google's speech recognition API
        5. Return the recognized text
        """
        try:
            # Wait for Enter press, or allow typing as fallback
            prompt = f"\n  ⏎  Press Enter to speak (or type): "
            typed = input(prompt)
            
            if typed.strip():
                # User typed something instead of pressing Enter
                return typed.strip()
            
            # User pressed Enter — now listen via microphone
            with sr.Microphone() as source:
                print("  🎧 Listening...", end="", flush=True)
                self.recognizer.adjust_for_ambient_noise(
                    source, 
                    duration=self.config.AMBIENT_NOISE_DURATION
                )
                
                audio = self.recognizer.listen(
                    source,
                    timeout=self.config.LISTEN_TIMEOUT,
                    phrase_time_limit=self.config.PHRASE_TIME_LIMIT
                )
            
            # Process the audio
            print(" 🔄...", end="", flush=True)
            text = self.recognizer.recognize_google(audio)
            print(f"\n  🎤 Heard: \"{text}\"")
            
            return text.strip()
        
        except sr.WaitTimeoutError:
            print(" ⏰ No speech detected.")
            return ""
        except sr.UnknownValueError:
            print(" ❓ Couldn't understand.")
            return ""
        except sr.RequestError:
            print(" 🌐 Network error — check your internet connection.")
            return ""
        except Exception as e:
            logger.warning("Voice input error: %s", e)
            print(f" ❌ Error: {e}")
            return ""
    
    def set_mode(self, mode: str):
        """Switch between 'voice' and 'text' input modes."""
        if mode == "voice" and not VOICE_INPUT_AVAILABLE:
            return False, "Voice input is not available on this system."
        
        self.mode = mode
        return True, f"Switched to {mode} mode."


# ============================================================
# LAYER 3: BRAIN — Command Processing
# ============================================================

class CommandHandler:
    """
    The brain of the assistant. Processes commands and generates responses.
    
    Uses the Command Pattern — each type of command has its own handler method.
    New commands can be added by adding new methods and registering them.
    """
    
    def __init__(self, config: Config, output: OutputLayer, input_layer: InputLayer):
        self.config = config
        self.output = output
        self.input_layer = input_layer
        self.history = []  # Remember recent commands
        
        # --- Initialize services ---
        self.notes = NoteManager(config)
        self.reminders = ReminderManager(config)
        self.reminders.set_output(output)
        self.music = MusicPlayer(config)
        
        # Register all command handlers
        # Each entry: (keywords_to_match, handler_method, description)
        #
        # IMPORTANT: Order matters! Commands are checked top-to-bottom.
        # More specific commands MUST come before shorter/more general ones.
        self.commands = [
            # --- System/meta commands (most specific first) ---
            (["switch to text", "text mode", "type mode"], self._cmd_text_mode, "Switch to text input"),
            (["switch to voice", "voice mode"], self._cmd_voice_mode, "Switch to voice input"),
            (["list voices", "voices", "available voices"], self._cmd_list_voices, "List TTS voices"),
            (["set voice"], self._cmd_set_voice, "Change TTS voice (e.g., 'set voice 0')"),
            (["history", "what did i say", "past commands"], self._cmd_history, "Show command history"),
            (["how are you", "how do you feel"], self._cmd_how_are_you, "Ask how the assistant is doing"),
            (["your name", "who are you", "what are you"], self._cmd_name, "Learn about the assistant"),
            (["what can you do", "commands"], self._cmd_help, "Show available commands"),
            
            # --- Music commands ---
            (["play"], self._cmd_play_music, "Play music (e.g., 'play bohemian rhapsody on youtube')"),
            
            # --- Notes commands ---
            (["take a note", "take note", "save note", "remember that", "note this"], self._cmd_take_note, "Save a note (e.g., 'take a note buy groceries')"),
            (["show notes", "my notes", "list notes", "read notes"], self._cmd_show_notes, "Show all saved notes"),
            (["delete note", "remove note"], self._cmd_delete_note, "Delete a note by number (e.g., 'delete note 2')"),
            (["clear notes", "erase notes", "wipe notes"], self._cmd_clear_notes, "Delete all notes"),
            
            # --- Reminder commands ---
            (["remind me", "set reminder", "reminder"], self._cmd_set_reminder, "Set a reminder (e.g., 'remind me to call mom in 5 minutes')"),
            (["show reminders", "my reminders", "list reminders"], self._cmd_show_reminders, "Show active reminders"),
            (["cancel reminders", "clear reminders", "cancel all reminders"], self._cmd_cancel_reminders, "Cancel all reminders"),
            (["set timer", "timer for", "countdown"], self._cmd_set_timer, "Set a countdown timer (e.g., 'timer for 5 minutes')"),
            
            # --- Content commands ---
            (["joke", "funny", "make me laugh", "tell me a joke"], self._cmd_joke, "Hear a joke"),
            (["fact", "interesting", "tell me something", "did you know"], self._cmd_fact, "Hear an interesting fact"),
            (["thank", "thanks"], self._cmd_thanks, "Say thanks"),
            (["time", "what time"], self._cmd_time, "Get the current time"),
            (["date", "what day", "what's the date"], self._cmd_date, "Get today's date"),
            
            # --- General commands (shorter keywords, checked last) ---
            (["help"], self._cmd_help, "Show available commands"),
            (["hello", "hi", "hey", "greetings"], self._cmd_greet, "Greet the assistant"),
            (["quit", "exit", "bye", "goodbye", "stop"], self._cmd_quit, "End the conversation"),
        ]
    
    def process(self, user_input: str) -> str:
        """
        Process user input and return a response.
        
        This is the main entry point. It:
        1. Records the input in history
        2. Normalizes the text
        3. Searches through registered commands
        4. Calls the matching handler
        5. Returns the response (or a fallback)
        """
        if not user_input.strip():
            return "I didn't catch that. Could you try again?"
        
        # Store in history
        self.history.append(user_input)
        if len(self.history) > self.config.HISTORY_SIZE:
            self.history.pop(0)  # Remove oldest if we exceed the limit
        
        text = user_input.lower().strip()
        
        # Search through registered commands
        for keywords, handler, _ in self.commands:
            # Check if ANY of the keywords appear in the user's text
            # Multi-word keywords use substring match (e.g., "switch to voice" in text)
            # Single-word keywords use word-boundary match to avoid false positives
            # (e.g., "hi" should not match inside "history")
            match_found = False
            for keyword in keywords:
                if " " in keyword:
                    # Multi-word: substring match is fine
                    if keyword in text:
                        match_found = True
                        break
                else:
                    # Single-word: only match as a standalone word
                    # We split the text into words and check for exact membership
                    words = text.split()
                    if keyword in words:
                        match_found = True
                        break
            
            if match_found:
                return handler(text, user_input)
        
        # No command matched
        return self._cmd_unknown(text)
    
    # ----------------------------------------------------------
    # COMMAND HANDLERS
    # Each handler receives the lowercase text and the original input.
    # Each handler returns a response string.
    # ----------------------------------------------------------
    
    def _cmd_greet(self, text, original):
        return f"Hello! I'm {self.config.ASSISTANT_NAME}. How can I help you today?"
    
    def _cmd_name(self, text, original):
        return (
            f"My name is {self.config.ASSISTANT_NAME}. "
            f"I'm your personal voice assistant. I can tell you the time, "
            f"tell jokes, share facts, and more! Say 'help' to see everything I can do."
        )
    
    def _cmd_time(self, text, original):
        now = datetime.datetime.now()
        return now.strftime("It's currently %I:%M %p")
    
    def _cmd_date(self, text, original):
        today = datetime.datetime.now()
        return today.strftime("Today is %A, %B %d, %Y")
    
    def _cmd_how_are_you(self, text, original):
        responses = [
            "I'm doing great! Ready to help.",
            "Fantastic! What can I do for you?",
            "Running smoothly! What's on your mind?",
            "I'm good! Thanks for asking.",
        ]
        return random.choice(responses)
    
    def _cmd_joke(self, text, original):
        joke = random.choice(self.config.JOKES)
        return joke
    
    def _cmd_fact(self, text, original):
        fact = random.choice(self.config.FACTS)
        return f"Here's a fun fact: {fact}"
    
    def _cmd_thanks(self, text, original):
        responses = [
            "You're welcome! Happy to help.",
            "Anytime! That's what I'm here for.",
            "My pleasure!",
            "Glad I could help!",
        ]
        return random.choice(responses)
    
    def _cmd_help(self, text, original):
        name = self.config.ASSISTANT_NAME
        lines = [f"I'm {name}. Here's what I can do:"]
        for keywords, _, description in self.commands:
            example = keywords[0]
            lines.append(f"  • \"{example}\" — {description}")
        return "\n".join(lines)
    
    def _cmd_history(self, text, original):
        if not self.history:
            return "No commands in history yet."
        lines = ["Recent commands:"]
        for i, cmd in enumerate(self.history[-10:], 1):
            lines.append(f"  {i}. {cmd}")
        return "\n".join(lines)
    
    def _cmd_text_mode(self, text, original):
        success, msg = self.input_layer.set_mode("text")
        return msg
    
    def _cmd_voice_mode(self, text, original):
        success, msg = self.input_layer.set_mode("voice")
        return msg
    
    def _cmd_list_voices(self, text, original):
        self.output.list_voices()
        return "Voices listed above. Use 'set voice N' to switch (e.g., 'set voice 0')."
    
    def _cmd_set_voice(self, text, original):
        # Try to extract a number from the input
        parts = text.split()
        for part in parts:
            if part.isdigit():
                index = int(part)
                if self.output.set_voice(index):
                    return f"Voice changed to voice {index}."
                else:
                    return f"Invalid voice index. Use 'list voices' to see available options."
        return "Please specify a voice number. Example: 'set voice 0'"
    
    def _cmd_quit(self, text, original):
        return "__QUIT__"
    
    # --- Music Handlers ---
    
    def _cmd_play_music(self, text, original):
        """Handle 'play [song] on [platform]' commands."""
        query, platform = MusicPlayer.extract_platform(text)
        
        if not query:
            return "What would you like me to play? Try: 'play bohemian rhapsody' or 'play shape of you on spotify'"
        
        return self.music.play(query, platform)
    
    # --- Note Handlers ---
    
    def _cmd_take_note(self, text, original):
        """Handle 'take a note: [text]' commands."""
        # Extract the note text after the trigger phrase
        note_text = text
        triggers = ["take a note", "take note", "save note", "remember that", "note this"]
        for trigger in triggers:
            if trigger in note_text:
                idx = note_text.index(trigger) + len(trigger)
                note_text = note_text[idx:].strip()
                break
        
        # Strip leading colon, dash, or "that"
        note_text = re.sub(r"^[\s:,\-]*(that\s+)?", "", note_text)
        
        if not note_text:
            return "What should I note down? Try: 'take a note: buy milk tomorrow'"
        
        return self.notes.add(note_text)
    
    def _cmd_show_notes(self, text, original):
        return self.notes.list_notes()
    
    def _cmd_delete_note(self, text, original):
        # Extract note number
        numbers = re.findall(r'\d+', text)
        if numbers:
            return self.notes.delete(int(numbers[0]))
        return "Which note should I delete? Try: 'delete note 2'"
    
    def _cmd_clear_notes(self, text, original):
        return self.notes.clear()
    
    # --- Reminder Handlers ---
    
    def _parse_time_amount(self, text: str) -> float:
        """
        Extract a time duration from text and return it in seconds.
        
        Supports patterns like:
            "in 5 minutes", "in 2 hours", "in 30 seconds"
            "5 min", "2hr", "30s"
        
        Returns 0 if no time found.
        """
        # Pattern: number followed by unit
        match = re.search(
            r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b', text
        )
        if match:
            return float(match.group(1)) * 3600
        
        match = re.search(
            r'(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)\b', text
        )
        if match:
            return float(match.group(1)) * 60
        
        match = re.search(
            r'(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b', text
        )
        if match:
            return float(match.group(1))
        
        return 0
    
    def _cmd_set_reminder(self, text, original):
        """Handle 'remind me to [task] in [N] minutes'."""
        delay = self._parse_time_amount(text)
        
        if delay <= 0:
            return (
                "When should I remind you? Include a time like:\n"
                "  • 'remind me to call mom in 5 minutes'\n"
                "  • 'remind me to leave in 1 hour'\n"
                "  • 'remind me to check oven in 30 seconds'"
            )
        
        # Extract the task — everything after "remind me to" or "remind me"
        task = text
        for trigger in ["remind me to", "set reminder to", "reminder to"]:
            if trigger in task:
                idx = task.index(trigger) + len(trigger)
                task = task[idx:].strip()
                break
        else:
            if "remind me" in task:
                idx = task.index("remind me") + len("remind me")
                task = task[idx:].strip()
        
        # Remove the time portion from the task
        task = re.sub(r'\s*in\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b', '', task).strip()
        
        if not task:
            task = "unnamed task"
        
        return self.reminders.add(task, delay)
    
    def _cmd_show_reminders(self, text, original):
        return self.reminders.list_reminders()
    
    def _cmd_cancel_reminders(self, text, original):
        return self.reminders.cancel_all()
    
    def _cmd_set_timer(self, text, original):
        """Handle 'timer for 5 minutes' or 'set timer 10 minutes'."""
        delay = self._parse_time_amount(text)
        
        if delay <= 0:
            return "How long? Try: 'timer for 5 minutes' or 'set timer 30 seconds'"
        
        return self.reminders.add("Timer finished!", delay)
    
    # --- Unknown Handler ---
    
    def _cmd_unknown(self, text):
        suggestions = [
            "I'm not sure I understood that. Say 'help' to see what I can do.",
            "Hmm, I didn't quite catch that. Try rephrasing or type 'help'.",
            "I don't know how to respond to that yet. Type 'help' for options.",
        ]
        return random.choice(suggestions)


# ============================================================
# ORCHESTRATOR — Tying It All Together
# ============================================================

class Assistant:
    """
    The main orchestrator. Connects the input, brain, and output layers.
    
    This is the "Controller" in MVC-like architecture:
    - Model = CommandHandler (brain)
    - View = OutputLayer (display + voice)
    - Controller = Assistant (this class — coordinates everything)
    
    +-----------+     +----------------+     +-------------+
    | InputLayer |────▶| Assistant (this)│────▶| OutputLayer  │
    +-----------+     |                │     +-------------+
                      | CommandHandler │
                      +--------+-------+
    """
    
    def __init__(self):
        self.config = Config()
        self.output = OutputLayer(self.config)
        self.input = InputLayer(self.config)
        self.brain = CommandHandler(self.config, self.output, self.input)
        self.running = True
    
    def start(self):
        """Start the assistant's main loop."""
        self._print_banner()
        
        # Welcome message
        welcome = f"Hello! I'm {self.config.ASSISTANT_NAME}. Speak or type your message!"
        self.output.respond(welcome)
        
        # Main conversation loop
        while self.running:
            try:
                # 1. Get input
                user_input = self.input.get_input()
                
                if not user_input:
                    continue
                
                # 2. Process through brain
                response = self.brain.process(user_input)
                
                # 3. Check for quit
                if response == "__QUIT__":
                    farewell = "Goodbye! Have a great day. 🚀"
                    self.output.respond(farewell)
                    self.running = False
                    break
                
                # 4. Output the response
                self.output.respond(response)
            
            except KeyboardInterrupt:
                print("\n")
                self.output.respond("Interrupted. Goodbye!")
                self.running = False
                break
            
            except Exception as e:
                logger.error("Unexpected error: %s", e, exc_info=True)
                self.output.respond("Sorry, something went wrong. Let's try again.")
        
        print(f"\n  Session ended. Run again to chat with {self.config.ASSISTANT_NAME}!")
    
    def _print_banner(self):
        """Display the startup banner."""
        name = self.config.ASSISTANT_NAME
        width = 55
        
        print("=" * width)
        print(f"  🤖 {name} — Voice Terminal Assistant")
        print("=" * width)
        
        # Show available capabilities
        caps = []
        caps.append("🔊 Voice output" if TTS_AVAILABLE else "🔇 No voice output")
        caps.append("🎤 Voice input" if VOICE_INPUT_AVAILABLE else "⌨️  Text input only")
        
        print(f"  {'  |  '.join(caps)}")
        print(f"  Type 'help' for commands. Type 'quit' to exit.")
        print("=" * width)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    assistant = Assistant()
    assistant.start()
