# VoiceBridge

VoiceBridge e' un'app desktop Windows per trasformare documenti in audio, trascrivere audio/video, creare sottotitoli e fare piccoli interventi di cleanup su audio e video.

La guida operativa completa e' in [Manual.md](Manual.md).

## Funzioni principali

- Text to Speech online con Microsoft Edge TTS.
- Local TTS opzionale con profili vocali autorizzati e Coqui XTTS-v2.
- TTS singola voce o multi-voce a blocchi, con output MP3 unico e timeline JSON dei blocchi.
- Gestione profili vocali locali, dataset per voice modeling, setup e training XTTS-v2.
- Generazione locale di testi guidati e sicuri per dataset vocali multilingua, con verifica Whisper in background.
- Speech to text offline con WhisperX e Whisper `large-v3`.
- Transcript Markdown, sottotitoli `.srt` automatici e sottotitoli da transcript fornito.
- Embed o burn-in di sottotitoli su video.
- Audio Cleanup manuale con taglio, silenziamento e fade su range selezionati.
- Video Cleanup con filmstrip manuale, detect opzionale dei frame neri e coda di modifiche Freeze/Remove.

## Pacchetto distribuito

La cartella da distribuire e avviare e':

```powershell
dist\VoiceBridge
```

Avvio:

```powershell
dist\VoiceBridge\VoiceBridge.exe
```

Distribuire sempre tutta la cartella `VoiceBridge`, non solo l'eseguibile.

Il bundle include runtime e strumenti necessari, ma il build standard non copia `models` dentro `dist\VoiceBridge` per evitare duplicazioni da molti GB.
I modelli vengono risolti in questo ordine:

1. `dist\VoiceBridge\models`, se esiste e contiene modelli validi.
2. `models` nella root del progetto sorgente, quando si esegue il dist creato dentro al progetto.
3. Download dall'app, se nessuna cache valida viene trovata.

Il bundle puo' includere:

- runtime Python ML condiviso in `python-ml`
- modelli in `models`
- Whisper `large-v3`
- allineamento WhisperX per sottotitoli
- Coqui XTTS-v2 e asset training opzionali
- ffmpeg tramite `imageio-ffmpeg`

La cartella `models` puo' essere distribuita manualmente oppure lasciata assente. In quel caso l'app mostra i pulsanti di download per i prerequisiti mancanti, come Whisper `large-v3`, XTTS-v2 e asset training XTTS.

## Requisiti utente

Per l'uso normale del pacchetto onefolder non serve installare Python.

- Edge TTS richiede connessione internet.
- Local TTS, Transcription, Subtitles, Audio Cleanup e Video Cleanup funzionano offline dopo aver incluso runtime, modelli e ffmpeg.
- Microsoft Word serve solo per leggere vecchi file `.doc`.
- Tesseract OCR serve solo per OCR su PDF scansionati.

## Ambiente sviluppo

L'app principale usa la venv `.venv`.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

OCR opzionale:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

STT, Local TTS e Voice Modeling possono usare una venv ML condivisa Python 3.13:

```powershell
py -3.13 -m venv .venv-ml
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-stt.txt
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-local-tts.txt
```

Preparazione modelli STT:

```powershell
.\.venv-ml\Scripts\python.exe .\prepare_stt_models.py
```

## Struttura codice

- `voicebridge_qt.py`: entrypoint Qt/PySide6 usato anche da PyInstaller.
- `voicebridge/main_window.py`: finestra principale, stato applicativo, settings e wiring dei workflow.
- `voicebridge/pages/`: builder delle pagine e workflow UI per TTS, STT, sottotitoli, Local Voices e cleanup.
- `voicebridge/ui/`: widget, helper UI e stylesheet Qt.
- `voicebridge/constants.py`: label, opzioni e costanti condivise.
- `voicebridge/app_paths.py`: percorsi runtime, bundle, modelli e risorse.
- `voicebridge/audio_recorder.py`: registrazione microfono via `sounddevice`.
- `voicebridge/tts_engine.py`: generazione Edge TTS, suffissi MP3 e cancellazione TTS.
- `voicebridge/media_tools.py`: ffmpeg, merge MP3, sottotitoli e cleanup audio/video.
- `voicebridge/stt_preflight.py`: controlli bundle STT, modelli e ffmpeg.
- `voicebridge/readers.py`: lettura documenti, PDF, OCR opzionale e rilevamento lingua.
- `local_tts_worker.py`: worker Coqui XTTS eseguito dal runtime ML.
- `stt_worker.py`: worker WhisperX eseguito dal runtime ML.
- `voice_modeling_worker.py`: worker per preparazione e training XTTS-v2.
- `prepare_stt_models.py`: script di preparazione/download dei modelli STT.

## Build

Build veloce app/exe, preservando runtime ML e modelli gia' presenti in `dist`:

```powershell
.\build_app.ps1
```

Sincronizzare solo runtime ML:

```powershell
.\sync_stt_bundle.ps1 -RuntimeOnly
```

Sincronizzare manualmente anche i modelli nel dist, solo se si vuole creare un bundle completamente offline:

```powershell
.\sync_stt_bundle.ps1 -ModelsOnly
```

Build completo standard, senza copia dei modelli:

```powershell
.\build_exe.ps1
```

Build completo pulito:

```powershell
.\build_exe.ps1 -Clean
```

Il README, `Manual.md`, la licenza e `THIRD_PARTY_LICENSES` vengono copiati nella cartella `dist\VoiceBridge` durante la build.

## Licenza

Il codice di VoiceBridge e' distribuito con licenza MPL-2.0. Vedere [LICENSE](LICENSE).

Le librerie, i runtime e i modelli di terze parti inclusi o usati dall'app mantengono le rispettive licenze. Vedere [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES).

Nota importante: XTTS-v2 usa la Coqui Public Model License, che limita modello e output a uso non commerciale.
