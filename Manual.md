# VoiceBridge - Manuale operativo

Guida operativa per usare VoiceBridge dal pacchetto Windows distribuito.

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
- Rilevamento di frame neri nei video, review manuale su filmstrip e riparazione/rimozione dei frame marcati.
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

Il build standard non copia `models` dentro `dist\VoiceBridge`, cosi' sul PC di sviluppo non si duplicano molti GB.
Quando viene eseguita dal dist creato dentro al progetto, l'app cerca prima eventuali modelli in
`dist\VoiceBridge\models`, poi riusa la cartella condivisa `models` nella root del progetto. Se Whisper `large-v3`
non e' presente in nessuna cache valida, la pagina `Transcription` mostra `Download Whisper large-v3` e scarica il modello STT,
Silero VAD e i dati NLTK necessari. I modelli di allineamento per SRT restano scaricabili su richiesta
quando si seleziona o si rileva una lingua non disponibile offline.

Il runtime ML puo' essere CPU-only o CUDA. Nell'app le sezioni STT e Local TTS espongono `Auto`, `CPU` e `CUDA`;
`CUDA` viene abilitato solo quando il precheck rileva un runtime PyTorch compatibile e una GPU NVIDIA disponibile.
La sidebar mostra anche lo stato `LOCAL` per runtime Local TTS e modello XTTS-v2, piu' `DVAE` per il checkpoint
`dvae.pth` richiesto dal futuro training XTTS-v2.
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

All'avvio l'app controlla le configurazioni in `%APPDATA%\VoiceBridge`: i vecchi JSON non piu' usati e i file corrotti
vengono spostati in `legacy_backup` invece di essere eliminati. Profili vocali, dataset, modelli e output utente non
vengono toccati da questa pulizia.
I JSON proprietari dell'app includono `schema_version` e `kind`. La versione e' separata per ogni `kind`, cosi' le
future modifiche strutturali possono essere gestite con migrazioni mirate o archiviazione controllata solo per il file
interessato.

L'app esegue controlli preventivi su input, output, spazio disco e modelli locali. I download interrotti o file modello
troppo piccoli vengono trattati come pacchetti incompleti e vanno scaricati di nuovo. Se un job CUDA fallisce nel
runtime, le sezioni STT, Local TTS e Training propongono un retry su CPU quando possibile.

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

### Local Voices, Voice Profiles e Local TTS

Le funzioni locali per la voce sono raccolte in `Local Voices`, con tab `Profiles`, `Datasets`, `Setup` e `Training`.
Il tab `Datasets` si abilita dopo aver creato almeno un profilo `Modeling dataset`; il tab `Setup` si abilita
quando esiste almeno un export dataset valido in `modeling_exports`; il tab `Training` si abilita dopo aver salvato
almeno un `job_config.json`.

1. Aprire `Local Voices > Profiles`.
2. Creare un profilo `Reference clone` con un file audio autorizzato e consenso confermato.
3. In alternativa, registrare direttamente dal microfono con `Record`; l'app apre una registrazione guidata da 30 secondi con countdown, testo di lettura nella lingua scelta, ascolto del WAV pulito e scelta finale `Mantieni`, `Ritenta` o `Annulla`.
4. Per preparare un futuro training, creare invece un profilo `Modeling dataset`: non richiede audio reference nella scheda profilo e crea un dataset collegato in `Local Voices > Datasets`.
5. Aprire `Text to Speech`.
6. Selezionare engine `Local TTS`.
7. Se necessario, usare `Download XTTS-v2` per scaricare il modello locale una sola volta.
8. Scegliere profilo vocale, preset XTTS (`Stable`, `Balanced` o `Natural`) e device `Auto`, `CPU` o `CUDA`.
9. Generare l'MP3.

