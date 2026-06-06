from __future__ import annotations

from typing import Any

UI_LANGUAGE_EN = "en"
UI_LANGUAGE_IT = "it"

UI_LANGUAGES = {
    UI_LANGUAGE_EN: "English",
    UI_LANGUAGE_IT: "Italiano",
}

DEFAULT_UI_LANGUAGE = UI_LANGUAGE_EN

TRANSLATIONS: dict[str, dict[str, str]] = {
    UI_LANGUAGE_EN: {
        "app.subtitle": "Voice and subtitle tools",
        "sidebar.main_tools": "MAIN TOOLS",
        "sidebar.advanced_tools": "ADVANCED TOOLS",
        "sidebar.support_tools": "SUPPORT TOOLS",
        "sidebar.ui_language": "UI LANGUAGE",
        "sidebar.ui_language.tooltip": "Select the application interface language.",
        "sidebar.status": "STATUS",
        "sidebar.manual": "Help",
        "sidebar.manual.tooltip": "Open the VoiceBridge user manual.",
        "manual.missing.title": "Manual missing",
        "manual.missing.message": "Could not find the selected VoiceBridge HTML manual next to the application.",
        "nav.dashboard": "Dashboard",
        "nav.tts": "Text to Speech",
        "nav.local_voices": "Local Voices",
        "nav.transcription": "Transcription",
        "nav.subtitles": "Subtitles",
        "nav.audio_cleanup": "Audio Cleanup",
        "nav.video_cleanup": "Video Cleanup",
        "local_voices.title": "Local Voices",
        "local_voices.subtitle": (
            "Manage local voice profiles, collect modeling datasets and configure XTTS-v2 training."
        ),
        "local_voices.tab.profiles": "Profiles",
        "local_voices.tab.datasets": "Dataset",
        "local_voices.tab.setup": "Setup",
        "local_voices.tab.training": "Training",
        "local_voices.tooltip.datasets_disabled": "Create a Modeling dataset profile first.",
        "local_voices.tooltip.datasets_profile_only": "Open Dataset from a saved modeling profile.",
        "local_voices.tooltip.setup_disabled": "Export a usable dataset first.",
        "local_voices.tooltip.training_disabled": "Save a training config from Setup first.",
        "voice_profiles.title": "Voice Profiles",
        "voice_profiles.subtitle": "Manage local reference voices for future Local TTS generation.",
        "voice_profiles.card.profiles": "Profiles",
        "voice_profiles.card.editor": "Profile editor",
        "voice_profiles.empty": "No voice profiles yet.",
        "voice_profiles.button.new": "New",
        "voice_profiles.button.delete": "Delete",
        "voice_profiles.button.record": "Record",
        "voice_profiles.button.play": "Play",
        "voice_profiles.button.save": "Save profile",
        "voice_profiles.button.open_dataset": "Open Dataset",
        "voice_profiles.button.open_audio": "Open audio",
        "voice_profiles.button.open_folder": "Open folder",
        "voice_profiles.label.name": "Name",
        "voice_profiles.label.type": "Type",
        "voice_profiles.label.language": "Language",
        "voice_profiles.label.microphone": "Microphone",
        "voice_profiles.file.reference_audio": "Reference audio",
        "voice_profiles.notes.placeholder": "Notes",
        "voice_profiles.status.new": "New profile.",
        "voice_profiles.status.record_prompt": "Record a guided 30s voice sample for the selected profile.",
        "voice_profiles.status.modeling_prompt": "Use Local Voices > Datasets to collect clips for this voice.",
        "voice_profiles.status.recording_cancelled": "Recording cancelled.",
        "voice_profiles.status.no_microphone": "No microphone input was detected by sounddevice.",
        "voice_profiles.status.delete_cancelled": "Delete cancelled.",
        "voice_profiles.status.saved": "Saved: {name} | {status}",
        "voice_profiles.error.title": "Voice Profiles",
        "voice_profiles.error.enter_name_before_recording": "Enter a profile name before recording.",
        "voice_profiles.error.no_microphone": "No microphone input was detected.",
        "voice_profiles.dialog.select_reference_audio": "Select reference audio",
        "voice_profiles.dialog.delete_title": "Delete voice profile and modeling work?",
        "voice_profiles.type.reference": "Reference clone",
        "voice_profiles.type.modeling": "Modeling dataset",
        "voice_profiles.status.modeling_dataset": "Modeling dataset",
        "voice_profiles.status.missing_reference_audio": "Missing reference audio",
        "voice_profiles.status.missing_audio_file": "Missing audio file",
        "voice_profiles.status.incomplete_audio_file": "Incomplete audio file",
        "voice_profiles.status.unsupported_audio_format": "Unsupported audio format",
        "voice_profiles.status.ready": "Ready",
    },
    UI_LANGUAGE_IT: {
        "app.subtitle": "Strumenti voce e sottotitoli",
        "sidebar.main_tools": "STRUMENTI PRINCIPALI",
        "sidebar.advanced_tools": "STRUMENTI AVANZATI",
        "sidebar.support_tools": "STRUMENTI DI SUPPORTO",
        "sidebar.ui_language": "LINGUA UI",
        "sidebar.ui_language.tooltip": "Seleziona la lingua dell'interfaccia.",
        "sidebar.status": "STATO",
        "sidebar.manual": "Aiuto",
        "sidebar.manual.tooltip": "Apri il manuale utente di VoiceBridge.",
        "manual.missing.title": "Manuale mancante",
        "manual.missing.message": "Impossibile trovare il manuale HTML selezionato accanto all'applicazione.",
        "nav.dashboard": "Dashboard",
        "nav.tts": "Text to Speech",
        "nav.local_voices": "Voci locali",
        "nav.transcription": "Trascrizione",
        "nav.subtitles": "Sottotitoli",
        "nav.audio_cleanup": "Pulizia audio",
        "nav.video_cleanup": "Pulizia video",
        "local_voices.title": "Voci locali",
        "local_voices.subtitle": (
            "Gestisci profili vocali locali, dataset di modeling e configurazione training XTTS-v2."
        ),
        "local_voices.tab.profiles": "Profili",
        "local_voices.tab.datasets": "Dataset",
        "local_voices.tab.setup": "Setup",
        "local_voices.tab.training": "Training",
        "local_voices.tooltip.datasets_disabled": "Crea prima un profilo Modeling dataset.",
        "local_voices.tooltip.datasets_profile_only": "Apri Dataset da un profilo modeling salvato.",
        "local_voices.tooltip.setup_disabled": "Esporta prima un dataset usabile.",
        "local_voices.tooltip.training_disabled": "Salva prima una configurazione training da Setup.",
        "voice_profiles.title": "Profili vocali",
        "voice_profiles.subtitle": "Gestisci voci di riferimento locali per la futura generazione Local TTS.",
        "voice_profiles.card.profiles": "Profili",
        "voice_profiles.card.editor": "Editor profilo",
        "voice_profiles.empty": "Nessun profilo vocale.",
        "voice_profiles.button.new": "Nuovo",
        "voice_profiles.button.delete": "Elimina",
        "voice_profiles.button.record": "Registra",
        "voice_profiles.button.play": "Play",
        "voice_profiles.button.save": "Salva profilo",
        "voice_profiles.button.open_dataset": "Apri Dataset",
        "voice_profiles.button.open_audio": "Apri audio",
        "voice_profiles.button.open_folder": "Apri cartella",
        "voice_profiles.label.name": "Nome",
        "voice_profiles.label.type": "Tipo",
        "voice_profiles.label.language": "Lingua",
        "voice_profiles.label.microphone": "Microfono",
        "voice_profiles.file.reference_audio": "Audio di riferimento",
        "voice_profiles.notes.placeholder": "Note",
        "voice_profiles.status.new": "Nuovo profilo.",
        "voice_profiles.status.record_prompt": "Registra un sample guidato da 30s per il profilo selezionato.",
        "voice_profiles.status.modeling_prompt": "Usa Local Voices > Datasets per raccogliere clip per questa voce.",
        "voice_profiles.status.recording_cancelled": "Registrazione annullata.",
        "voice_profiles.status.no_microphone": "Nessun input microfono rilevato da sounddevice.",
        "voice_profiles.status.delete_cancelled": "Eliminazione annullata.",
        "voice_profiles.status.saved": "Salvato: {name} | {status}",
        "voice_profiles.error.title": "Profili vocali",
        "voice_profiles.error.enter_name_before_recording": "Inserisci un nome profilo prima di registrare.",
        "voice_profiles.error.no_microphone": "Nessun input microfono rilevato.",
        "voice_profiles.dialog.select_reference_audio": "Seleziona audio di riferimento",
        "voice_profiles.dialog.delete_title": "Eliminare profilo vocale e lavoro di modeling?",
        "voice_profiles.type.reference": "Reference clone",
        "voice_profiles.type.modeling": "Modeling dataset",
        "voice_profiles.status.modeling_dataset": "Dataset modeling",
        "voice_profiles.status.missing_reference_audio": "Audio di riferimento mancante",
        "voice_profiles.status.missing_audio_file": "File audio mancante",
        "voice_profiles.status.incomplete_audio_file": "File audio incompleto",
        "voice_profiles.status.unsupported_audio_format": "Formato audio non supportato",
        "voice_profiles.status.ready": "Pronto",
    },
}

