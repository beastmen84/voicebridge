# VoiceBridge

Desktop app Windows per convertire documenti in audio MP3, creare transcript/sottotitoli da file audio o video e gestire piccoli interventi audio/video.

## Funzioni

- Text to Speech con voci Microsoft Edge TTS, richiede connessione internet.
- Local TTS opzionale con profili vocali autorizzati e Coqui XTTS nel runtime ML.
- Generazione TTS a voce singola oppure multi-voce per blocchi di testo, con un solo MP3 finale.
- Ricerca voci, voci preferite e ordinamento delle voci consigliate per lingua rilevata.
- Pulsanti TTS per annullare la generazione, aprire l'MP3 generato o aprire la cartella di output.
- Lettura file `.txt`, `.docx`, `.doc`, `.pdf`.
- OCR opzionale per PDF scansionati o basati su immagini.
- Speech to text offline da audio/video con WhisperX e modelli inclusi.
- Creazione transcript `.md`.
- Creazione sottotitoli `.srt` automatici.
- Creazione `.srt` da transcript fornito, con allineamento al video/audio.
- Aggiunta sottotitoli `.srt` al video come traccia selezionabile oppure impressi nel video.
- Cleanup manuale di file audio con taglio, silenziamento o fade di un intervallo selezionato.
- Rilevamento di frame neri isolati nei video, con riparazione conservativa o rimozione dei frame selezionati.
- Transcript fornito per allineamento da `.txt`, `.md`, `.docx` o `.doc`.

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

Il pacchetto ML offline puo' includere:

- runtime Python ML condiviso in `python-ml`
- Whisper `large-v3`
- allineamento inglese
- allineamento italiano
- Silero VAD
- ffmpeg tramite `imageio-ffmpeg`

La cartella `models` puo' essere distribuita gia' pronta oppure lasciata assente. Se Whisper `large-v3`
non e' presente, la pagina `Transcription` mostra `Download Whisper large-v3` e scarica il modello STT,
Silero VAD e i dati NLTK necessari. I modelli di allineamento per SRT restano scaricabili su richiesta
quando si seleziona o si rileva una lingua non disponibile offline.

Il runtime ML puo' essere CPU-only o CUDA. Nell'app le sezioni STT e Local TTS espongono `Auto`, `CPU` e `CUDA`;
`CUDA` viene abilitato solo quando il precheck rileva un runtime PyTorch compatibile e una GPU NVIDIA disponibile.
La sidebar mostra anche lo stato `LOCAL` per runtime Local TTS e modello XTTS-v2.
Per le modalita' SRT, se viene rilevata o selezionata una lingua con modello di allineamento non incluso, l'app chiede conferma prima di scaricarlo. Dopo il download, quel modello resta disponibile offline sul computer.

## Requisiti utente

Per l'uso normale del pacchetto onefolder non serve installare Python.

Connessione:

- `Text to Speech` richiede internet solo usando Microsoft Edge TTS.
- `Local TTS`, `Transcription`, `Subtitles` e `Video Cleanup` funzionano offline dopo aver incluso runtime, modelli e ffmpeg nella cartella distribuita.

Prerequisiti opzionali:

- Microsoft Word: richiesto per leggere vecchi file `.doc`.
- Tesseract OCR: richiesto solo per OCR su PDF scansionati. Installer Windows consigliato: <https://github.com/UB-Mannheim/tesseract/wiki>

I file `.docx`, `.txt` e PDF testuali non richiedono Word.

## Workflow

I campi file/output delle sezioni operative partono vuoti a ogni avvio. Restano salvate solo preferenze come engine,
modalita', lingua, device, qualita' e preset.

### Text to Speech

1. Aprire `Text to Speech`.
2. Scegliere un file supportato.
3. Selezionare voce, preferiti e velocita'.
4. In alternativa, scegliere `Multi-voice blocks`, dividere il documento in blocchi e assegnare voce/velocita' Edge oppure profili vocali Local TTS ai singoli blocchi.
5. Salvare come `.mp3`.
6. Premere `Generate MP3`; a fine generazione usare `Open output`, `Open folder` o `Open in Audio Cleanup`.