Local TTS usa `coqui-tts` nel runtime ML e il modello XTTS-v2. Il primo uso puo' scaricare il modello in `models\coqui`;
dopo il download il modello resta disponibile localmente.
Con almeno due profili vocali pronti, `Multi-voice blocks` e' disponibile anche per Local TTS: ogni blocco usa il
profilo assegnato e, se XTTS divide internamente un blocco lungo, mantiene lo stesso profilo su tutte le parti.
Per ridurre artefatti su testi lunghi, Local TTS normalizza liste, spazi, file extension e punteggiatura, divide il testo in chunk brevi
e concatena l'audio WAV prima della conversione MP3 finale. Il preset `Stable` privilegia la stabilita', `Balanced` e' il compromesso
consigliato per i test, mentre `Natural` lascia piu' espressivita' al modello.
Il modello XTTS-v2 usa la Coqui Public Model License, che limita modello e output a uso non commerciale. Vedere `THIRD_PARTY_LICENSES`.
Il tipo profilo si sceglie alla creazione e resta bloccato dopo il salvataggio. Le registrazioni create dall'app sono
file utente nella cartella `voice_profiles` e non vengono tracciate da git: i sample rapidi finiscono in
`voice_profiles\reference_clone\<nome profilo>`, mentre i dataset futuri usano `voice_profiles\modeling_dataset\<nome profilo>`.

### Local Voices > Datasets

`Local Voices > Datasets` prepara coppie audio/testo autorizzate per un futuro voice modeling, ma non esegue ancora training.

1. Creare prima un profilo in `Local Voices > Profiles` con tipo `Modeling dataset`.
2. Aprire `Local Voices > Datasets`: l'app crea o aggiorna il dataset collegato al profilo.
3. Per il flusso consigliato, usare `Generate guided text`: l'app compone un testo locale e sicuro dalla lingua del
   dataset, con frasi prevalidate e varieta' di ritmo, domande, numeri, nomi e punteggiatura. Poi usare
   `Record from text`. Il contatore `Guided prompts: usati / disponibili` mostra quante combinazioni guidate sono gia'
   state consumate nel dataset; con il corpus attuale ogni lingua ha 262.144 combinazioni teoriche disponibili.
4. Per una clip guidata avanzata, caricare o incollare il testo esatto e usare `Record from text`; il testo per una
   singola clip e' limitato a 450 caratteri, la finestra mostra il testo, registra dal microfono per massimo 60 secondi,
   pulisce il WAV e permette `Ascolta`, `Mantieni`, `Ritenta` o `Annulla`.
5. Per una clip libera, usare `Free record`; registra per massimo 60 secondi e la clip viene salvata come `Needs transcript`.
6. Per le clip libere si puo' usare `Open in Transcription` per mandare l'audio alla pagina STT, poi correggere/incollare il testo e salvarlo con `Save transcript`.

I dataset vengono salvati in `voice_profiles\modeling_dataset\<nome profilo>`; ogni clip mantiene WAV pulito in `clips`,
testo sidecar `.txt` in `transcripts` quando disponibile e metadata di qualita'. Solo le clip con testo confermato sono marcate `Ready`.
Le clip create con il generatore mantengono nel JSON la sorgente `generated_prompt:<versione corpus>`; il testo mostrato
rimane il transcript esatto associato alla registrazione. Il generatore non ricicla automaticamente prompt gia' usati:
se il pool e' esaurito, bisogna usare testo custom, caricare uno script o premere `Reset guided history`. Il reset
cancella solo la cronologia dei prompt proposti; i testi gia' salvati nelle clip restano comunque esclusi dai duplicati.
La scheda mostra anche un riepilogo qualita' del dataset: clip pronte, durata utile, clip senza transcript, audio mancanti
e segnali come clip troppo corte/lunghe, volume basso, clipping o SNR stimato basso. L'app separa `Export readiness`
dal livello reale del dataset: `Usable` richiede almeno 5 clip pronte e 60 secondi di audio ed e' pensato soprattutto
per testare la pipeline. Il livello qualitativo viene invece letto dai minuti effettivi validati: test tecnico sotto
5 minuti, base 5-15 minuti, recommended 15-30 minuti, high quality 30-60 minuti e premium oltre 60 minuti.
Il target consigliato per una voce da usare davvero e' 60-120 clip pronte e 30-60 minuti di audio pulito.
`Export dataset` e' disponibile solo da stato `Usable` in poi e crea una copia pronta per training in
`modeling_exports\<nome profilo>-<timestamp>` con `wavs`, `metadata.csv` in formato `wavs/clip.wav|testo` e
`dataset.json` con riepilogo e audit dell'export. L'export include solo clip `Ready` con WAV esistente e non modifica i
file di lavoro.

