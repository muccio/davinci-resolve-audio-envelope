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

- **Mappatura su Parametri Video & Effetti della Clip (Fusion & OpenFX):**
  - **🎯 Preset Rapidi (Auto-creazione del nodo):**
    - *Transform*: Zoom (`Size`), Rotazione (`Angle`), Spostamento X/Y (`Center_X`, `Center_Y`), Deformazione Scala (`XSize`, `YSize`).
    - *Brightness & Contrast*: Flash / Boost (`Gain`), Ombre (`Lift`), Toni Medi (`Gamma`), Saturazione (`Saturation`).
    - *Blur*: Sfocatura Dinamica (`BlurSize`), Mix Trasparenza (`Blend`).
    - *Glow*: Bagliore Luminoso (`Glow`), Raggio Espansione (`GlowSize`).
    - *Camera Shake*: Terremoto / Scuotimento (`OverallStrength`), Velocità (`Speed`), Vibrazione Orizzontale (`XShake`) e Verticale (`YShake`).
    *(Se il nodo non è presente nella composizione Fusion della clip, lo script lo crea e lo collega automaticamente tra `MediaIn` e `MediaOut`).*
  - **✨ Sfoglia Effetti sulla Clip (Nodi Fusion & OpenFX esistenti):**
    - Scansione dinamica in tempo reale di **qualsiasi effetto o plugin OpenFX/ResolveFX** già applicato alla clip video (es. Gaussian Blur, Directional Blur, Color Corrector, Glow, Film Grain, Stylize, ecc.).
    - Rilevamento automatico di tutti i parametri animabili di tipo **Number** (scalari) e **Point** (coordinate 2D con separazione automatica degli assi X e Y).
    - Calcolo intelligente dei valori di default per Min e Max basato sul valore corrente e sui limiti di scala del cursore.
    - Pulsante `↻ Rileva` per ri-scansionare istantaneamente la clip se aggiungi un effetto durante la sessione.

- **Iniezione Keyframe Fusion ad Alte Prestazioni:**
  - Crea o recupera la Fusion Composition incorporata nel `TimelineItem` video.
  - Utilizza `comp.Lock()` e `comp.Unlock()` per iniettare centinaia di keyframe in frazioni di secondo.
  - Collega automaticamente le curve `BezierSpline` e `XYPath` per un'interpolazione fluida senza creare conflitti.

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
   - Seleziona la traccia audio e la traccia video (clicca su *Rileva Clip su Playhead* per verificare i file).
   - Scegli la **Modalità Target**:
     - **🎯 Preset Rapidi**: seleziona parametri pronti per Transform, Flash, Blur, Glow o Camera Shake.
     - **✨ Effetti sulla Clip**: seleziona qualsiasi effetto già presente sulla clip video (es. plugin OpenFX, ResolveFX o nodi Fusion) e scegli il parametro numerico o asse X/Y da modulare.
   - Scegli la **Banda Audio FFT** (es. `Sub-Bass / Cassa (20 - 90 Hz)` per far tremare o zoomare sul kick, oppure `Full Spectrum`).
   - Regola **Attack**, **Release** e **Smoothing**.
   - Clicca su **`⚡ ESTRAI AUDIO & GENERA AUTOMAZIONE ⚡`**.
6. Premi **Play** nella timeline per vedere subito la clip video o il suo effetto modulato sul ritmo dell'audio!

---

## 🔧 Risoluzione Problemi (Troubleshooting)

### La finestra non compare / Errore di connessione API
- **Porta 49152 occupata:** L'architettura di scripting di DaVinci Resolve utilizza la porta 1144 e alloca la porta di ritorno IPC nel range `49152..65535` (di default `127.0.0.1:49152`). Se un'altra applicazione (ad es. **Ollama**) occupa la porta locale `49152`, la connessione fallirà restituendo `None`. Per verificare ed eventualmente liberare la porta:
  ```bash
  lsof -i :49152
  ```
- **Progetto attivo:** Assicurati che DaVinci Resolve Studio sia aperto con un progetto caricato e una timeline attiva nella Edit Page.

---

## 🧪 Test Unitari

Per eseguire la suite di test automatizzati:
```bash
python3 -m unittest test_audio_envelope.py
```

---

## 📄 Licenza
Rilasciato sotto licenza MIT.