Questo workflow richiede connessione internet quando l'engine selezionato e' `Edge TTS`.
Il pulsante `Cancel` annulla la generazione TTS in corso. L'app scrive su file temporanei e sostituisce l'MP3 finale solo a generazione completata, quindi un annullamento non lascia output finali parziali.
La modalita' multi-voce normalizza il testo, divide internamente i blocchi lunghi mantenendo la stessa voce/velocita'
e unisce le parti temporanee in un unico MP3 finale; per l'unione usa `ffmpeg` dal bundle completo.
Quando l'output viene generato a blocchi, l'app salva accanto all'MP3 anche `nome.voicebridge-tts.json` con la
timeline dei blocchi effettivamente generati. Local TTS crea questa mappa anche in modalita' singola quando XTTS
divide internamente il testo in chunk.
Le voci `Multilingual` vengono indicate come `auto language`; per testi italiani tecnici conviene preferire una voce nativa `it-IT`.

### Voice Profiles e Local TTS

1. Aprire `Voice Profiles`.
2. Creare un profilo `Reference clone` con un file audio autorizzato e consenso confermato.
3. In alternativa, registrare direttamente dal microfono con `Record`; l'app apre una registrazione guidata da 30 secondi con countdown, testo di lettura nella lingua scelta, ascolto del WAV pulito e scelta finale `Mantieni`, `Ritenta` o `Annulla`.
4. Aprire `Text to Speech`.
5. Selezionare engine `Local TTS`.
6. Se necessario, usare `Download XTTS-v2` per scaricare il modello locale una sola volta.
7. Scegliere profilo vocale, preset XTTS (`Stable`, `Balanced` o `Natural`) e device `Auto`, `CPU` o `CUDA`.
8. Generare l'MP3.

Local TTS usa `coqui-tts` nel runtime ML e il modello XTTS-v2. Il primo uso puo' scaricare il modello in `models\coqui`;
dopo il download il modello resta disponibile localmente.
Con almeno due profili vocali pronti, `Multi-voice blocks` e' disponibile anche per Local TTS: ogni blocco usa il
profilo assegnato e, se XTTS divide internamente un blocco lungo, mantiene lo stesso profilo su tutte le parti.
Per ridurre artefatti su testi lunghi, Local TTS normalizza liste, spazi, file extension e punteggiatura, divide il testo in chunk brevi
e concatena l'audio WAV prima della conversione MP3 finale. Il preset `Stable` privilegia la stabilita', `Balanced` e' il compromesso
consigliato per i test, mentre `Natural` lascia piu' espressivita' al modello.
Il modello XTTS-v2 usa la Coqui Public Model License, che limita modello e output a uso non commerciale. Vedere `THIRD_PARTY_LICENSES`.
Le registrazioni create dall'app sono file utente nella cartella `voice_profiles` e non vengono tracciate da git.

### Transcription

1. Aprire `Transcription`.
2. Se compare `Download Whisper large-v3`, scaricare prima il modello STT richiesto.
3. Scegliere un file audio o video.
4. Scegliere la modalita':
   - `Transcript Markdown (.md)`
   - `Auto subtitles (.srt)`
   - `Subtitles from provided text (.srt)`
5. Scegliere lingua. `Auto detect` va bene nella maggior parte dei casi; nel menu le lingue gia' disponibili sono marcate `offline ready`, mentre le altre sono marcate `download for SRT`.
6. Scegliere device `Auto`, `CPU` o `CUDA`.
7. Generare il file.
8. Per aggiungere un `.srt` a un video, usare la sezione `Subtitles`.