### Local Voices > Setup

`Local Voices > Setup` prepara il job di training XTTS-v2, ma non avvia ancora il training.

1. Esportare prima un dataset dalla sezione `Local Voices > Datasets`.
2. Aprire `Local Voices > Setup` e scegliere il dataset export dal dropdown popolato da `modeling_exports`.
3. Usare `Refresh` se si e' appena creato un export; `Browse external...` serve solo per dataset validi fuori cartella.
4. Scegliere cartella output in `voice_models`, device `Auto`, `CPU` o `CUDA`, epoch e batch size.
5. Se si sta riprendendo un training precedente, indicare un checkpoint `.pth`, `.pt` o `.ckpt`.
6. Se mancano `dvae.pth` o `mel_stats.pth`, usare `Download training assets`; i file vengono salvati nella cache XTTS-v2 locale.
7. Usare `Refresh preflight` per verificare runtime ML, Torch/CUDA, Coqui, XTTS-v2, asset training, dataset e output.
8. Usare `Save training config` per creare `job_config.json` nella cartella output.

### Local Voices > Training

`Local Voices > Training` elenca i job configurati in `voice_models` e avvia la preparazione, il dry-run e il training
XTTS-v2.

1. Salvare prima un `job_config.json` da `Local Voices > Setup`.
2. Aprire `Local Voices > Training`.
3. Usare `Prepare` per creare i metadata Coqui `metadata_train.csv` e `metadata_eval.csv` in `prepared_dataset`.
4. Usare `Dry run` per verificare runtime, device, modello, `dvae.pth`, `mel_stats.pth` e dataset senza addestrare.
5. Usare `Start training` per avviare il worker XTTS-v2; `Cancel` termina il processo esterno.
6. Usare `Open job folder` per ispezionare config, log, metadata preparati e output.

Il training crea `run\training` con i checkpoint Coqui e, se completato, `inference_model` con `model.pth`,
`config.json` e `vocab.json` preparati per l'uso come voce locale. La cartella `voice_models` contiene
output utente e non viene tracciata da git.

Quando esiste un `training_result.json` completo, la voce addestrata compare automaticamente tra le voci `Local TTS`
insieme ai profili `Reference clone`. Le voci addestrate usano il loro `inference_model`; il download del modello base
XTTS-v2 resta necessario solo per i profili reference clone.

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
La card `Burn-in font` permette di regolare posizione, margine verticale, dimensione, outline, ombra, colori e box di sfondo.
Queste opzioni usano parametri ASS/ffmpeg portabili e non dipendono da font specifici installati sul PC.

### Audio Cleanup

Audio Cleanup serve soprattutto a correggere piccoli artefatti o allucinazioni generate dal TTS AI senza rifare tutto
l'output. Non e' pensato come editor audio completo: se si taglia una porzione, la timeline puo' riallineare i tempi,
ma il testo associato ai blocchi resta una guida operativa, non una trascrizione riscritta.

1. Aprire `Audio Cleanup`.
2. Scegliere un file audio `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac` o `.ogg`.
3. Se esiste un sidecar `nome.voicebridge-tts.json`, usare la scheda `TTS blocks` sotto la waveform: click su un blocco per agganciare il range e leggere il testo associato.
4. Usare la waveform, lo zoom o i campi `Start` / `End` per rifinire l'intervallo con passo da 10 ms; un click singolo sulla waveform azzera la selezione e il pulsante diventa `Play all`.
5. Premere `Cut`, `Silence` o `Fade` nella scheda `Waveform` per mettere in coda la correzione.
6. Ripetere il passaggio per aggiungere piu' correzioni; `Applied changes` mostra le modifiche in coda, le evidenzia sulla waveform e permette di rimuovere una singola voce con la `X`.
7. Salvare un nuovo file audio e premere `Clean audio`.

