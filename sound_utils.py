# ==========================================
# N.O.V.A. - Tactical Sound Utilities
# Audio chime generator using pygame-ce / pygame and in-memory wave synthesis
# Fully compatible with Python 3.14.7 runtime
# ==========================================
import io
import math
import struct
import wave
import threading
import pygame

# Ensure mixer is initialized
try:
    if not pygame.mixer.get_init():
        pygame.mixer.init()
except Exception:
    pass

def synthesize_wav_tone(frequencies, duration_per_freq=0.15, sample_rate=44100, volume=0.4):
    """
    Synthesizes a multi-frequency acoustic wave tone in memory.
    Requires no external sound files on disk and executes with zero latency.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)       # Mono
        wav_file.setsampwidth(2)      # 16-bit PCM
        wav_file.setframerate(sample_rate)
        
        for freq in frequencies:
            num_samples = int(sample_rate * duration_per_freq)
            samples = []
            for i in range(num_samples):
                # Envelope shaping to eliminate acoustic pop/click on start & end
                fade_in = min(1.0, i / (sample_rate * 0.015))
                fade_out = min(1.0, (num_samples - i) / (sample_rate * 0.015))
                envelope = fade_in * fade_out
                
                value = int(volume * 32767.0 * envelope * math.sin(2.0 * math.pi * freq * i / sample_rate))
                samples.append(struct.pack('<h', value))
            wav_file.writeframes(b''.join(samples))
            
    buffer.seek(0)
    return buffer

def play_chime(chime_type="alert", block=False):
    """
    Plays an in-memory tactical chime via pygame mixer.
    Supported types:
      - 'alert' / 'broadcast': Rising triple-tone alert (660, 880, 1100 Hz)
      - 'timer': Urgent alert pulse (950, 1400, 950, 1400 Hz)
      - 'success': Harmonious uplink chord (523, 659, 784 Hz)
      - 'error': Low frequency error buzzer (350, 260 Hz)
      - 'ping': Single crisp sonar ping (1200 Hz)
    """
    presets = {
        "alert": ([660, 880, 1100], 0.12),
        "broadcast": ([660, 880, 1100], 0.14),
        "timer": ([950, 1400, 950, 1400], 0.12),
        "success": ([523, 659, 784], 0.10),
        "error": ([350, 260], 0.15),
        "ping": ([1200], 0.18)
    }
    
    freqs, dur = presets.get(chime_type, ([880, 1320], 0.15))
    
    def _play():
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            buf = synthesize_wav_tone(freqs, duration_per_freq=dur)
            sound = pygame.mixer.Sound(buf)
            channel = sound.play()
            if block and channel:
                while channel.get_busy():
                    pygame.time.Clock().tick(20)
        except Exception as e:
            # Silently degrade if audio device is locked or unavailable
            pass
            
    if block:
        _play()
    else:
        threading.Thread(target=_play, daemon=True).start()