La modalita' `Transcript Markdown (.md)` non richiede modelli di allineamento: Whisper `large-v3` puo' trascrivere anche lingue non incluse nel pacchetto alignment.
Le due modalita' `.srt` richiedono invece il modello di allineamento della lingua parlata. Se il modello non e' disponibile, l'app mostra un prompt e lo scarica solo se l'utente conferma.
Nel modo `Subtitles from provided text (.srt)`, il transcript fornito puo' essere `.txt`, `.md`, `.docx` o `.doc`; i vecchi `.doc` richiedono Microsoft Word installato.
`Subtitles` usa `ffmpeg` incluso nel bundle completo ed e' indipendente dall'ultimo job STT: si puo' usare anche con un `.srt` creato da un audio estratto dal video.
`Embed SRT track` crea un file `_subtitled`, mentre `Burn in SRT` crea un file `_burned`.
Nel burn-in si puo' scegliere la qualita' di ricodifica:

- `Auto (recommended)`: sceglie CRF 20 per la maggior parte dei 1080p, CRF 18 per 4K o 1080p ad alto bitrate.
- `Standard (CRF 20)`: qualita' alta per 1080p, file normalmente piu' piccoli.
- `High quality (CRF 18)`: piu' vicino alla sorgente, file piu' grandi.
- `Maximum quality (CRF 16)`: qualita' molto alta, file molto piu' grandi.
- `Original bitrate`: ricodifica puntando al bitrate video sorgente; non e' lossless.

CRF significa qualita' costante: numeri piu' bassi danno piu' qualita' e file piu' grandi.

### Audio Cleanup

Audio Cleanup serve soprattutto a correggere piccoli artefatti o allucinazioni generate dal TTS AI senza rifare tutto
l'output. Non e' pensato come editor audio completo: se si taglia una porzione, la timeline puo' riallineare i tempi,
ma il testo associato ai blocchi resta una guida operativa, non una trascrizione riscritta.

1. Aprire `Audio Cleanup`.
2. Scegliere un file audio `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac` o `.ogg`.
3. Se esiste un sidecar `nome.voicebridge-tts.json`, usare la scheda `TTS blocks` sotto la waveform: click su un blocco per agganciare il range e leggere il testo associato.
4. Usare la waveform, lo zoom o i campi `Start` / `End` per rifinire l'intervallo con passo da 10 ms e ascoltare la selezione.
5. Scegliere `Cut range`, `Replace with silence` o `Fade range to silence`.
6. Salvare un nuovo file audio e premere `Clean audio`.

Questo workflow e' manuale e non dipende da Local TTS: puo' correggere anche audio creati altrove. Durante l'anteprima della sorgente, la waveform mostra il punto di riproduzione corrente. Usa `ffmpeg` dal bundle completo.

### Video Cleanup

1. Aprire `Video Cleanup`.
2. Scegliere il video sorgente.
3. Usare `Detect black frames` per analizzare il video senza modificarlo.
4. Controllare i frame marcati come riparabili. Ogni candidato ha un checkbox e un pulsante `Details`.
5. In `Details` si vedono frame precedente, frame problematico e frame successivo.
6. Selezionare solo i frame da correggere, scegliere metodo/qualita' e usare `Clean selected frames`.

Il metodo `Freeze previous frame` e' conservativo: corregge solo frame neri isolati di un singolo frame, sostituendoli con il frame precedente. Il video mantiene la durata originale e l'audio viene copiato quando possibile.
Il metodo `Remove selected frames` elimina i frame selezionati e le micro-porzioni audio corrispondenti. E' utile se si pulisce il video prima di creare o allineare sottotitoli, ma accorcia la timeline.
Le sequenze nere piu' lunghe, incluse parti nere all'inizio o alla fine del video, vengono segnalate e lasciate intatte, per evitare di alterare dissolvenze, fade o parti nere intenzionali.
La qualita' di output puo' essere scelta nella sezione `Output quality`:

- `Auto (recommended)`: usa la stessa logica del burn-in, cioe' CRF 20 per la maggior parte dei 1080p e CRF 18 per 4K o 1080p ad alto bitrate.
- `Standard (CRF 20)`: qualita' alta per 1080p, file normalmente piu' piccoli.
- `High quality (CRF 18)`: piu' vicino alla sorgente, file piu' grandi.
- `Maximum quality (CRF 16)`: qualita' molto alta, file molto piu' grandi.
- `Original bitrate`: punta sempre al bitrate video sorgente; se non e' rilevabile, scegliere una modalita' CRF.

