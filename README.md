# DaVinci Resolve - Audio Envelope to Video Keyframes 🎵➡️🎬

Un potente script Python standalone per **DaVinci Resolve (19, 20, 21+)** che converte il profilo dinamico d'ampiezza o una specifica banda di frequenza (analisi **FFT**) di una traccia audio in curve di keyframe applicate a parametri video direttamente nella **Edit Page** tramite Fusion Composition incorporata, senza costringere l'utente a lavorare nella pagina Fusion.

---

## ✨ Funzionalità Principali

- **Analisi Spettrale FFT & Filtro Passa-Banda:**
  - Motore Radix-2 Cooley-Tukey iterativo ad alte prestazioni con finestra di Hann (`PurePythonFFT` con fallback automatico su `numpy`).
  - Isolamento selettivo di frequenze musicali con preset dedicati:
    - *Sub-Bass / Cassa (Kick)*: 20 – 90 Hz
    - *Bass / Linea di Basso*: 80 – 250 Hz
    - *Low-Mid / Corpo Rullante*: 250 – 600 Hz
    - *Midrange / Voci & Lead*: 600 – 2.500 Hz
    - *High-Mid / Presenza & Attacco*: 2.500 – 7.000 Hz
    - *Treble / Hi-Hat & Piatti*: 7.000 – 18.000 Hz
    - *Tutto lo spettro (Full Spectrum)*: 20 – 20.000 Hz
    - *Personalizzato (Custom Range)*: imposta liberamente qualsiasi intervallo in Hz.

- **DSP Envelope Follower Avanzato:**
  - Calcolo frame-accurate con supporto completo ai framerate frazionari (`23.976`, `29.97`, `59.94` fps).
  - Filtro IIR asimmetrico per tarare separatamente **Attack** (reattività sui transienti) e **Release** (decadimento/coda).
  - Media mobile centrata (**Moving Average Smoothing**) per stabilizzare la risposta visiva.
  - Normalizzazione e rimappatura lineare nel range `[Min, Max]` scelto.

- **Iniezione Keyframe Fusion ad Alte Prestazioni:**
  - Crea o recupera la Fusion Composition incorporata nel `TimelineItem` video.
  - Genera nodi dedicati (`AudioEnvelope_Transform` o `AudioEnvelope_BC`) e li collega in pipeline prima di `MediaOut1` senza alterare eventuali nodi esistenti.
  - Utilizza `comp.Lock()` e `comp.Unlock()` per iniettare centinaia di keyframe in frazioni di secondo.
  - Collega automaticamente le curve `BezierSpline` e `XYPath` per un'interpolazione fluida.

- **Decodifica Audio Multi-Tier Resiliente:**
  - Supporta file **WAV, AIFF, MP3, AAC, M4A, ALAC, FLAC, MOV, MP4**.
  - Su macOS sfrutta lo strumento di sistema nativo Apple `/usr/bin/afconvert` (zero dipendenze).
  - Su tutti i sistemi supporta fallback automatici su `soundfile`, `scipy.io.wavfile`, il modulo standard `wave` e `ffmpeg`.

- **Interfaccia Utente Nativa (UIManager & UIDispatcher):**
  - Costruita esclusivamente con le API native di DaVinci Resolve.
  - Perfetta integrazione con il tema scuro di Resolve senza dipendenze pesanti (Qt/Tkinter non necessarie).

---

## 🚀 Installazione

Copia `AudioEnvelopeToVideo.py` nella cartella degli script di DaVinci Resolve:

### macOS
```bash
cp AudioEnvelopeToVideo.py ~/Library/Application\ Support/Blackmagic\ Design/DaVinci\ Resolve/Fusion/Scripts/Utility/
```
*(Oppure in `.../Fusion/Scripts/Edit/`)*

### Windows
```cmd
copy AudioEnvelopeToVideo.py "%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\"
```

### Linux
```bash
cp AudioEnvelopeToVideo.py ~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/
```

---

## 🖥️ Utilizzo

1. Apri il tuo progetto in **DaVinci Resolve** e posizionati nella **Edit Page**.
2. Allinea una traccia audio e una clip video sulla timeline.
3. Posiziona il **playhead** sopra le clip da elaborare.
4. Vai nel menu in alto: **`Workspace` > `Scripts` > `AudioEnvelopeToVideo`**.
5. Nella GUI:
   - Seleziona la traccia audio e la traccia video.
   - Scegli la **Proprietà Target** (es. `Transform: Size (Zoom)`, `BrightnessContrast: Gain`, `Transform: Angle`, ecc.).
   - Scegli la **Banda Audio** (es. `Sub-Bass / Cassa (20 - 90 Hz)`).
   - Regola **Attack**, **Release** e **Smoothing**.
   - Clicca su **`⚡ ESTRAI AUDIO & GENERA AUTOMAZIONE ⚡`**.
6. Premi **Play** nella timeline per vedere subito la clip video pulsare a ritmo di musica!

---

## 🧪 Test Unitari

Per eseguire la suite di test automatizzati:
```bash
python3 -m unittest test_audio_envelope.py
```

---

## 📄 Licenza
Rilasciato sotto licenza MIT.