Se l'audio sorgente ha una timeline TTS, anche il file pulito riceve un nuovo `nome.voicebridge-tts.json`: `Cut range`
applica le modifiche in ordine, riallinea i tempi dei blocchi successivi e marca quelli toccati, mentre `Replace with silence` e `Fade range to silence`
mantengono la durata. L'output pulito viene caricato come nuova sorgente per continuare con eventuali altre correzioni.

Questo workflow e' manuale e non dipende da Local TTS: puo' correggere anche audio creati altrove. Durante l'anteprima della sorgente, la waveform mostra il punto di riproduzione corrente. Usa `ffmpeg` dal bundle completo.

### Video Cleanup

1. Aprire `Video Cleanup`.
2. Scegliere il video sorgente.
3. Scegliere il percorso `Save cleaned video as` e la qualita' in `Output quality`.
4. Usare `Frame review` per controllare la filmstrip. La selezione manuale e' sempre disponibile.
5. Se serve, usare `Detect black frames`: analizza il video senza modificarlo e auto-marca solo i glitch isolati.
6. Selezionare uno o piu' frame e usare `Mark selected`; usare `Unmark selected` o `Clear marks` per correggere la selezione.
7. Applicare `Freeze previous frame` o `Remove selected frames`: la modifica entra in `Applied changes` e puo' essere rimossa con la `X`.
8. Usare `Clean video` per applicare in ordine tutte le modifiche in coda.

Il metodo `Freeze previous frame` e' conservativo: corregge i frame marcati sostituendoli con il frame precedente. Il video mantiene la durata originale e l'audio viene copiato quando possibile.
Il metodo `Remove selected frames` elimina i frame marcati e le micro-porzioni audio corrispondenti. Le modifiche successive vengono applicate tenendo conto dei frame gia' rimossi. E' utile se si pulisce il video prima di creare o allineare sottotitoli, ma accorcia la timeline.
Le sequenze nere piu' lunghe, incluse parti nere all'inizio o alla fine del video, vengono segnalate e lasciate intatte, per evitare di alterare dissolvenze, fade o parti nere intenzionali.
La qualita' di output puo' essere scelta nella sezione `Output quality`:

- `Auto (recommended)`: usa la stessa logica del burn-in, cioe' CRF 20 per la maggior parte dei 1080p e CRF 18 per 4K o 1080p ad alto bitrate.
- `Standard (CRF 20)`: qualita' alta per 1080p, file normalmente piu' piccoli.
- `High quality (CRF 18)`: piu' vicino alla sorgente, file piu' grandi.
- `Maximum quality (CRF 16)`: qualita' molto alta, file molto piu' grandi.
- `Original bitrate`: punta sempre al bitrate video sorgente; se non e' rilevabile, scegliere una modalita' CRF.

## Note operative

- `requirements-stt.txt` e `requirements-local-tts.txt` non servono al programma a runtime, ma documentano come ricreare il runtime ML.
- Il primo avvio STT puo' essere lento su CPU, soprattutto con video lunghi.
- `Download Whisper large-v3` scarica il modello STT in `models\whisperx` e prepara le cache STT richieste.
- `Download XTTS-v2` scarica un unico modello multilingua in `models\coqui` e richiede circa 1.8-2.3 GB.
- `dvae.pth` e `mel_stats.pth`, usati per voice modeling/fine-tuning XTTS-v2, sono attesi in
  `models\coqui\tts\tts_models--multilingual--multi-dataset--xtts_v2`.
- I modelli di allineamento SRT possono essere inclusi nella distribuzione o scaricati su richiesta dalle funzioni SRT.
- La generazione Edge TTS resta online; Local TTS usa il runtime ML locale.
- Il README, `Manual.md`, la licenza e `THIRD_PARTY_LICENSES` vengono copiati nella cartella `dist\VoiceBridge` durante la build.

## Licenza

Il codice di VoiceBridge e' distribuito con licenza MPL-2.0. Vedere `LICENSE`.
Le librerie, i runtime e i modelli di terze parti inclusi o usati dall'app mantengono le rispettive licenze. Vedere `THIRD_PARTY_LICENSES`.