## Ambiente sviluppo

L'app principale usa la venv `.venv`.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

Struttura principale del codice:

- `voicebridge_qt.py`: entrypoint Qt/PySide6 usato anche da PyInstaller.
- `voicebridge/main_window.py`: finestra principale, stato applicativo, settings e wiring dei workflow.
- `voicebridge/pages/`: builder delle pagine e workflow UI separati per TTS, STT, sottotitoli e cleanup video.
- `voicebridge/ui/`: widget, helper UI e stylesheet Qt.
- `voicebridge/constants.py`: label, opzioni e costanti condivise dell'app.
- `voicebridge/app_paths.py`: percorsi runtime, bundle, modelli e risorse.
- `voicebridge/audio_recorder.py`: registrazione microfono via `sounddevice` per i profili vocali.
- `voicebridge/voice_profile_recording_dialog.py`: dialog guidato per registrare, pulire, ascoltare e confermare un reference vocale.
- `voicebridge/voice_profile_scripts.py`: testi di registrazione per le lingue supportate dai profili vocali.
- `voicebridge/tts_engine.py`: generazione Edge TTS, suffissi MP3 e cancellazione TTS.
- `voicebridge/media_tools.py`: ffmpeg, merge MP3 multi-voce, embed/burn-in sottotitoli e cleanup video.
- `voicebridge/stt_preflight.py`: controlli bundle STT, modelli e ffmpeg.
- `voicebridge/readers.py`: lettura documenti, PDF, OCR opzionale e rilevamento lingua.
- `voicebridge/voices.py`: elenco, ricerca, preferiti e ordinamento voci.
- `voicebridge/wav_writer.py`: scrittura WAV PCM, analisi livello, trim silenzio e normalizzazione per registrazioni microfono dei profili vocali.
- `stt_worker.py`: worker offline WhisperX eseguito dal runtime ML e copiato come file esterno nel bundle.
- `local_tts_worker.py`: worker Coqui XTTS eseguito dal runtime ML e copiato come file esterno nel bundle.
- `prepare_stt_models.py`: script di preparazione/download dei modelli STT.

OCR opzionale:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

STT e Local TTS possono usare una venv ML condivisa Python 3.13:

```powershell
py -3.13 -m venv .venv-ml
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-stt.txt
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-local-tts.txt
```

Preparazione modelli STT:

```powershell
.\.venv-ml\Scripts\python.exe .\prepare_stt_models.py
```

## Build

Build veloce app/exe, preservando runtime ML e modelli gia' presenti in `dist`:

```powershell
.\build_app.ps1
```

Sincronizzare solo runtime ML:

```powershell
.\sync_stt_bundle.ps1 -RuntimeOnly
```

Sincronizzare solo modelli:

```powershell
.\sync_stt_bundle.ps1 -ModelsOnly
```

Build completo:

```powershell
.\build_exe.ps1
```

Build completo pulito:

```powershell
.\build_exe.ps1 -Clean
```

## Note

- `requirements-stt.txt` e `requirements-local-tts.txt` non servono al programma a runtime, ma documentano come ricreare il runtime ML.
- Il primo avvio STT puo' essere lento su CPU, soprattutto con video lunghi.
- `Download Whisper large-v3` scarica il modello STT in `models\whisperx` e prepara le cache STT richieste.
- `Download XTTS-v2` scarica un unico modello multilingua in `models\coqui` e richiede circa 1.8-2.3 GB.
- I modelli di allineamento SRT possono essere inclusi nella distribuzione o scaricati su richiesta dalle funzioni SRT.
- La generazione Edge TTS resta online; Local TTS usa il runtime ML locale.
- Il README, la licenza e `THIRD_PARTY_LICENSES` vengono copiati nella cartella `dist\VoiceBridge` durante la build.

## Licenza

Il codice di VoiceBridge e' distribuito con licenza MIT. Vedere `LICENSE`.
Le librerie, i runtime e i modelli di terze parti inclusi o usati dall'app mantengono le rispettive licenze. Vedere `THIRD_PARTY_LICENSES`.