STATIC_TEXT_TRANSLATIONS_IT = {
    "Yes": "Sì",
    "No": "No",
    "OK": "OK",
    "Convert, transcribe and subtitle": "Converti, trascrivi e sottotitola",
    "Online text-to-speech, offline speech-to-text and practical video subtitle tools in one workspace.": (
        "Text-to-speech online, speech-to-text offline e strumenti pratici per sottotitoli video in un unico workspace."
    ),
    "DASHBOARD": "DASHBOARD",
    "Text to Speech": "Text to Speech",
    "Convert DOCX, DOC, PDF and TXT into MP3 with Microsoft Edge voices.": (
        "Converti DOCX, DOC, PDF e TXT in MP3 con le voci Microsoft Edge."
    ),
    "Online TTS": "TTS online",
    "Local Voices": "Voci locali",
    "Prepare reference profiles, modeling datasets and XTTS-v2 training configuration.": (
        "Prepara profili di riferimento, dataset di modeling e configurazione training XTTS-v2."
    ),
    "Profiles, datasets, training setup": "Profili, dataset, setup training",
    "Dataset": "Dataset",
    "No modeling profile selected.": "Nessun profilo modeling selezionato.",
    "Dataset for: {name} | {language}": "Dataset per: {name} | {language}",
    "Ready clips\n{count}": "Clip pronte\n{count}",
    "Ready clips\n--": "Clip pronte\n--",
    "Ready duration\n{duration}": "Durata pronta\n{duration}",
    "Ready duration\n--": "Durata pronta\n--",
    "Tier\n{tier}": "Tier\n{tier}",
    "Tier\n--": "Tier\n--",
    "Exportable\n{value}": "Esportabile\n{value}",
    "Exportable\n--": "Esportabile\n--",
    "{count} of {total} clip(s) are ready.": "{count} di {total} clip pronte.",
    "Total duration of ready clips.": "Durata totale delle clip pronte.",
    "Dataset duration tier.": "Tier basato sulla durata del dataset.",
    "Dataset can be exported.": "Il dataset può essere esportato.",
    "Transcription": "Trascrizione",
    "Create Markdown transcripts, automatic SRT files, or aligned subtitles with bundled offline models.": (
        "Crea transcript Markdown, file SRT automatici o sottotitoli allineati con i modelli offline inclusi."
    ),
    "Offline STT": "STT offline",
    "Subtitles": "Sottotitoli",
    "Embed an SRT track or burn subtitles into an MP4 with controlled output quality.": (
        "Integra una traccia SRT o imprimi i sottotitoli in un MP4 con qualità output controllata."
    ),
    "FFmpeg tools": "Strumenti FFmpeg",
    "Audio Cleanup": "Pulizia audio",
    "Remove short AI TTS artifacts or hallucinated fragments without rebuilding the whole output.": (
        "Rimuovi brevi artefatti TTS AI o frammenti allucinati senza rigenerare tutto l'output."
    ),
    "TTS artifact repair": "Correzione artefatti TTS",
    "Video Cleanup": "Pulizia video",
    "Detect isolated black-frame glitches and repair them without shortening the video.": (
        "Rileva glitch isolati di frame neri e correggili senza accorciare il video."
    ),
    "Frame repair/removal": "Riparazione/rimozione frame",
    "Recent jobs": "Job recenti",
    "Generate MP3 with online Edge voices or prepared local voice profiles.": (
        "Genera MP3 con voci Edge online o profili vocali locali preparati."
    ),
    "Creates transcripts or SRT subtitles locally with the bundled offline STT package.": (
        "Crea transcript o sottotitoli SRT in locale con il pacchetto STT offline incluso."
    ),
    "Embed an SRT track without re-encoding or burn subtitles directly into the video frames.": (
        "Integra una traccia SRT senza ricodifica o imprimi i sottotitoli direttamente nei frame video."
    ),
    "Remove, silence or fade short AI TTS artifacts and hallucinated fragments, not full audio edits.": (
        "Rimuovi, silenzia o sfuma brevi artefatti TTS AI e frammenti allucinati; non è un editor audio completo."
    ),
    "Review video frames, queue cleanup changes and export a repaired copy before subtitling.": (
        "Rivedi i frame video, prepara le modifiche e esporta una copia corretta prima dei sottotitoli."
    ),
    "Black-frame detection can auto-mark isolated black frames. Frame-glitch detection only marks suspicious "
    "frames for manual review.": (
        "Il detect dei frame neri può auto-marcare frame neri isolati. Il detect glitch segnala solo frame "
        "sospetti per revisione manuale."
    ),
    "Modeling Datasets": "Dataset di modeling",
    "Collect authorized audio clips and exact text pairs before future voice model training.": (
        "Raccogli clip audio autorizzate e coppie testo esatto prima del futuro training del modello vocale."
    ),
    "Voice Modeling": "Voice Modeling",
    "Validate an exported dataset and prepare a controlled XTTS-v2 training job configuration.": (
        "Valida un dataset esportato e prepara una configurazione controllata per un job training XTTS-v2."
    ),
    "Training": "Training",
    "Run configured local voice training jobs.": "Esegui job di training vocale locale già configurati.",
    "Select an exported dataset.": "Seleziona un dataset esportato.",
    "CRF is constant quality: lower number means higher quality and a larger output file.": (
        "CRF indica qualità costante: un numero più basso significa qualità maggiore e file output più grande."
    ),
    "Auto (recommended)": "Auto (consigliata)",
    "Standard (CRF 20)": "Standard (CRF 20)",
    "High quality (CRF 18)": "Alta qualità (CRF 18)",
    "Maximum quality (CRF 16)": "Qualità massima (CRF 16)",
    "Original bitrate": "Bitrate originale",
    "Chooses CRF 20 for most 1080p videos, CRF 18 for 4K or high-bitrate 1080p sources.": (
        "Sceglie CRF 20 per la maggior parte dei video 1080p, CRF 18 per sorgenti 4K o 1080p ad alto bitrate."
    ),
    "CRF 20: high quality for 1080p, usually smaller files.": (
        "CRF 20: alta qualità per 1080p, di solito file più piccoli."
    ),
    "CRF 18: closer to the source, larger files.": "CRF 18: più vicino alla sorgente, file più grandi.",
    "CRF 16: very high quality, much larger files.": "CRF 16: qualità molto alta, file molto più grandi.",
    "Targets the source video bitrate; still re-encodes, so it is not lossless.": (
        "Punta al bitrate del video sorgente; ricodifica comunque, quindi non è lossless."
    ),
    "CRF 18: high visual quality, bitrate may differ from the source.": (
        "CRF 18: alta qualità visiva, il bitrate può differire dalla sorgente."
    ),
    "CRF 16: very high quality, larger output files.": "CRF 16: qualità molto alta, file output più grandi.",
    "CRF 20: good quality and smaller files, but less conservative.": (
        "CRF 20: buona qualità e file più piccoli, ma meno conservativo."
    ),
    "Background box": "Box di sfondo",
    "Embed SRT track": "Integra traccia SRT",
    "Burn in SRT": "Imprimi SRT",
    "Adds the SRT as a subtitle track. Video and audio streams are copied when possible.": (
        "Aggiunge l'SRT come traccia sottotitoli. Stream video e audio vengono copiati quando possibile."
    ),
    "Draws subtitles into the video frames. The video must be re-encoded.": (
        "Disegna i sottotitoli nei frame video. Il video deve essere ricodificato."
    ),
    "Bottom center": "Centro basso",
    "Middle center": "Centro",
    "Top center": "Centro alto",
    "White": "Bianco",
    "Warm yellow": "Giallo caldo",
    "Light cyan": "Ciano chiaro",
    "Black": "Nero",
    "Dark gray": "Grigio scuro",
    "Black 70%": "Nero 70%",
    "Dark gray 70%": "Grigio scuro 70%",
    "Files": "File",
    "Files and mode": "File e modalità",
    "Media and output": "Media e output",
    "Mode and quality": "Modalità e qualità",
    "Transcription settings": "Impostazioni trascrizione",
    "Training configuration": "Configurazione training",
    "Training preflight": "Preflight training",
    "Training jobs": "Job di training",
    "Exported dataset": "Dataset esportato",
    "Dataset export": "Export dataset",
    "Datasets": "Dataset",
    "Clips": "Clip",
    "Clip text": "Testo clip",
    "Waveform": "Forma d'onda",
    "Applied changes": "Modifiche applicate",
    "Frame review": "Revisione frame",
    "Black frames": "Frame neri",
    "Suspicious frames": "Frame sospetti",
    "Burn-in font": "Font burn-in",
    "Blocks": "Blocchi",
    "Block settings": "Impostazioni blocco",
    "Voice": "Voce",
    "Voice profile": "Profilo vocale",
    "Voice mode": "Modalità voce",
    "Block voice": "Voce blocco",
    "Block speed": "Velocità blocco",
    "Engine": "Engine",
    "Search": "Cerca",
    "Speed": "Velocità",
    "Mode": "Modalità",
    "Language": "Lingua",
    "Device": "Device",
    "Preset": "Preset",
    "Burn-in quality": "Qualità burn-in",
    "Output quality": "Qualità output",
    "Layout": "Layout",
    "Legibility": "Leggibilità",
    "Colors": "Colori",
    "Position": "Posizione",
    "Vertical margin": "Margine verticale",
    "Font size": "Dimensione font",
    "Outline": "Contorno",
    "Shadow": "Ombra",
    "Text": "Testo",
    "Box": "Box",
    "Zoom": "Zoom",
    "Start": "Inizio",
    "End": "Fine",
    "Job config": "Configurazione job",
    "Max epochs": "Epoch massime",
    "Batch size": "Batch size",
    "Reference audio": "Audio di riferimento",
    "Input file": "File input",
    "Save MP3 as": "Salva MP3 come",
    "Media file": "File media",
    "Provided transcript file": "File transcript fornito",
    "Save output as": "Salva output come",
    "Video file": "File video",
    "SRT file": "File SRT",
    "Save video as": "Salva video come",
    "Audio file": "File audio",
    "Save cleaned audio as": "Salva audio pulito come",
    "Save cleaned video as": "Salva video pulito come",
    "Model output folder": "Cartella output modello",
    "Resume checkpoint": "Checkpoint di ripresa",
    "Browse...": "Sfoglia...",
    "Browse external...": "Sfoglia esterno...",
    "Save as...": "Salva come...",
    "Generate": "Genera",
    "Cancel": "Annulla",
    "Open output": "Apri output",
    "Open folder": "Apri cartella",
    "Show details": "Mostra dettagli",
    "Hide details": "Nascondi dettagli",
    "Create video": "Crea video",
    "Preview style": "Anteprima stile",
    "Clean audio": "Pulisci audio",
    "Play output": "Riproduci output",
    "Play all": "Riproduci tutto",
    "Play selection": "Riproduci selezione",
    "Cut": "Taglia",
    "Silence": "Silenzia",
    "Fade": "Fade",
    "Cut range": "Taglia intervallo",
    "Replace with silence": "Sostituisci con silenzio",
    "Fade range to silence": "Sfuma intervallo a silenzio",
    "Fit": "Adatta",
    "Clean video": "Pulisci video",
    "Detect black frames": "Rileva frame neri",
    "Detect frame glitches": "Rileva glitch frame",
    "Mark selected": "Marca selezionati",
    "Unmark selected": "Rimuovi mark",
    "Clear marks": "Cancella mark",
    "Freeze previous frame": "Congela frame precedente",
    "Remove selected frames": "Rimuovi frame selezionati",
    "Select video file": "Seleziona file video",
    "Select SRT subtitle file": "Seleziona file sottotitoli SRT",
    "Save subtitled video as": "Salva video sottotitolato come",
    "Preview subtitles": "Anteprima sottotitoli",
    "Select an existing video file.": "Seleziona un file video esistente.",
    "Select an existing .srt subtitle file.": "Seleziona un file sottotitoli .srt esistente.",
    "Subtitle style preview": "Anteprima stile sottotitoli",
    "Preview at {time:.2f}s": "Anteprima a {time:.2f}s",
    "Preview unavailable": "Anteprima non disponibile",
    "Could not generate subtitle preview.": "Impossibile generare l'anteprima sottotitoli.",
    "Embedding subtitle track...": "Integrazione traccia sottotitoli...",
    "Burning subtitles into video...": "Burn-in sottotitoli nel video...",
    "Subtitles embedded.": "Sottotitoli integrati.",
    "Subtitles burned into video.": "Sottotitoli impressi nel video.",
    "Success": "Successo",
    "Please select a video file.": "Seleziona un file video.",
    "The selected video file does not exist.": "Il file video selezionato non esiste.",
    "The selected file must be a video.": "Il file selezionato deve essere un video.",
    "The selected video file could not be inspected or has no readable video stream.": (
        "Il file video selezionato non può essere analizzato oppure non contiene uno stream video leggibile."
    ),
    "Select a readable video file to load frame review.": (
        "Seleziona un file video leggibile per caricare la revisione frame."
    ),
    "ffmpeg unavailable for frame review.": "ffmpeg non disponibile per la revisione frame.",
    "Loading frame review...": "Caricamento revisione frame...",
    "The selected video has no readable video stream.": "Il video selezionato non ha uno stream video leggibile.",
    "Frame review ready.": "Revisione frame pronta.",
    "Frame review unavailable.": "Revisione frame non disponibile.",
    "Marked frame pending action | #{frame_number} / {time:.3f}s": (
        "Frame marcato in attesa di azione | #{frame_number} / {time:.3f}s"
    ),
    "{conflict_message} Remove the duplicate queued change before cleaning.": (
        "{conflict_message} Rimuovi la modifica duplicata in coda prima della pulizia."
    ),
    "Frame(s) {frames}{suffix} have more than one queued cleanup action.": (
        "I frame {frames}{suffix} hanno più di un'azione di cleanup in coda."
    ),
    "{change_count} change(s) queued; {pending_count} marked frame(s) pending action.": (
        "{change_count} modifica/e in coda; {pending_count} frame marcato/i in attesa di azione."
    ),
    "{change_count} change(s) queued.": "{change_count} modifica/e in coda.",
    "{pending_count} marked frame(s) pending Freeze or Remove.": (
        "{pending_count} frame marcato/i in attesa di Freeze o Remove."
    ),
    "Select a pending marked row or a marked frame before applying cleanup.": (
        "Seleziona una riga marcata in attesa o un frame marcato prima di applicare la pulizia."
    ),
    "{frames} already has a queued cleanup action. Remove that queued change before choosing another action.": (
        "{frames} ha già un'azione di pulizia in coda. Rimuovi quella modifica prima di scegliere un'altra azione."
    ),
    "Queued video cleanup change {number}.": "Modifica video cleanup {number} messa in coda.",
    "Queued {count} video cleanup changes.": "{count} modifiche video cleanup messe in coda.",
    "Removed queued video cleanup change.": "Modifica video cleanup rimossa dalla coda.",
    "Load frame review for this video before cleaning frames.": (
        "Carica la revisione frame di questo video prima di pulire i frame."
    ),
    "Frame review is not ready yet.": "La revisione frame non è ancora pronta.",
    "Apply at least one video cleanup change before cleaning video.": (
        "Applica almeno una modifica video cleanup prima di pulire il video."
    ),
    "Repaired video output must be .mp4, .mkv, .mov or .m4v.": (
        "Il video riparato deve essere .mp4, .mkv, .mov o .m4v."
    ),
    "ffmpeg missing": "ffmpeg mancante",
    "ffmpeg missing.": "ffmpeg mancante.",
    "Could not find ffmpeg. Use the full VoiceBridge bundle.": (
        "Impossibile trovare ffmpeg. Usa il bundle completo di VoiceBridge."
    ),
    "Detecting black-frame candidates...": "Rilevamento candidati frame neri...",
    "Detecting black frames...": "Rilevamento frame neri...",
    "Frame review not ready.": "Revisione frame non pronta.",
    "Load frame review for this video before detecting frame glitches.": (
        "Carica la revisione frame di questo video prima di rilevare glitch frame."
    ),
    "ML runtime missing.": "ML runtime mancante.",
    "Could not find ML Python runtime:\n{path}": "Impossibile trovare il runtime Python ML:\n{path}",
    "Anomaly worker missing.": "Worker anomalie mancante.",
    "Could not find:\n{path}": "Impossibile trovare:\n{path}",
    "Detecting suspicious frame glitches...": "Rilevamento glitch frame sospetti...",
    "Cleaning {count} queued change(s)...": "Pulizia di {count} modifica/e in coda...",
    "Cleaning change {index} of {count}...": "Pulizia modifica {index} di {count}...",
    "Select one or more unqueued frames in the frame review first.": (
        "Seleziona prima uno o più frame non in coda nella revisione frame."
    ),
    "Select one or more frames in the frame review first.": (
        "Seleziona prima uno o più frame nella revisione frame."
    ),
    "Frame {frame_number} | {time:.3f}s | {pblack}% black | {reason}": (
        "Frame {frame_number} | {time:.3f}s | {pblack}% nero | {reason}"
    ),
    "Marked pending action": "Marcato in attesa di azione",
    "Detected; review before marking manually": "Rilevato; rivedi prima di marcare manualmente",
    "Frame {frame_number} | {time:.3f}s | {kind} | score {score:.1f}": (
        "Frame {frame_number} | {time:.3f}s | {kind} | score {score:.1f}"
    ),
    "Single-frame anomaly": "Anomalia single-frame",
    "Isolated transition frame": "Frame di transizione isolato",
    "Cut-boundary anomaly": "Anomalia su boundary di cut",
    "Suspicious frame": "Frame sospetto",
    "No black-frame candidates found.": "Nessun candidato frame nero trovato.",
    "Black-frame candidates: {count}": "Candidati frame neri: {count}",
    "Repairable isolated frames: {count}": "Frame isolati riparabili: {count}",
    "Longer black runs left untouched: {count}": "Sequenze nere più lunghe lasciate intatte: {count}",
    "...and {count} more candidates in the log.": "...e altri {count} candidati nel log.",
    "No suspicious frame anomalies found.": "Nessuna anomalia frame sospetta trovata.",
    "...and {count} more suspicious frame(s) in the log.": (
        "...e altri {count} frame sospetti nel log."
    ),
    "Detected {candidate_count} black-frame candidate(s); {actionable_count} marked pending action.": (
        "Rilevati {candidate_count} candidati frame neri; {actionable_count} marcati in attesa di azione."
    ),
    "Detected {count} suspicious frame(s).": "Rilevati {count} frame sospetti.",
    "No video cleanup changes queued.": "Nessuna modifica video cleanup in coda.",
    "Applied {change_count} video cleanup change(s).": "Applicate {change_count} modifiche video cleanup.",
    "Video saved:\n{path}": "Video salvato:\n{path}",
    "Cancelling...": "Annullamento...",
    "Download Whisper large-v3": "Scarica Whisper large-v3",
    "Transcript Markdown (.md)": "Transcript Markdown (.md)",
    "Auto subtitles (.srt)": "Sottotitoli automatici (.srt)",
    "Subtitles from provided text (.srt)": "Sottotitoli da testo fornito (.srt)",
    "Auto": "Auto",
    "CPU": "CPU",
    "CUDA": "CUDA",
    "Uses CUDA when available; otherwise falls back to CPU.": (
        "Usa CUDA quando disponibile; altrimenti passa alla CPU."
    ),
    "Forces CPU execution.": "Forza l'esecuzione su CPU.",
    "Uses the detected CUDA GPU.": "Usa la GPU CUDA rilevata.",
    "CUDA is not available in the current STT runtime on this machine.": (
        "CUDA non è disponibile nel runtime STT corrente su questa macchina."
    ),
    "Auto detect": "Rilevamento automatico",
    "offline ready": "offline pronto",
    "download for SRT": "download per SRT",
    "Detects the spoken language automatically.": "Rileva automaticamente la lingua parlata.",
    "Included in the offline package for SRT alignment.": (
        "Incluso nel pacchetto offline per l'allineamento SRT."
    ),
    "Downloaded on this computer and available offline for SRT alignment.": (
        "Scaricato su questo computer e disponibile offline per l'allineamento SRT."
    ),
    "Markdown transcripts work offline; SRT alignment downloads this language on request.": (
        "I transcript Markdown funzionano offline; l'allineamento SRT scarica questa lingua su richiesta."
    ),
    "Select audio or video file": "Seleziona file audio o video",
    "Select transcript file": "Seleziona file transcript",
    "Please select an audio or video file.": "Seleziona un file audio o video.",
    "The selected media file does not exist.": "Il file media selezionato non esiste.",
    "The selected media file has no readable audio stream.": (
        "Il file media selezionato non contiene uno stream audio leggibile."
    ),
    "Please choose where to save the output file.": "Scegli dove salvare il file output.",
    "Please select the transcript text file to align.": "Seleziona il file testo transcript da allineare.",
    "STT offline package incomplete.": "Pacchetto STT offline incompleto.",
    "STT environment missing": "Ambiente STT mancante",
    "Could not find the STT Python runtime:\n{path}": "Impossibile trovare il runtime Python STT:\n{path}",
    "STT worker missing": "Worker STT mancante",
    "Transcript file error": "Errore file transcript",
    "Could not read transcript file.\n\n{message}": "Impossibile leggere il file transcript.\n\n{message}",
    "Starting offline transcription...": "Avvio trascrizione offline...",
    "Alignment model missing.": "Modello di allineamento mancante.",
    "Alignment model missing": "Modello di allineamento mancante",
    "The required alignment model is not included.": "Il modello di allineamento richiesto non è incluso.",
    "Alignment model required.": "Modello di allineamento richiesto.",
    "Selected language": "Lingua selezionata",
    "Detected language": "Lingua rilevata",
    (
        "{source_label}: {language_label}.\n\n"
        "The alignment model is not included. Download it now?\n\n"
        "After download, this language will work offline on this computer."
    ): (
        "{source_label}: {language_label}.\n\n"
        "Il modello di allineamento non è incluso. Vuoi scaricarlo ora?\n\n"
        "Dopo il download questa lingua funzionerà offline su questo computer."
    ),
    "Not enough disk space.": "Spazio disco insufficiente.",
    "Downloading alignment model for {language}...": "Download modello di allineamento per {language}...",
    "Downloading Whisper large-v3 model...": "Download modello Whisper large-v3...",
    "Alignment model downloaded. Restarting SRT job...": (
        "Modello di allineamento scaricato. Riavvio job SRT..."
    ),
    "Whisper large-v3 model downloaded.": "Modello Whisper large-v3 scaricato.",
    "Output saved:\n{path}": "Output salvato:\n{path}",
    "STT CUDA failed": "CUDA STT fallita",
    "Transcription failed in the CUDA runtime.\n\nRetry the same job on CPU now?": (
        "La trascrizione è fallita nel runtime CUDA.\n\nRitentare lo stesso job su CPU?"
    ),
    "Retrying transcription on CPU...": "Riprovo la trascrizione su CPU...",
    "STT Error": "Errore STT",
    "Generate MP3": "Genera MP3",
    "Edge TTS": "Edge TTS",
    "Local TTS": "Local TTS",
    "Checking Edge TTS voices": "Controllo voci Edge TTS",
    "Checking Edge TTS voices...": "Controllo voci Edge TTS...",
    "Loading complete voice list...": "Caricamento lista completa voci...",
    "Retrying Edge TTS voice list...": "Riprovo caricamento lista voci Edge TTS...",
    "{count} online voices loaded": "{count} voci online caricate",
    "Loaded {count} voices. Select a file to filter by language.": (
        "{count} voci caricate. Seleziona un file per filtrare per lingua."
    ),
    "Edge TTS offline; Local TTS may still work": "Edge TTS offline; Local TTS potrebbe funzionare",
    (
        "Edge TTS voice list unavailable. Edge TTS requires internet; "
        "Local TTS remains available if configured. Retrying automatically."
    ): (
        "Lista voci Edge TTS non disponibile. Edge TTS richiede internet; "
        "Local TTS resta disponibile se configurato. Riprovo automaticamente."
    ),
    "Edge TTS is unavailable. Check internet connection or use Local TTS.": (
        "Edge TTS non è disponibile. Controlla la connessione internet o usa Local TTS."
    ),
    "Edge TTS voice list is unavailable. Check internet connection or use Local TTS.": (
        "La lista voci Edge TTS non è disponibile. Controlla la connessione internet o usa Local TTS."
    ),
    "Paragraphs": "Paragrafi",
    "Lines": "Righe",
    "Local multi-voice requires at least two ready local voices.": (
        "La modalità multi-voce locale richiede almeno due voci locali pronte."
    ),
    "No ready local voices": "Nessuna voce locale pronta",
    "Create a ready reference profile or complete a voice training job.": (
        "Crea un profilo di riferimento pronto o completa un job di training voce."
    ),
    "Trained model selected. Download XTTS-v2 is only required for reference clone voices.": (
        "Modello addestrato selezionato. Il download XTTS-v2 è richiesto solo per voci reference clone."
    ),
    "XTTS-v2 model download is incomplete. Download again to repair it.": (
        "Il download del modello XTTS-v2 è incompleto. Scaricalo di nuovo per ripararlo."
    ),
    "XTTS-v2 model not downloaded. Required once for all languages.": (
        "Modello XTTS-v2 non scaricato. Richiesto una sola volta per tutte le lingue."
    ),
    "Local TTS ready.": "Local TTS pronto.",
    "Download XTTS-v2 before Local TTS generation.": "Scarica XTTS-v2 prima della generazione Local TTS.",
    "Block local voice": "Voce locale blocco",
    "Use current profile": "Usa profilo corrente",
    "Use current profile for all": "Usa profilo corrente per tutti",
    "Select input file": "Seleziona file input",
    "Save audio as": "Salva audio come",
    "Detecting file language...": "Rilevamento lingua file...",
    "Reading file text...": "Lettura testo file...",
    "Uses the selected voice and speed for the whole document.": (
        "Usa la voce e la velocità selezionate per tutto il documento."
    ),
    "Uses the selected voice profile for the whole document.": (
        "Usa il profilo vocale selezionato per tutto il documento."
    ),
    (
        "Split the document into blocks and assign voice profiles per block. "
        "Long local blocks keep the same profile when XTTS splits them internally."
    ): (
        "Divide il documento in blocchi e assegna profili vocali per blocco. "
        "I blocchi locali lunghi mantengono lo stesso profilo quando XTTS li divide internamente."
    ),
    "Split the document into blocks and assign voice or speed per block.": (
        "Divide il documento in blocchi e assegna voce o velocità per blocco."
    ),
    "Generating multi-voice audio...": "Generazione audio multi-voce...",
    "Local TTS environment missing.": "Ambiente Local TTS mancante.",
    "Local TTS environment missing": "Ambiente Local TTS mancante",
    "Could not find the ML Python runtime:\n{path}": "Impossibile trovare il runtime Python ML:\n{path}",
    "Local TTS worker missing.": "Worker Local TTS mancante.",
    "Local TTS worker missing": "Worker Local TTS mancante",
    "Starting local multi-voice TTS...": "Avvio Local TTS multi-voce...",
    (
        "XTTS-v2 is a single multilingual model of about 1.8-2.3 GB.\n\n"
        "The model uses the Coqui Public Model License and is limited to non-commercial use, "
        "including generated output.\n\n"
        "Download the model now?"
    ): (
        "XTTS-v2 è un singolo modello multilingua da circa 1.8-2.3 GB.\n\n"
        "Il modello usa la Coqui Public Model License ed è limitato all'uso non commerciale, "
        "incluso l'output generato.\n\n"
        "Scaricare il modello ora?"
    ),
    "XTTS-v2 model is already downloaded.": "Il modello XTTS-v2 è già scaricato.",
    "XTTS-v2 download cancelled.": "Download XTTS-v2 annullato.",
    "Downloading XTTS-v2 model...": "Download modello XTTS-v2...",
    "XTTS-v2 model downloaded:\n{path}": "Modello XTTS-v2 scaricato:\n{path}",
    "Merging audio blocks...": "Unione blocchi audio...",
    "Audio saved:\n{path}": "Audio salvato:\n{path}",
    "Local TTS CUDA failed": "CUDA Local TTS fallita",
    "Local TTS failed in the CUDA runtime.\n\nRetry the same job on CPU now?": (
        "Local TTS è fallito nel runtime CUDA.\n\nRitentare lo stesso job su CPU?"
    ),
    "Retrying Local TTS on CPU...": "Riprovo Local TTS su CPU...",
    "Cancelling TTS job...": "Annullamento job TTS...",
    "Open in Audio Cleanup": "Apri in Pulizia audio",
    "Single voice": "Voce singola",
    "Multi-voice blocks": "Blocchi multi-voce",
    "Preferred voice": "Voce preferita",
    "Manage profiles": "Gestisci profili",
    "Download XTTS-v2": "Scarica XTTS-v2",
    "Split document": "Dividi documento",
    "Merge selected": "Unisci selezionati",
    "Apply to block": "Applica al blocco",
    "Use current voice": "Usa voce corrente",
    "Use current voice for all": "Usa voce corrente per tutti",
    "Refresh": "Aggiorna",
    "Microphone": "Microfono",
    "Microphone unavailable": "Microfono non disponibile",
    "No microphone input was detected.": "Nessun input microfono rilevato.",
    "Select a microphone input first.": "Seleziona prima un input microfono.",
    "Export dataset": "Esporta dataset",
    "Open audio": "Apri audio",
    "Retry recording": "Riprova registrazione",
    "Verify text": "Verifica testo",
    "Exclude export": "Escludi da export",
    "Delete clip": "Elimina clip",
    "Open in Transcription": "Apri in Trascrizione",
    "Generate guided text": "Genera testo guidato",
    "Load text": "Carica testo",
    "Reset guided history": "Reset cronologia guidata",
    "Record from text": "Registra da testo",
    "Free record": "Registrazione libera",
    "Save transcript": "Salva transcript",
    "Clear checkpoint": "Cancella checkpoint",
    "Download training assets": "Scarica asset training",
    "Refresh preflight": "Aggiorna preflight",
    "Save training config": "Salva configurazione training",
    "Open output folder": "Apri cartella output",
    "Prepare": "Prepara",
    "Dry run": "Dry run",
    "Start training": "Avvia training",
    "Open job folder": "Apri cartella job",
    "Close": "Chiudi",
    "Clear": "Pulisci",
    "No jobs yet.": "Nessun job.",
    "No audio selected.": "Nessun audio selezionato.",
    "No waveform loaded.": "Nessuna waveform caricata.",
    "Loading waveform...": "Caricamento waveform...",
    "Waveform unavailable.": "Waveform non disponibile.",
    "Waveform ready. View: {start} - {end}": "Waveform pronta. Vista: {start} - {end}",
    "TTS block JSON does not match the selected audio file.": (
        "Il JSON dei blocchi TTS non corrisponde al file audio selezionato."
    ),
    "TTS block JSON found, but no usable ranges were detected.": (
        "JSON blocchi TTS trovato, ma non sono stati rilevati intervalli usabili."
    ),
    "{engine} block map loaded with duration mismatch; verify ranges before editing.": (
        "Mappa blocchi {engine} caricata con durata non corrispondente; verifica gli intervalli prima di modificare."
    ),
    "{engine} block map loaded: {count} range(s).": "Mappa blocchi {engine} caricata: {count} intervallo/i.",
    "Selected {block_label} | {voice}": "Selezionato {block_label} | {voice}",
    "Select audio file": "Seleziona file audio",
    "Selected audio file does not exist.": "Il file audio selezionato non esiste.",
    "Could not inspect audio: {message}": "Impossibile analizzare l'audio: {message}",
    "Could not detect an audio stream.": "Impossibile rilevare uno stream audio.",
    "Duration: {duration}": "Durata: {duration}",
    "No applied changes.": "Nessuna modifica applicata.",
    "Apply one or more ranges before cleaning audio.": (
        "Applica uno o più intervalli prima di pulire l'audio."
    ),
    "Selection: none": "Selezione: nessuna",
    "Selection: {start} - {end} ({duration:.3f}s)": "Selezione: {start} - {end} ({duration:.3f}s)",
    "The selected range overlaps a cut already queued.": (
        "L'intervallo selezionato si sovrappone a un taglio già in coda."
    ),
    "Select a range before applying a cleanup change.": (
        "Seleziona un intervallo prima di applicare una modifica di pulizia."
    ),
    "The selected range overlaps a cleanup change already queued: C. {index} ({start} - {end}).": (
        "L'intervallo selezionato si sovrappone a una modifica già in coda: C. {index} ({start} - {end})."
    ),
    "The selected range is no longer valid after queued cuts.": (
        "L'intervallo selezionato non è più valido dopo i tagli in coda."
    ),
    "Queued cleanup change {number}.": "Modifica di pulizia {number} messa in coda.",
    "Removed queued cleanup change.": "Modifica di pulizia rimossa dalla coda.",
    "Please select an audio file.": "Seleziona un file audio.",
    "The selected file must be .mp3, .wav, .m4a, .aac, .flac or .ogg.": (
        "Il file selezionato deve essere .mp3, .wav, .m4a, .aac, .flac o .ogg."
    ),
    "Could not detect the selected audio duration.": "Impossibile rilevare la durata dell'audio selezionato.",
    "Apply at least one cleanup range before cleaning audio.": (
        "Applica almeno un intervallo di pulizia prima di pulire l'audio."
    ),
    (
        "Cleanup range C. {second} overlaps C. {first}. "
        "Remove or adjust overlapping queued ranges before cleaning audio."
    ): (
        "L'intervallo C. {second} si sovrappone a C. {first}. Rimuovi o modifica gli intervalli "
        "sovrapposti prima di pulire l'audio."
    ),
    "Cleaned audio output must be .mp3, .wav, .m4a, .aac, .flac or .ogg.": (
        "L'audio pulito deve essere .mp3, .wav, .m4a, .aac, .flac o .ogg."
    ),
    "Cleaning {count} queued range(s)...": "Pulizia di {count} intervallo/i in coda...",
    "Cleaned audio saved.": "Audio pulito salvato.",
    "Audio saved and loaded for the next cleanup pass:\n{path}": (
        "Audio salvato e caricato per il prossimo passaggio di pulizia:\n{path}"
    ),
    "No TTS block JSON found.": "Nessun JSON blocchi TTS trovato.",
    "Select a TTS block to preview its text.": "Seleziona un blocco TTS per vedere il testo.",
    "Mark frames, then apply Freeze or Remove before cleaning video.": (
        "Marca i frame, poi applica Freeze o Remove prima di pulire il video."
    ),
    "Select a video file to load frame review.": "Seleziona un file video per caricare la revisione frame.",
    "Timeline: --": "Timeline: --",
    "Load frame review, then run Detect black frames.": (
        "Carica la revisione frame, poi avvia Rileva frame neri."
    ),
    "Load frame review, then run Detect frame glitches.": (
        "Carica la revisione frame, poi avvia Rileva glitch frame."
    ),
    "Run Detect black frames to list black-frame candidates.": (
        "Avvia Rileva frame neri per elencare i candidati."
    ),
    "Run Detect frame glitches to list non-black suspicious frames.": (
        "Avvia Rileva glitch frame per elencare frame sospetti non neri."
    ),
    "Dataset readiness summary appears here.": "Il riepilogo readiness del dataset appare qui.",
    "Recording quality details appear here after a clip is saved.": (
        "I dettagli qualità registrazione appaiono qui dopo il salvataggio di una clip."
    ),
    "Guided prompts: 0 / 0 used": "Prompt guidati: 0 / 0 usati",
    "No training job configured.": "Nessun job training configurato.",
    "No modeling datasets yet.": "Nessun dataset di modeling.",
    "{name} | {clip_count} clip(s), {ready_count} ready": (
        "{name} | {clip_count} clip, {ready_count} pronte"
    ),
    "Create or select a modeling dataset.": "Crea o seleziona un dataset di modeling.",
    "Select a modeling dataset.": "Seleziona un dataset di modeling.",
    "No clips yet.": "Nessuna clip.",
    "Create a Voice Profile with type Modeling dataset first.": (
        "Crea prima un Voice Profile di tipo Modeling dataset."
    ),
    "Dataset: {name} | {clip_count} clip(s).": "Dataset: {name} | {clip_count} clip.",
    "No valid dataset exports found.": "Nessun export dataset valido trovato.",
    "Export a Usable or Good dataset from Local Voices > Datasets first.": (
        "Esporta prima un dataset Usable o Good da Voci locali > Dataset."
    ),
    "No valid dataset export found.": "Nessun export dataset valido trovato.",
    "Select exported dataset": "Seleziona dataset esportato",
    "Dataset not ready.": "Dataset non pronto.",
    "No dataset selected.": "Nessun dataset selezionato.",
    "Dataset export validated.": "Export dataset validato.",
    "Preflight not run yet. Use Refresh preflight.": "Preflight non ancora eseguito. Usa Aggiorna preflight.",
    "Select model output folder": "Seleziona cartella output modello",
    "Select resume checkpoint": "Seleziona checkpoint di ripresa",
    "Preflight needs refresh after configuration changes.": (
        "Il preflight va aggiornato dopo le modifiche alla configurazione."
    ),
    "Checking Voice Modeling prerequisites...": "Controllo prerequisiti Voice Modeling...",
    "Download XTTS-v2 training assets": "Scarica asset training XTTS-v2",
    (
        "XTTS-v2 DVAE is about 211 MB and mel_stats.pth is also needed for voice modeling/fine-tuning.\n\n"
        "The file is distributed with XTTS-v2 under the Coqui Public Model License, "
        "limited to non-commercial use.\n\n"
        "Download the missing training asset(s) now?"
    ): (
        "XTTS-v2 DVAE pesa circa 211 MB e mel_stats.pth è necessario per voice modeling/fine-tuning.\n\n"
        "Il file è distribuito con XTTS-v2 sotto Coqui Public Model License, "
        "limitata all'uso non commerciale.\n\n"
        "Scaricare ora gli asset training mancanti?"
    ),
    "XTTS-v2 training assets are already downloaded:\n{dvae_path}\n{mel_stats_path}": (
        "Gli asset training XTTS-v2 sono già scaricati:\n{dvae_path}\n{mel_stats_path}"
    ),
    "Training assets download cancelled.": "Download asset training annullato.",
    "Downloading XTTS-v2 training assets...": "Download asset training XTTS-v2...",
    "Cancel download": "Annulla download",
    "Cancelling training assets download...": "Annullamento download asset training...",
    "XTTS-v2 training assets ready.": "Asset training XTTS-v2 pronti.",
    "XTTS-v2 training assets ready:\n{path}": "Asset training XTTS-v2 pronti:\n{path}",
    "Training assets download failed.": "Download asset training fallito.",
    "Select a valid exported dataset first.": "Seleziona prima un dataset esportato valido.",
    "Training job configured: {path}": "Job training configurato: {path}",
    "Training job config saved:\n{path}": "Configurazione job training salvata:\n{path}",
    "Select a dataset export to check training prerequisites.": (
        "Seleziona un export dataset per controllare i prerequisiti training."
    ),
    "No training jobs configured.": "Nessun job training configurato.",
    "Save a training config from Setup first.": "Salva prima una configurazione training da Setup.",
    "No training job selected.": "Nessun job training selezionato.",
    "Selected job config:\n{path}": "Configurazione job selezionata:\n{path}",
    "Voice Training": "Voice Training",
    "Start voice training": "Avvia training voce",
    "This will start XTTS-v2 fine-tuning in the ML runtime and can take a long time.\n\nContinue?": (
        "Questo avvierà il fine-tuning XTTS-v2 nel runtime ML e può richiedere molto tempo.\n\nContinuare?"
    ),
    "Starting dry run...": "Avvio dry run...",
    "Starting training...": "Avvio training...",
    "Dry run completed.": "Dry run completato.",
    "Training completed.": "Training completato.",
    "Voice Training CUDA failed": "CUDA Voice Training fallita",
    "Voice training failed in the CUDA runtime.\n\nSwitch this job to CPU and retry?": (
        "Voice training è fallito nel runtime CUDA.\n\nPassare questo job a CPU e riprovare?"
    ),
    "Could not switch the training job to CPU.\n\n{message}": (
        "Impossibile passare il job training a CPU.\n\n{message}"
    ),
    "Job switched to CPU. Retrying...": "Job passato a CPU. Riprovo...",
    "TTS requires internet. Local voice tools are grouped under Local Voices.": (
        "TTS richiede internet. Gli strumenti per voci locali sono in Voci locali."
    ),
    "Search voice, locale or style": "Cerca voce, locale o stile",
    "Create a ready reference profile in Local Voices > Profiles.": (
        "Crea un profilo di riferimento pronto in Voci locali > Profili."
    ),
    "XTTS-v2 model ready.": "Modello XTTS-v2 pronto.",
    "Select a block to preview the text.": "Seleziona un blocco per vedere il testo.",
    "Paste or load the exact text read in this clip. Max 450 characters.": (
        "Incolla o carica il testo esatto letto in questa clip. Massimo 450 caratteri."
    ),
    "0/450 characters for guided recording": "0/450 caratteri per registrazione guidata",
    "Checking STT offline package...": "Controllo pacchetto STT offline...",
    "Remove this change": "Rimuovi questa modifica",
    "Move frame review one frame left": "Sposta la revisione frame di un frame a sinistra",
    "Move frame review one frame right": "Sposta la revisione frame di un frame a destra",
    "Review this frame before marking it manually.": "Rivedi questo frame prima di marcarlo manualmente.",
    "Ready.": "Pronto.",
    "Error.": "Errore.",
    "Cancelled.": "Annullato.",
    "Done.": "Completato.",
    "Ready": "Pronto",
    "Press Start when you are ready.": "Premi Inizio quando sei pronto.",
    "Recording starts soon.": "La registrazione inizierà tra poco.",
    "Ascolta": "Ascolta",
    "Mantieni": "Mantieni",
    "Ritenta": "Ritenta",
    "Annulla": "Annulla",
}


def normalize_ui_language(value: Any) -> str:
    return value if isinstance(value, str) and value in UI_LANGUAGES else DEFAULT_UI_LANGUAGE


def ui_language_name(language_code: str) -> str:
    return UI_LANGUAGES[normalize_ui_language(language_code)]


def translate_static_ui_text(text: str, language_code: str = DEFAULT_UI_LANGUAGE) -> str:
    if normalize_ui_language(language_code) != UI_LANGUAGE_IT:
        return text
    return STATIC_TEXT_TRANSLATIONS_IT.get(text, text)


def translate_ui(key: str, language_code: str = DEFAULT_UI_LANGUAGE, **kwargs: Any) -> str:
    language = normalize_ui_language(language_code)
    template = TRANSLATIONS.get(language, {}).get(key) or TRANSLATIONS[DEFAULT_UI_LANGUAGE].get(key) or key
    if not kwargs:
        return template
    return template.format(**kwargs)
