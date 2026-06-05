# VoiceBridge - Manuale utente

Versione testuale della guida operativa. Per lettura e stampa usare preferibilmente `Manual.html`.

## Scopo dell'app

VoiceBridge serve a trasformare documenti in audio, trascrivere audio/video, creare sottotitoli e correggere piccoli difetti su audio e video. L'interfaccia è organizzata per workflow: scegli una sezione dalla sidebar, carichi i file necessari, controlli le opzioni principali e avvii il job.

## Prima di iniziare

- Edge TTS richiede internet.
- Local TTS funziona offline dopo aver scaricato o incluso il modello XTTS-v2.
- Transcription funziona offline dopo aver scaricato o incluso Whisper large-v3 e i modelli di allineamento necessari.
- Audio Cleanup e Video Cleanup usano ffmpeg incluso nel bundle completo.
- Video Cleanup usa anche OpenCV per il rilevamento dei frame sospetti.
- Microsoft Word serve solo per vecchi file `.doc`.
- Tesseract OCR serve solo per PDF scansionati o basati su immagini.
- La risoluzione minima pratica è Full HD, 1920x1080.

## Home e sidebar

La Home mostra lo stato operativo dell'app: disponibilità Edge TTS, runtime locale, modelli STT, Local TTS, DVAE e strumenti video. Se un requisito manca, la sezione interessata mostra il pulsante o il messaggio per risolvere.

La sidebar permette di passare tra:

- Text to Speech
- Local Voices
- Transcription
- Subtitles
- Audio Cleanup
- Video Cleanup

La lingua dell'interfaccia si seleziona dalla sidebar. Le preferenze vengono salvate automaticamente; i campi file e output partono vuoti a ogni avvio per evitare di riusare file sbagliati.

## Text to Speech

Usa Text to Speech per creare un MP3 da un documento.

1. Apri `Text to Speech`.
2. Seleziona un file `.txt`, `.docx`, `.doc` o `.pdf`.
3. Scegli engine, voce, lingua e velocità.
4. Scegli il percorso di salvataggio dell'MP3.
5. Premi `Generate MP3`.
6. A fine job usa `Open output`, `Open folder` oppure `Open in Audio Cleanup`.

### Edge TTS

Edge TTS usa le voci Microsoft online. Se internet non è disponibile, l'app disabilita Edge TTS, passa temporaneamente a Local TTS se possibile e ritenta il controllo della lista voci in background.

### Local TTS

Local TTS usa XTTS-v2 nel runtime locale. Prima dell'uso scarica il modello con `Download XTTS-v2`, poi scegli un profilo vocale locale, preset e device.

Preset consigliati:

- `Stable`: più conservativo, utile per test lunghi.
- `Balanced`: compromesso consigliato.
- `Natural`: più espressivo, può essere meno stabile.

Se CUDA fallisce, l'app può proporre di ritentare lo stesso job su CPU.

### Multi-voice blocks

La modalità multi-voce divide il testo in blocchi e permette di assegnare voce e velocità diverse a ogni blocco. L'output resta un unico MP3 finale. Quando disponibile, VoiceBridge salva anche una timeline JSON accanto all'MP3 per indicare quali blocchi sono stati generati.

## Local Voices

Local Voices contiene quattro tab: `Profiles`, `Datasets`, `Setup` e `Training`.

### Profiles

Usa `Profiles` per creare voci locali.

1. Crea un profilo `Reference clone` se hai già un audio reference autorizzato.
2. Crea un profilo `Modeling dataset` se vuoi raccogliere clip per un futuro training.
3. Per registrare un reference audio, usa `Record`: l'app guida una registrazione breve, la pulisce e permette di ascoltare, ritentare o salvare.

Il tipo profilo si sceglie alla creazione e resta bloccato. Se elimini un profilo con lavoro di modeling collegato, l'app chiede conferma distruttiva prima di eliminare anche dataset e asset identificabili.

### Datasets

Usa `Datasets` per raccogliere clip audio/testo pronte per voice modeling.

1. Crea prima un profilo `Modeling dataset`.
2. Apri `Local Voices > Datasets`.
3. Usa `Generate guided text` per creare un prompt locale adatto alla lingua del dataset.
4. Usa `Record from text` per registrare la clip guidata.
5. Ascolta il risultato, poi scegli se mantenere o ritentare.
6. Le clip guidate vengono verificate con Whisper in background.
7. Correggi eventuali transcript e usa `Verify text` se serve rilanciare il controllo.
8. Usa `Exclude export` per tenere una clip nel dataset ma non esportarla.

Stati importanti:

- `Ready`: clip con audio e transcript utilizzabile.
- `Checking text`: verifica testo in corso.
- `Match OK`: audio e testo coerenti.
- `Needs review`: il testo va controllato.
- `Check error`: verifica non completata.

`Export dataset` è disponibile solo quando il dataset raggiunge la readiness minima. L'export copia solo clip pronte e non modifica il dataset di lavoro.

### Setup

Usa `Setup` per preparare un job di training XTTS-v2.

1. Esporta prima un dataset da `Datasets`.
2. Scegli l'export nel dropdown.
3. Imposta cartella output, device, epoch e batch size.
4. Se riprendi un training, indica il checkpoint.
5. Se mancano `dvae.pth` o `mel_stats.pth`, usa `Download training assets`.
6. Usa `Refresh preflight`.
7. Se tutto è pronto, usa `Save training config`.

Il download degli asset training può essere annullato con `Cancel download`.

### Training

Usa `Training` per eseguire job salvati.

1. Seleziona un job configurato.
2. Usa `Prepare` per creare metadata e cartelle Coqui.
3. Usa `Dry run` per verificare il job senza addestrare.
4. Usa `Start training` per avviare il training.
5. Usa `Cancel` per terminare il processo esterno.
6. Usa `Open job folder` per controllare log, config e output.

Quando un training produce un `training_result.json` completo, la voce addestrata compare tra le voci Local TTS.

## Transcription

Usa Transcription per creare transcript o sottotitoli da audio/video.

1. Apri `Transcription`.
2. Se compare `Download Whisper large-v3`, scarica prima il modello.
3. Seleziona audio o video.
4. Scegli modalità:
   - `Transcript Markdown (.md)`
   - `Auto subtitles (.srt)`
   - `Subtitles from provided text (.srt)`
5. Scegli lingua e device.
6. Avvia il job.

La modalità Markdown non richiede modelli di allineamento. Le modalità `.srt` richiedono il modello di allineamento della lingua parlata; se manca, l'app chiede se scaricarlo.

## Subtitles

Usa Subtitles per aggiungere un file `.srt` a un video.

1. Seleziona video sorgente.
2. Seleziona file `.srt`.
3. Scegli output.
4. Scegli `Embed SRT track` per aggiungere una traccia sottotitoli selezionabile.
5. Scegli `Burn in SRT` per imprimere i sottotitoli nel video.
6. Nel burn-in regola posizione, dimensione, outline, ombra, colori e qualità.

Il burn-in ricodifica il video. Le modalità CRF più basse aumentano qualità e dimensione file.

## Audio Cleanup

Audio Cleanup serve a correggere piccoli artefatti audio senza rigenerare tutto.

1. Seleziona un file `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac` o `.ogg`.
2. Usa waveform, zoom o campi `Start` / `End` per selezionare un range.
3. Se esiste una timeline TTS, usa `TTS blocks` per agganciarti al blocco generato.
4. Premi `Cut`, `Silence` o `Fade` per mettere la modifica in coda.
5. Ripeti per più correzioni.
6. Controlla `Applied changes`.
7. Premi `Clean audio`.

Le modifiche non possono sovrapporsi. Gli stage intermedi usano formato lossless; l'audio viene codificato nel formato finale solo all'ultimo passaggio. Se esiste una timeline TTS, il file pulito riceve una timeline aggiornata.

## Video Cleanup

Video Cleanup serve a individuare e correggere singoli frame problematici.

1. Seleziona il video.
2. Scegli output e qualità.
3. Usa `Frame review` per caricare la filmstrip.
4. Usa le frecce vicino allo slider per muoverti di un frame alla volta.
5. Usa `Detect black frames` per trovare frame neri isolati.
6. Usa `Detect frame glitches` per trovare frame sospetti non neri.
7. Fai doppio click su un risultato per saltare al frame.
8. Marca manualmente i frame da correggere quando serve.
9. Applica `Freeze previous frame` o `Remove selected frames`.
10. Controlla `Applied changes`.
11. Premi `Clean video`.

`Detect black frames` auto-marca solo frame neri isolati considerati riparabili. I frame sospetti non neri sono solo segnalati e vanno verificati manualmente.

`Freeze previous frame` mantiene la durata originale. `Remove selected frames` accorcia leggermente video e audio rimuovendo i frame marcati.

## Messaggi e stati comuni

- `Ready`: la sezione è pronta.
- `Downloading`: download in corso.
- `Checking`: controllo in corso.
- `Cancelling`: annullamento richiesto.
- `Cancelled`: job annullato.
- `Error`: controlla dettagli, input, output, modelli o spazio disco.
- `CUDA failed`: se proposto, puoi ritentare lo stesso job su CPU.

## Risoluzione problemi rapida

- Edge TTS non disponibile: controlla internet oppure usa Local TTS.
- Local TTS non disponibile: scarica XTTS-v2 e verifica il profilo vocale.
- Transcription non pronta: scarica Whisper large-v3.
- SRT non generato: verifica lingua e modello di allineamento.
- Audio/video cleanup fallisce: controlla output, spazio disco e che il file non sia aperto da un altro programma.
- CUDA non disponibile: usa `Auto` o `CPU`.
- PDF vuoto o scansionato: installa Tesseract OCR e usa OCR quando richiesto.

## Licenze operative

XTTS-v2 usa la Coqui Public Model License e limita modello e output a uso non commerciale. Per licenze complete di librerie, runtime e modelli vedere i file di licenza inclusi nel pacchetto.
