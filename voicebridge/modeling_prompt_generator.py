from dataclasses import dataclass
from math import gcd
from typing import TypedDict

from voicebridge.languages import normalize_language_code
from voicebridge.voice_profiles import VOICE_PROFILE_LANGUAGES

MODELING_PROMPT_CORPUS_VERSION = "1.2"
MODELING_PROMPT_SOURCE_GENERATED = f"generated_prompt:{MODELING_PROMPT_CORPUS_VERSION}"
MODELING_PROMPT_SOURCE_PROVIDED = "provided_text"
MODELING_PROMPT_DEFAULT_MAX_CHARS = 450
NO_UNUSED_MODELING_PROMPTS_MESSAGE = (
    "No unused guided prompts are available for this dataset. "
    "Add custom text, upload a script, or reset guided prompt history."
)


class ModelingPromptCorpus(TypedDict):
    short: tuple[str, ...]
    medium: tuple[str, ...]
    question: tuple[str, ...]
    numbers: tuple[str, ...]
    names: tuple[str, ...]
    punctuation: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedModelingPrompt:
    text: str
    language_code: str
    corpus_version: str
    source: str


class NoUnusedModelingPromptError(ValueError):
    pass


PROMPT_SLOT_ORDER = ("short", "medium", "question", "numbers", "names", "punctuation")
PROMPT_SLOT_STRIDE_DIGITS = (1, 3, 5, 7, 11, 13)

MODELING_PROMPT_CORPUS: dict[str, ModelingPromptCorpus] = {
    "it": {
        "short": (
            "La luce cambia piano, ma la voce resta calma.",
            "Apro la finestra e preparo il tavolo con cura.",
            "Il pomeriggio scorre leggero tra una pausa e l'altra.",
        ),
        "medium": (
            "Quando il percorso diventa lungo, scelgo un passo regolare e continuo senza fretta.",
            "Una frase chiara aiuta chi ascolta a seguire il ritmo naturale del discorso.",
            "Oggi descrivo piccoli dettagli, alternando parole comuni e suoni meno abituali.",
        ),
        "question": (
            "Hai controllato se il testo è completo prima di registrare?",
            "Possiamo ripetere questa parte con lo stesso tono e la stessa distanza dal microfono?",
            "Ti sembra più naturale fare una pausa breve dopo la domanda?",
        ),
        "numbers": (
            "Nel cassetto ci sono 3 matite, 12 fogli e 24 etichette ordinate.",
            "La lettura dura circa 30 secondi, non 10 e non 90.",
            "Alle 8:15 preparo una nota breve, poi ne leggo altre 2.",
        ),
        "names": (
            "Marco e Lina osservano il giardino mentre Paolo riordina le sedie.",
            "Sara, Elena e Davide scelgono parole semplici per spiegare l'idea.",
            "Nora aspetta Giulio vicino alla porta, poi rientra con calma.",
        ),
        "punctuation": (
            "Bene, procediamo con calma! Poi fermiamoci un momento.",
            "Prima leggo la frase; dopo controllo il respiro, il ritmo e la chiarezza.",
            "Attenzione: il volume deve restare stabile, senza forzare la voce.",
        ),
    },
    "en": {
        "short": (
            "The room is quiet, and the voice stays steady.",
            "I open the notebook and read the next line.",
            "A calm pace makes every word easier to follow.",
        ),
        "medium": (
            "When the passage becomes longer, I keep a steady rhythm and breathe naturally.",
            "Clear speech helps the listener follow each idea without effort.",
            "Today I describe simple details with common words and a few less familiar sounds.",
        ),
        "question": (
            "Did you check that the script matches the audio before saving it?",
            "Can we repeat this sentence with the same tone and microphone distance?",
            "Does a short pause after the question sound more natural?",
        ),
        "numbers": (
            "On the desk there are 3 pencils, 12 pages, and 24 small labels.",
            "This reading should take about 30 seconds, not 10 and not 90.",
            "At 8:15 I prepare one short note, then I read 2 more.",
        ),
        "names": (
            "Marta and Daniel watch the garden while Nora arranges the chairs.",
            "Julia, Ethan, and Clara choose plain words to explain the idea.",
            "Leo waits near the door, then walks back inside without hurry.",
        ),
        "punctuation": (
            "Good, let us continue calmly! Then we can stop for a moment.",
            "First I read the line; after that I check breath, rhythm, and clarity.",
            "Note: the volume should stay even, without pushing the voice.",
        ),
    },
    "es": {
        "short": (
            "La sala está tranquila y la voz se mantiene firme.",
            "Abro el cuaderno y leo la siguiente línea con calma.",
            "Un ritmo sereno ayuda a entender cada palabra.",
        ),
        "medium": (
            "Cuando el texto se hace más largo, mantengo una cadencia regular y respiro sin prisa.",
            "Una voz clara permite seguir cada idea sin esfuerzo.",
            "Hoy describo detalles sencillos con palabras comunes y algunos sonidos menos frecuentes.",
        ),
        "question": (
            "¿Has comprobado que el texto coincide con el audio antes de guardarlo?",
            "¿Podemos repetir esta frase con el mismo tono y la misma distancia al micrófono?",
            "¿Suena más natural hacer una pausa breve después de la pregunta?",
        ),
        "numbers": (
            "En la mesa hay 3 lápices, 12 hojas y 24 etiquetas pequeñas.",
            "La lectura debe durar unos 30 segundos, no 10 y no 90.",
            "A las 8:15 preparo una nota corta y después leo otras 2.",
        ),
        "names": (
            "Marta y Daniel miran el jardín mientras Nora ordena las sillas.",
            "Julia, Mateo y Clara eligen palabras simples para explicar la idea.",
            "Leo espera junto a la puerta y luego vuelve despacio.",
        ),
        "punctuation": (
            "¡Bien, seguimos con calma! Luego paramos un momento.",
            "Primero leo la frase; después reviso la respiración, el ritmo y la claridad.",
            "Nota: el volumen debe mantenerse estable, sin forzar la voz.",
        ),
    },
    "fr": {
        "short": (
            "La pièce est calme et la voix reste régulière.",
            "J'ouvre le carnet et je lis la ligne suivante.",
            "Un rythme posé rend chaque mot plus clair.",
        ),
        "medium": (
            "Quand le passage devient plus long, je garde une cadence simple et je respire naturellement.",
            "Une parole nette aide l'auditeur à suivre chaque idée sans effort.",
            "Aujourd'hui je décris des détails ordinaires avec des mots courants et quelques sons moins habituels.",
        ),
        "question": (
            "As-tu vérifié que le texte correspond bien à l'audio avant de l'enregistrer?",
            "Pouvons-nous répéter cette phrase avec le même ton et la même distance du micro?",
            "Une courte pause après la question semble-t-elle plus naturelle?",
        ),
        "numbers": (
            "Sur la table il y a 3 crayons, 12 feuilles et 24 petites étiquettes.",
            "Cette lecture doit durer environ 30 secondes, pas 10 et pas 90.",
            "À 8:15 je prépare une note courte, puis j'en lis 2 autres.",
        ),
        "names": (
            "Marta et Daniel regardent le jardin pendant que Nora range les chaises.",
            "Julie, Mateo et Claire choisissent des mots simples pour expliquer l'idée.",
            "Leo attend près de la porte, puis il rentre tranquillement.",
        ),
        "punctuation": (
            "Bien, continuons calmement ! Ensuite nous faisons une pause.",
            "D'abord je lis la phrase; ensuite je contrôle le souffle, le rythme et la clarté.",
            "Note: le volume doit rester stable, sans forcer la voix.",
        ),
    },
    "de": {
        "short": (
            "Der Raum ist ruhig, und die Stimme bleibt gleichmäßig.",
            "Ich öffne das Heft und lese die nächste Zeile.",
            "Ein ruhiges Tempo macht jedes Wort klarer.",
        ),
        "medium": (
            "Wenn der Abschnitt länger wird, halte ich einen regelmäßigen Rhythmus und atme natürlich.",
            "Deutliche Sprache hilft beim Folgen jeder Idee ohne Anstrengung.",
            "Heute beschreibe ich einfache Details mit häufigen Wörtern und einigen selteneren Lauten.",
        ),
        "question": (
            "Hast du geprüft, ob der Text vor dem Speichern zum Audio passt?",
            "Können wir diesen Satz mit gleichem Ton und gleichem Mikrofonabstand wiederholen?",
            "Klingt eine kurze Pause nach der Frage natürlicher?",
        ),
        "numbers": (
            "Auf dem Tisch liegen 3 Stifte, 12 Blätter und 24 kleine Etiketten.",
            "Diese Aufnahme soll etwa 30 Sekunden dauern, nicht 10 und nicht 90.",
            "Um 8:15 schreibe ich eine kurze Notiz und lese danach 2 weitere.",
        ),
        "names": (
            "Marta und Daniel sehen in den Garten, während Nora die Stühle ordnet.",
            "Julia, Mateo und Clara wählen einfache Worte, um die Idee zu erklären.",
            "Leo wartet an der Tür und geht dann langsam wieder hinein.",
        ),
        "punctuation": (
            "Gut, wir machen ruhig weiter! Danach halten wir kurz an.",
            "Zuerst lese ich den Satz; danach prüfe ich Atem, Rhythmus und Klarheit.",
            "Hinweis: Die Lautstärke soll stabil bleiben, ohne die Stimme zu drücken.",
        ),
    },
    "pt": {
        "short": (
            "A sala está calma e a voz permanece estável.",
            "Abro o caderno e leio a próxima linha devagar.",
            "Um ritmo tranquilo ajuda cada palavra a ficar clara.",
        ),
        "medium": (
            "Quando o trecho fica mais longo, mantenho uma cadência regular e respiro naturalmente.",
            "Uma fala clara ajuda quem escuta a acompanhar cada ideia sem esforço.",
            "Hoje descrevo detalhes simples com palavras comuns e alguns sons menos frequentes.",
        ),
        "question": (
            "Você conferiu se o texto combina com o áudio antes de salvar?",
            "Podemos repetir esta frase com o mesmo tom e a mesma distância do microfone?",
            "Uma pausa curta depois da pergunta soa mais natural?",
        ),
        "numbers": (
            "Na mesa há 3 lápis, 12 folhas e 24 etiquetas pequenas.",
            "Esta leitura deve durar cerca de 30 segundos, não 10 e não 90.",
            "Às 8:15 preparo uma nota curta e depois leio mais 2.",
        ),
        "names": (
            "Marta e Daniel olham o jardim enquanto Nora organiza as cadeiras.",
            "Julia, Mateo e Clara escolhem palavras simples para explicar a ideia.",
            "Leo espera perto da porta e depois volta sem pressa.",
        ),
        "punctuation": (
            "Certo, vamos continuar com calma! Depois paramos um momento.",
            "Primeiro leio a frase; depois verifico respiração, ritmo e clareza.",
            "Nota: o volume deve ficar estável, sem forçar a voz.",
        ),
    },
    "pl": {
        "short": (
            "Pokój jest cichy, a głos pozostaje równy.",
            "Otwieram notes i czytam następne zdanie spokojnie.",
            "Spokojne tempo pomaga wyraźnie wypowiedzieć każde słowo.",
        ),
        "medium": (
            "Kiedy fragment staje się dłuższy, utrzymuję równy rytm i oddycham naturalnie.",
            "Wyraźna mowa pomaga słuchaczowi bez wysiłku śledzić każdą myśl.",
            "Dziś opisuję proste szczegóły, używając codziennych słów i kilku rzadszych dźwięków.",
        ),
        "question": (
            "Czy sprawdzono, że tekst zgadza się z nagraniem przed zapisaniem?",
            "Czy możemy powtórzyć to zdanie tym samym tonem i z tej samej odległości od mikrofonu?",
            "Czy krótka pauza po pytaniu brzmi bardziej naturalnie?",
        ),
        "numbers": (
            "Na biurku są 3 ołówki, 12 kartek i 24 małe etykiety.",
            "To czytanie powinno trwać około 30 sekund, nie 10 i nie 90.",
            "O 8:15 przygotowuję krótką notatkę, potem czytam jeszcze 2.",
        ),
        "names": (
            "Marta i Daniel patrzą na ogród, a Nora ustawia krzesła.",
            "Julia, Mateusz i Klara wybierają proste słowa, aby wyjaśnić pomysł.",
            "Leo czeka przy drzwiach, a potem wraca spokojnym krokiem.",
        ),
        "punctuation": (
            "Dobrze, kontynuujmy spokojnie! Potem zatrzymamy się na chwilę.",
            "Najpierw czytam zdanie; potem sprawdzam oddech, rytm i wyrazistość.",
            "Uwaga: głośność powinna być stała, bez napinania głosu.",
        ),
    },
    "tr": {
        "short": (
            "Oda sessiz ve ses dengeli kalıyor.",
            "Defteri açıp sonraki satırı sakin bir tempoyla okuyorum.",
            "Yumuşak bir ritim her kelimeyi daha anlaşılır yapar.",
        ),
        "medium": (
            "Metin uzadığında düzenli bir ritim tutar ve doğal şekilde nefes alırım.",
            "Açık konuşma, dinleyenin her fikri zorlanmadan takip etmesine yardım eder.",
            "Bugün basit ayrıntıları, yaygın kelimeler ve birkaç farklı sesle anlatıyorum.",
        ),
        "question": (
            "Kaydetmeden önce metnin sesle eşleştiğini kontrol ettin mi?",
            "Bu cümleyi aynı tonla ve mikrofona aynı uzaklıkta tekrar edebilir miyiz?",
            "Sorudan sonra kısa bir duraklama daha doğal geliyor mu?",
        ),
        "numbers": (
            "Masada 3 kalem, 12 sayfa ve 24 küçük etiket var.",
            "Bu okuma yaklaşık 30 saniye sürmeli, 10 değil ve 90 değil.",
            "Saat 8:15'te kısa bir not hazırlarım, sonra 2 tane daha okurum.",
        ),
        "names": (
            "Marta ve Daniel bahçeye bakarken Nora sandalyeleri düzenler.",
            "Julia, Mete ve Clara fikri anlatmak için sade kelimeler seçer.",
            "Leo kapının yanında bekler, sonra sakince içeri döner.",
        ),
        "punctuation": (
            "Güzel, sakin şekilde devam edelim! Sonra kısa bir mola verelim.",
            "Önce cümleyi okurum; sonra nefesi, ritmi ve açıklığı kontrol ederim.",
            "Not: Ses seviyesi sabit kalmalı, sesi zorlamamalıyız.",
        ),
    },
    "ru": {
        "short": (
            "В комнате тихо, и голос остается ровным.",
            "Я открываю блокнот и спокойно читаю следующую строку.",
            "Спокойный темп помогает каждому слову звучать ясно.",
        ),
        "medium": (
            "Когда отрывок становится длиннее, я сохраняю ровный ритм и дышу естественно.",
            "Четкая речь помогает слушателю легко следить за каждой мыслью.",
            "Сегодня я описываю простые детали обычными словами и несколькими редкими звуками.",
        ),
        "question": (
            "Ты проверил, что текст совпадает с аудио перед сохранением?",
            "Можем повторить эту фразу тем же тоном и с тем же расстоянием до микрофона?",
            "Короткая пауза после вопроса звучит естественнее?",
        ),
        "numbers": (
            "На столе лежат 3 карандаша, 12 листов и 24 маленькие метки.",
            "Это чтение должно занять около 30 секунд, не 10 и не 90.",
            "В 8:15 я готовлю короткую заметку, потом читаю еще 2.",
        ),
        "names": (
            "Марта и Даниил смотрят в сад, пока Нора расставляет стулья.",
            "Юлия, Матвей и Клара выбирают простые слова, чтобы объяснить идею.",
            "Лео ждет у двери, а затем спокойно возвращается внутрь.",
        ),
        "punctuation": (
            "Хорошо, продолжаем спокойно! Затем остановимся на минуту.",
            "Сначала я читаю фразу; потом проверяю дыхание, ритм и четкость.",
            "Важно: громкость должна оставаться ровной, без напряжения голоса.",
        ),
    },
    "nl": {
        "short": (
            "De kamer is rustig en de stem blijft gelijkmatig.",
            "Ik open het schrift en lees de volgende regel kalm.",
            "Een rustig tempo maakt elk woord duidelijker.",
        ),
        "medium": (
            "Wanneer de tekst langer wordt, houd ik een regelmatig ritme aan en adem ik natuurlijk.",
            "Heldere spraak helpt de luisteraar elke gedachte zonder moeite te volgen.",
            "Vandaag beschrijf ik gewone details met bekende woorden en enkele minder bekende klanken.",
        ),
        "question": (
            "Heb je gecontroleerd of de tekst met de audio overeenkomt voor het opslaan?",
            "Kunnen we deze zin herhalen met dezelfde toon en dezelfde afstand tot de microfoon?",
            "Klinkt een korte pauze na de vraag natuurlijker?",
        ),
        "numbers": (
            "Op tafel liggen 3 potloden, 12 vellen en 24 kleine labels.",
            "Deze lezing duurt ongeveer 30 seconden, niet 10 en niet 90.",
            "Om 8:15 maak ik een korte notitie en daarna lees ik er nog 2.",
        ),
        "names": (
            "Marta en Daniel kijken naar de tuin terwijl Nora de stoelen rechtzet.",
            "Julia, Mateo en Clara kiezen eenvoudige woorden om het idee uit te leggen.",
            "Leo wacht bij de deur en loopt daarna rustig naar binnen.",
        ),
        "punctuation": (
            "Goed, we gaan rustig verder! Daarna stoppen we even.",
            "Eerst lees ik de zin; daarna controleer ik adem, ritme en helderheid.",
            "Let op: het volume moet stabiel blijven, zonder de stem te forceren.",
        ),
    },
    "cs": {
        "short": (
            "Místnost je tichá a hlas zůstává vyrovnaný.",
            "Otevírám zápisník a klidně čtu další řádek.",
            "Klidné tempo pomáhá vyslovit každé slovo jasně.",
        ),
        "medium": (
            "Když je odstavec delší, držím pravidelný rytmus a dýchám přirozeně.",
            "Zřetelná řeč pomáhá posluchači sledovat každou myšlenku bez námahy.",
            "Dnes popisuji jednoduché detaily běžnými slovy a několika méně obvyklými zvuky.",
        ),
        "question": (
            "Zkontroloval jsi před uložením, že text odpovídá nahrávce?",
            "Můžeme tuto větu zopakovat stejným tónem a ze stejné vzdálenosti od mikrofonu?",
            "Zní krátká pauza po otázce přirozeněji?",
        ),
        "numbers": (
            "Na stole jsou 3 tužky, 12 listů a 24 malých štítků.",
            "Toto čtení má trvat asi 30 sekund, ne 10 a ne 90.",
            "V 8:15 připravím krátkou poznámku a pak přečtu ještě 2.",
        ),
        "names": (
            "Marta a Daniel se dívají do zahrady, zatímco Nora rovná židle.",
            "Julie, Matěj a Klára volí jednoduchá slova, aby vysvětlili nápad.",
            "Leo čeká u dveří a potom se klidně vrací dovnitř.",
        ),
        "punctuation": (
            "Dobře, pokračujme v klidu! Potom se na chvíli zastavíme.",
            "Nejprve přečtu větu; potom zkontroluji dech, rytmus a zřetelnost.",
            "Poznámka: hlasitost má zůstat stabilní, bez tlačení na hlas.",
        ),
    },
    "ar": {
        "short": (
            "الغرفة هادئة، والصوت يبقى ثابتا وواضحا.",
            "أفتح الدفتر وأقرأ السطر التالي بهدوء.",
            "الإيقاع الهادئ يجعل كل كلمة أسهل للفهم.",
        ),
        "medium": (
            "عندما يطول النص، أحافظ على إيقاع منتظم وأتنفس بطريقة طبيعية.",
            "الكلام الواضح يساعد المستمع على متابعة كل فكرة بدون جهد.",
            "اليوم أصف تفاصيل بسيطة بكلمات مألوفة وبعض الأصوات الأقل شيوعا.",
        ),
        "question": (
            "هل تأكدت من أن النص يطابق الصوت قبل الحفظ؟",
            "هل يمكن أن نعيد هذه الجملة بنفس النبرة ونفس المسافة من الميكروفون؟",
            "هل تبدو الوقفة القصيرة بعد السؤال أكثر طبيعية؟",
        ),
        "numbers": (
            "على الطاولة 3 أقلام و12 ورقة و24 بطاقة صغيرة.",
            "يجب أن تستغرق القراءة حوالي 30 ثانية، لا 10 ولا 90.",
            "في الساعة 8:15 أجهز ملاحظة قصيرة، ثم أقرأ 2 أخريين.",
        ),
        "names": (
            "مارتا ودانيال ينظران إلى الحديقة بينما ترتب نورا الكراسي.",
            "جوليا وماتيو وكلارا يختارون كلمات بسيطة لشرح الفكرة.",
            "ليو ينتظر قرب الباب، ثم يعود إلى الداخل بهدوء.",
        ),
        "punctuation": (
            "حسنا، نتابع بهدوء! ثم نتوقف لحظة قصيرة.",
            "أولا أقرأ الجملة؛ ثم أراجع التنفس والإيقاع والوضوح.",
            "ملاحظة: يجب أن يبقى مستوى الصوت ثابتا، بدون ضغط على الصوت.",
        ),
    },
    "zh-cn": {
        "short": (
            "房间很安静，声音保持平稳清楚。",
            "我打开笔记本，慢慢读下一行。",
            "稳定的节奏让每个词更容易听懂。",
        ),
        "medium": (
            "当文字变长时，我保持自然呼吸，并用均匀的速度朗读。",
            "清楚的表达可以帮助听众轻松跟上每一个想法。",
            "今天我描述一些简单细节，使用常见词语和少量不常见的发音。",
        ),
        "question": (
            "保存之前，你确认文字和录音完全一致了吗？",
            "我们可以用同样的语气和同样的麦克风距离再读一次吗？",
            "问题后面稍微停顿一下，听起来会不会更自然？",
        ),
        "numbers": (
            "桌上有3支铅笔、12张纸和24个小标签。",
            "这段朗读大约需要30秒，不是10秒，也不是90秒。",
            "8:15的时候，我准备一条短笔记，然后再读2条。",
        ),
        "names": (
            "玛塔和丹尼尔看着花园，诺拉在整理椅子。",
            "朱莉娅、马特奥和克拉拉选择简单的话来说明想法。",
            "利奥在门口等了一会儿，然后平静地走回屋里。",
        ),
        "punctuation": (
            "很好，我们继续慢慢读！然后停一下。",
            "我先读句子；然后检查呼吸、节奏和清晰度。",
            "注意：音量应该保持稳定，不要用力压嗓子。",
        ),
    },
    "ja": {
        "short": (
            "部屋は静かで、声は落ち着いています。",
            "ノートを開いて、次の行をゆっくり読みます。",
            "安定したリズムは、言葉を聞き取りやすくします。",
        ),
        "medium": (
            "文章が長くなっても、自然に息をしながら一定の速さで読みます。",
            "はっきりした話し方は、聞く人が考えを追いやすくします。",
            "今日は、身近な言葉と少し珍しい音を使って、簡単な様子を説明します。",
        ),
        "question": (
            "保存する前に、文章と録音が同じだと確認しましたか？",
            "同じ声の高さと同じマイクの距離で、もう一度読めますか？",
            "質問のあとに短く止まると、より自然に聞こえますか？",
        ),
        "numbers": (
            "机の上には3本の鉛筆、12枚の紙、24個の小さな札があります。",
            "この読み上げは約30秒で、10秒でも90秒でもありません。",
            "8:15に短いメモを用意して、そのあと2つ読みます。",
        ),
        "names": (
            "マルタとダニエルが庭を見ている間、ノラは椅子を整えます。",
            "ジュリア、マテオ、クララは、考えを伝えるために簡単な言葉を選びます。",
            "レオはドアの近くで待ち、それから静かに中へ戻ります。",
        ),
        "punctuation": (
            "よし、落ち着いて続けましょう！そのあと少し止まります。",
            "まず文を読みます；それから息、リズム、明瞭さを確認します。",
            "注意：音量は安定させ、声を無理に押し出さないようにします。",
        ),
    },
    "hu": {
        "short": (
            "A szoba csendes, és a hang egyenletes marad.",
            "Kinyitom a füzetet, és nyugodtan olvasom a következő sort.",
            "A lassú, biztos tempó minden szót érthetőbbé tesz.",
        ),
        "medium": (
            "Amikor a szöveg hosszabb lesz, tartom az egyenletes ritmust és természetesen lélegzem.",
            "A tiszta beszéd segít a hallgatónak követni minden gondolatot.",
            "Ma egyszerű részleteket írok le gyakori szavakkal és néhány ritkább hanggal.",
        ),
        "question": (
            "Ellenőrizted, hogy a szöveg megegyezik a hanggal mentés előtt?",
            "Meg tudjuk ismételni ezt a mondatot ugyanazzal a hangszínnel és mikrofontávolsággal?",
            "Természetesebben hangzik egy rövid szünet a kérdés után?",
        ),
        "numbers": (
            "Az asztalon 3 ceruza, 12 lap és 24 kis címke van.",
            "Ez a felolvasás körülbelül 30 másodpercig tart, nem 10 és nem 90.",
            "8:15-kor készítek egy rövid jegyzetet, majd még 2-t felolvasok.",
        ),
        "names": (
            "Márta és Dániel a kertet nézik, miközben Nóra elrendezi a székeket.",
            "Júlia, Máté és Klára egyszerű szavakat választ az ötlet magyarázatához.",
            "Leó az ajtó mellett vár, aztán nyugodtan visszamegy.",
        ),
        "punctuation": (
            "Rendben, folytassuk nyugodtan! Utána megállunk egy pillanatra.",
            "Először felolvasom a mondatot; utána figyelem a légzést, a ritmust és a tisztaságot.",
            "Megjegyzés: a hangerőnek stabilnak kell maradnia, erőltetés nélkül.",
        ),
    },
    "ko": {
        "short": (
            "방은 조용하고 목소리는 고르게 유지됩니다.",
            "공책을 열고 다음 줄을 천천히 읽습니다.",
            "차분한 속도는 모든 단어를 더 분명하게 만듭니다.",
        ),
        "medium": (
            "문장이 길어질 때도 자연스럽게 숨을 쉬며 일정한 리듬을 유지합니다.",
            "분명한 말하기는 듣는 사람이 각 생각을 쉽게 따라가도록 돕습니다.",
            "오늘은 익숙한 단어와 조금 다른 소리를 섞어 간단한 장면을 설명합니다.",
        ),
        "question": (
            "저장하기 전에 글과 녹음이 서로 맞는지 확인했나요?",
            "같은 톤과 같은 마이크 거리로 이 문장을 다시 읽을 수 있을까요?",
            "질문 뒤에 짧게 쉬면 더 자연스럽게 들리나요?",
        ),
        "numbers": (
            "책상 위에는 연필 3개, 종이 12장, 작은 라벨 24개가 있습니다.",
            "이 읽기는 약 30초가 걸려야 하며, 10초도 90초도 아닙니다.",
            "8:15에 짧은 메모를 준비하고, 그다음 2개를 더 읽습니다.",
        ),
        "names": (
            "마르타와 다니엘이 정원을 보는 동안 노라는 의자를 정리합니다.",
            "줄리아, 마테오, 클라라는 생각을 설명하려고 쉬운 단어를 고릅니다.",
            "레오는 문 근처에서 기다린 뒤 천천히 안으로 돌아갑니다.",
        ),
        "punctuation": (
            "좋습니다, 차분하게 계속합시다! 그런 다음 잠시 멈춥니다.",
            "먼저 문장을 읽고; 그다음 호흡, 리듬, 또렷함을 확인합니다.",
            "참고: 목소리를 억지로 내지 말고 음량을 일정하게 유지합니다.",
        ),
    },
    "hi": {
        "short": (
            "कमरा शांत है, और आवाज़ स्थिर रहती है।",
            "मैं नोटबुक खोलता हूं और अगली पंक्ति धीरे पढ़ता हूं।",
            "संतुलित गति हर शब्द को साफ बनाती है।",
        ),
        "medium": (
            "जब वाक्य लंबा हो जाता है, मैं समान लय रखता हूं और स्वाभाविक सांस लेता हूं।",
            "स्पष्ट बोलने से सुनने वाला हर विचार आसानी से समझ पाता है।",
            "आज मैं सामान्य शब्दों और कुछ अलग ध्वनियों से छोटे विवरण बताता हूं।",
        ),
        "question": (
            "क्या आपने सेव करने से पहले जांचा कि पाठ और ऑडियो समान हैं?",
            "क्या हम इस वाक्य को उसी स्वर और उसी माइक्रोफोन दूरी से दोहरा सकते हैं?",
            "क्या प्रश्न के बाद छोटी रुकावट अधिक स्वाभाविक लगती है?",
        ),
        "numbers": (
            "मेज पर 3 पेंसिल, 12 पन्ने और 24 छोटे लेबल रखे हैं।",
            "यह पाठ लगभग 30 सेकंड का होना चाहिए, 10 नहीं और 90 नहीं।",
            "8:15 पर मैं एक छोटी नोट तैयार करता हूं, फिर 2 और पढ़ता हूं।",
        ),
        "names": (
            "मार्टा और डैनियल बगीचे को देखते हैं, जबकि नोरा कुर्सियां ठीक करती है।",
            "जूलिया, मातेओ और क्लारा विचार समझाने के लिए सरल शब्द चुनते हैं।",
            "लियो दरवाजे के पास इंतजार करता है, फिर धीरे से अंदर लौटता है।",
        ),
        "punctuation": (
            "ठीक है, हम शांति से जारी रखते हैं! फिर थोड़ी देर रुकते हैं।",
            "पहले मैं वाक्य पढ़ता हूं; फिर सांस, लय और स्पष्टता देखता हूं।",
            "ध्यान दें: आवाज़ का स्तर स्थिर रहना चाहिए, बिना जोर लगाए।",
        ),
    },
}

MODELING_PROMPT_CORPUS_EXTENSIONS: dict[str, ModelingPromptCorpus] = {
    "it": {
        "short": (
            "La tazza resta sul ripiano mentre preparo la stanza.",
            "Cammino piano e mantengo la stessa distanza dal microfono.",
            "Il quaderno contiene appunti brevi e ordinati.",
            "La voce resta morbida anche quando la frase accelera.",
            "Chiudo la porta senza rumore e riprendo a leggere.",
        ),
        "medium": (
            "Ogni registrazione dovrebbe avere un inizio pulito, una frase completa e una chiusura senza rumori.",
            "Se una parola sembra difficile, la pronuncio con naturalezza invece di alzare troppo il volume.",
            "Il testo alterna descrizioni semplici, piccole azioni quotidiane e cambi di ritmo controllati.",
            "Una pausa breve tra due idee rende il parlato più chiaro senza sembrare artificiale.",
            "Leggo con attenzione, ma lascio alla voce un movimento leggero e spontaneo.",
        ),
        "question": (
            "Vuoi ripetere la frase se senti un colpo di tosse o un fruscio?",
            "Questa intonazione sembra adatta a un racconto semplice?",
            "Hai lasciato abbastanza silenzio prima di iniziare a parlare?",
            "Possiamo rendere l'ultima parola chiara senza esagerare?",
            "Il ritmo è costante anche quando la frase diventa più lunga?",
        ),
        "numbers": (
            "Sul calendario segno 4 incontri, 18 minuti di prova e 32 righe lette.",
            "Il volume resta vicino al 70%, mentre la distanza è circa 20 centimetri.",
            "Preparo 5 schede, ne scarto 1 e tengo 14 esempi utili.",
            "La seconda clip dura 42 secondi e contiene 6 pause naturali.",
            "Alle 9:30 registro 3 frasi brevi e 2 frasi più lunghe.",
        ),
        "names": (
            "Irene ascolta Matteo, poi chiede a Bianca di controllare il testo.",
            "Luca, Gianni e Serena leggono a turno senza cambiare tono.",
            "Elisa incontra Fabio davanti alla libreria e gli passa una cartellina.",
            "Roberto saluta Anna, sistema il microfono e riprova la frase.",
            "Chiara e Simone scelgono un esempio chiaro per il nuovo dataset.",
        ),
        "punctuation": (
            "Ottimo: la frase è breve, chiara e ben scandita.",
            "Aspetta un secondo, respira, poi continua con naturalezza.",
            "Non serve correre; meglio leggere bene, con calma.",
            "Se il rumore aumenta, fermati! Riprendi solo quando la stanza è silenziosa.",
            "Nota bene: la punteggiatura guida il ritmo, non deve essere letta come testo.",
        ),
    },
    "en": {
        "short": (
            "The cup stays on the shelf while I prepare the room.",
            "I walk slowly and keep the same distance from the microphone.",
            "The notebook holds short and orderly notes.",
            "The voice stays soft even when the sentence moves faster.",
            "I close the door quietly and start reading again.",
        ),
        "medium": (
            "Each recording should have a clean start, a complete sentence, and an ending without noise.",
            "If a word feels difficult, I say it naturally instead of raising the volume too much.",
            "The script alternates simple descriptions, everyday actions, and controlled changes of rhythm.",
            "A short pause between two ideas makes speech clearer without sounding artificial.",
            "I read with care, while allowing the voice to move lightly and naturally.",
        ),
        "question": (
            "Do you want to repeat the line if you hear a cough or a rustle?",
            "Does this tone fit a simple spoken story?",
            "Did you leave enough silence before starting to speak?",
            "Can we make the final word clear without exaggerating it?",
            "Does the rhythm stay steady when the sentence becomes longer?",
        ),
        "numbers": (
            "On the calendar I mark 4 meetings, 18 minutes of testing, and 32 lines read.",
            "The volume stays near 70%, and the distance is about 20 centimeters.",
            "I prepare 5 cards, discard 1, and keep 14 useful examples.",
            "The second clip lasts 42 seconds and includes 6 natural pauses.",
            "At 9:30 I record 3 short lines and 2 longer ones.",
        ),
        "names": (
            "Irene listens to Mateo, then asks Bianca to check the text.",
            "Luca, Gianni, and Serena read in turns without changing tone.",
            "Elisa meets Fabio by the bookcase and hands him a folder.",
            "Robert greets Anna, adjusts the microphone, and tries the line again.",
            "Clara and Simon choose a clear example for the new dataset.",
        ),
        "punctuation": (
            "Excellent: the sentence is short, clear, and well paced.",
            "Wait one second, breathe, then continue naturally.",
            "There is no need to rush; it is better to read clearly and calmly.",
            "If the noise increases, stop! Continue only when the room is quiet.",
            "Note: punctuation guides the rhythm, but it should not be read as text.",
        ),
    },
    "es": {
        "short": (
            "La taza queda en la repisa mientras preparo la sala.",
            "Camino despacio y mantengo la misma distancia al micrófono.",
            "El cuaderno guarda notas breves y ordenadas.",
            "La voz sigue suave aunque la frase avance más rápido.",
            "Cierro la puerta sin ruido y vuelvo a leer.",
        ),
        "medium": (
            "Cada grabación debe tener un inicio limpio, una frase completa y un final sin ruidos.",
            "Si una palabra resulta difícil, la digo con naturalidad en lugar de subir mucho el volumen.",
            "El texto alterna descripciones simples, acciones cotidianas y cambios de ritmo controlados.",
            "Una pausa breve entre dos ideas hace que el habla sea más clara sin sonar artificial.",
            "Leo con atención, pero dejo que la voz tenga un movimiento ligero y espontáneo.",
        ),
        "question": (
            "¿Quieres repetir la frase si escuchas una tos o un roce?",
            "¿Este tono sirve para una historia sencilla?",
            "¿Dejaste suficiente silencio antes de empezar a hablar?",
            "¿Podemos hacer que la última palabra sea clara sin exagerarla?",
            "¿El ritmo se mantiene constante cuando la frase se hace más larga?",
        ),
        "numbers": (
            "En el calendario marco 4 reuniones, 18 minutos de prueba y 32 líneas leídas.",
            "El volumen queda cerca del 70%, y la distancia es de unos 20 centímetros.",
            "Preparo 5 tarjetas, descarto 1 y conservo 14 ejemplos útiles.",
            "El segundo clip dura 42 segundos e incluye 6 pausas naturales.",
            "A las 9:30 grabo 3 frases cortas y 2 más largas.",
        ),
        "names": (
            "Irene escucha a Mateo y luego pide a Bianca que revise el texto.",
            "Luca, Gianni y Serena leen por turnos sin cambiar el tono.",
            "Elisa encuentra a Fabio junto a la librería y le entrega una carpeta.",
            "Roberto saluda a Ana, ajusta el micrófono y repite la frase.",
            "Clara y Simón eligen un ejemplo claro para el nuevo dataset.",
        ),
        "punctuation": (
            "Excelente: la frase es breve, clara y bien marcada.",
            "Espera un segundo, respira y luego continúa con naturalidad.",
            "No hace falta correr; es mejor leer bien y con calma.",
            "¡Si aumenta el ruido, detente! Continúa solo cuando la sala esté tranquila.",
            "Nota: la puntuación guía el ritmo, pero no debe leerse como texto.",
        ),
    },
    "fr": {
        "short": (
            "La tasse reste sur l'étagère pendant que je prépare la pièce.",
            "Je marche lentement et je garde la même distance du micro.",
            "Le carnet contient des notes courtes et bien rangées.",
            "La voix reste douce même quand la phrase accélère.",
            "Je ferme la porte sans bruit et je reprends la lecture.",
        ),
        "medium": (
            "Chaque enregistrement doit commencer proprement, contenir une phrase complète et finir sans bruit.",
            "Si un mot semble difficile, je le prononce naturellement au lieu de monter le volume.",
            "Le texte alterne des descriptions simples, des gestes quotidiens et des changements de rythme contrôlés.",
            "Une courte pause entre deux idées rend la parole plus claire sans paraître artificielle.",
            "Je lis avec attention, tout en laissant la voix bouger de façon légère et naturelle.",
        ),
        "question": (
            "Veux-tu répéter la phrase si tu entends une toux ou un froissement?",
            "Ce ton convient-il à une histoire simple?",
            "As-tu laisse assez de silence avant de commencer a parler?",
            "Peut-on rendre le dernier mot clair sans l'exagérer?",
            "Le rythme reste-t-il stable quand la phrase devient plus longue?",
        ),
        "numbers": (
            "Sur le calendrier je note 4 rendez-vous, 18 minutes d'essai et 32 lignes lues.",
            "Le volume reste près de 70%, et la distance est d'environ 20 centimètres.",
            "Je prépare 5 fiches, j'en retire 1 et je garde 14 exemples utiles.",
            "La deuxième clip dure 42 secondes et contient 6 pauses naturelles.",
            "À 9:30 j'enregistre 3 phrases courtes et 2 plus longues.",
        ),
        "names": (
            "Irène écoute Mateo, puis demande à Bianca de vérifier le texte.",
            "Luca, Gianni et Serena lisent a tour de role sans changer de ton.",
            "Elisa retrouve Fabio près de la bibliothèque et lui donne un dossier.",
            "Robert salue Anna, règle le micro et reprend la phrase.",
            "Clara et Simon choisissent un exemple clair pour le nouveau dataset.",
        ),
        "punctuation": (
            "Excellent: la phrase est courte, claire et bien rythmée.",
            "Attends une seconde, respire, puis continue naturellement.",
            "Inutile de se presser; mieux vaut lire clairement et calmement.",
            "Si le bruit augmente, arrête-toi! Reprends seulement quand la pièce est calme.",
            "Note: la ponctuation guide le rythme, mais elle ne doit pas être lue comme du texte.",
        ),
    },
    "de": {
        "short": (
            "Die Tasse bleibt im Regal, während ich den Raum vorbereite.",
            "Ich gehe langsam und halte den gleichen Abstand zum Mikrofon.",
            "Das Heft enthält kurze und geordnete Notizen.",
            "Die Stimme bleibt weich, auch wenn der Satz schneller wird.",
            "Ich schließe die Tür leise und lese weiter.",
        ),
        "medium": (
            "Jede Aufnahme braucht einen sauberen Anfang, einen vollständigen Satz und ein Ende ohne Störgeräusche.",
            "Wenn ein Wort schwierig wirkt, spreche ich es natürlich statt die Lautstärke stark zu erhöhen.",
            "Der Text wechselt einfache Beschreibungen, alltägliche Handlungen und kontrollierte Rhythmuswechsel.",
            "Eine kurze Pause zwischen zwei Gedanken macht die Sprache klarer, ohne künstlich zu klingen.",
            "Ich lese aufmerksam, lasse der Stimme aber eine leichte und natuerliche Bewegung.",
        ),
        "question": (
            "Möchtest du den Satz wiederholen, wenn du Husten oder Rascheln hörst?",
            "Passt dieser Ton zu einer einfachen Erzählung?",
            "Hast du vor dem Sprechen genug Stille gelassen?",
            "Können wir das letzte Wort klar machen, ohne es zu übertreiben?",
            "Bleibt der Rhythmus stabil, wenn der Satz länger wird?",
        ),
        "numbers": (
            "Im Kalender markiere ich 4 Treffen, 18 Minuten Test und 32 gelesene Zeilen.",
            "Die Lautstärke bleibt nahe bei 70%, und der Abstand betraegt etwa 20 Zentimeter.",
            "Ich bereite 5 Karten vor, verwerfe 1 und behalte 14 nützliche Beispiele.",
            "Der zweite Clip dauert 42 Sekunden und enthält 6 natuerliche Pausen.",
            "Um 9:30 nehme ich 3 kurze Sätze und 2 längere auf.",
        ),
        "names": (
            "Irene hört Mateo zu und bittet Bianca dann, den Text zu prüfen.",
            "Luca, Gianni und Serena lesen abwechselnd, ohne den Ton zu ändern.",
            "Elisa trifft Fabio am Bücherregal und gibt ihm eine Mappe.",
            "Robert grüßt Anna, richtet das Mikrofon aus und versucht den Satz erneut.",
            "Clara und Simon wählen ein klares Beispiel für den neuen Datensatz.",
        ),
        "punctuation": (
            "Sehr gut: Der Satz ist kurz, klar und gut gegliedert.",
            "Warte einen Moment, atme, und sprich dann natürlich weiter.",
            "Es ist nicht nötig zu hetzen; klares und ruhiges Lesen ist besser.",
            "Wenn das Geräusch lauter wird, stopp! Lies erst weiter, wenn der Raum ruhig ist.",
            "Hinweis: Satzzeichen führen den Rhythmus, sollen aber nicht als Text gelesen werden.",
        ),
    },
    "pt": {
        "short": (
            "A xícara fica na prateleira enquanto preparo a sala.",
            "Caminho devagar e mantenho a mesma distância do microfone.",
            "O caderno guarda notas curtas e organizadas.",
            "A voz continua suave mesmo quando a frase acelera.",
            "Fecho a porta sem barulho e volto a ler.",
        ),
        "medium": (
            "Cada gravação deve ter um início limpo, uma frase completa e um final sem ruído.",
            "Se uma palavra parece difícil, digo com naturalidade em vez de aumentar muito o volume.",
            "O texto alterna descrições simples, ações do dia a dia e mudanças controladas de ritmo.",
            "Uma pausa curta entre duas ideias deixa a fala mais clara sem soar artificial.",
            "Leio com atenção, mas deixo a voz se mover de forma leve e natural.",
        ),
        "question": (
            "Você quer repetir a frase se ouvir tosse ou ruído de papel?",
            "Esse tom combina com uma história simples?",
            "Você deixou silêncio suficiente antes de começar a falar?",
            "Podemos deixar a última palavra clara sem exagerar?",
            "O ritmo continua estável quando a frase fica mais longa?",
        ),
        "numbers": (
            "No calendário marco 4 reuniões, 18 minutos de teste e 32 linhas lidas.",
            "O volume fica perto de 70%, e a distância e de cerca de 20 centímetros.",
            "Preparo 5 cartões, descarto 1 e guardo 14 exemplos úteis.",
            "O segundo clipe dura 42 segundos e inclui 6 pausas naturais.",
            "Às 9:30 gravo 3 frases curtas e 2 mais longas.",
        ),
        "names": (
            "Irene escuta Mateo e depois pede a Bianca para conferir o texto.",
            "Luca, Gianni e Serena leem em turnos sem mudar o tom.",
            "Elisa encontra Fabio perto da estante e entrega uma pasta.",
            "Roberto cumprimenta Ana, ajusta o microfone e repete a frase.",
            "Clara e Simon escolhem um exemplo claro para o novo dataset.",
        ),
        "punctuation": (
            "Excelente: a frase é curta, clara e bem ritmada.",
            "Espere um segundo, respire e continue naturalmente.",
            "Não precisa correr; é melhor ler bem e com calma.",
            "Se o ruído aumentar, pare! Continue apenas quando a sala estiver silenciosa.",
            "Nota: a pontuação guia o ritmo, mas não deve ser lida como texto.",
        ),
    },
    "pl": {
        "short": (
            "Kubek stoi na półce, gdy przygotowuję pokój.",
            "Idę powoli i trzymam taką samą odległość od mikrofonu.",
            "Notes zawiera krótkie i uporządkowane zapiski.",
            "Głos pozostaje miękki, nawet gdy zdanie przyspiesza.",
            "Zamykam drzwi cicho i wracam do czytania.",
        ),
        "medium": (
            "Każde nagranie powinno mieć czysty początek, pełne zdanie i koniec bez hałasu.",
            "Jeśli słowo wydaje się trudne, wymawiam je naturalnie zamiast mocno podnosić głos.",
            "Tekst łączy proste opisy, codzienne czynności i kontrolowane zmiany rytmu.",
            "Krótka pauza między dwiema myślami sprawia, że mowa jest jaśniejsza i nie brzmi sztucznie.",
            "Czytam uważnie, ale pozwalam głosowi poruszać się lekko i swobodnie.",
        ),
        "question": (
            "Czy chcesz powtórzyć zdanie, jeśli słychać kaszel albo szelest?",
            "Czy ten ton pasuje do prostej opowieści?",
            "Czy zostawiono dość ciszy przed rozpoczęciem mówienia?",
            "Czy możemy wyraźnie wypowiedzieć ostatnie słowo bez przesady?",
            "Czy rytm pozostaje stały, gdy zdanie staje się dłuższe?",
        ),
        "numbers": (
            "W kalendarzu zaznaczam 4 spotkania, 18 minut próby i 32 przeczytane linie.",
            "Głośność zostaje blisko 70%, a odległość wynosi około 20 centymetrów.",
            "Przygotowuję 5 kart, odrzucam 1 i zostawiam 14 przydatnych przykładów.",
            "Drugi klip trwa 42 sekundy i zawiera 6 naturalnych pauz.",
            "O 9:30 nagrywam 3 krótkie zdania i 2 dłuższe.",
        ),
        "names": (
            "Irena słucha Mateusza, a potem prosi Biankę o sprawdzenie tekstu.",
            "Luca, Gianni i Serena czytają po kolei bez zmiany tonu.",
            "Elisa spotyka Fabia przy regale i podaje mu teczkę.",
            "Robert wita Annę, ustawia mikrofon i powtarza zdanie.",
            "Klara i Simon wybierają jasny przykład do nowego zbioru danych.",
        ),
        "punctuation": (
            "Bardzo dobrze: zdanie jest krótkie, jasne i równo przeczytane.",
            "Poczekaj sekundę, weź oddech i kontynuuj naturalnie.",
            "Nie trzeba się spieszyć; lepiej czytać wyraźnie i spokojnie.",
            "Jeśli hałas wzrośnie, zatrzymaj się! Kontynuuj dopiero w ciszy.",
            "Uwaga: interpunkcja prowadzi rytm, ale nie powinna być czytana jako tekst.",
        ),
    },
    "tr": {
        "short": (
            "Fincan rafta kalır, ben odayı hazırlarım.",
            "Yavaş yürür ve mikrofona aynı uzaklıkta kalırım.",
            "Defterde kısa ve düzenli notlar vardır.",
            "Cümle hızlansa bile ses yumuşak kalır.",
            "Kapıyı sessizce kapatıp okumaya devam ederim.",
        ),
        "medium": (
            "Her kaydın temiz bir başlangıcı, tam bir cümlesi ve gürültüsüz bir sonu olmalıdır.",
            "Bir kelime zor gelirse sesi çok yükseltmeden doğal biçimde söylerim.",
            "Metin basit betimlemeleri, günlük hareketleri ve kontrollü ritim değişimlerini dengeler.",
            "İki fikir arasındaki kısa duraklama konuşmayı yapaylaştırmadan daha anlaşılır kılar.",
            "Dikkatli okurum, ama sesin hafif ve doğal bir hareket taşımasına izin veririm.",
        ),
        "question": (
            "Öksürük ya da hışırtı duyarsan cümleyi tekrar etmek ister misin?",
            "Bu ton basit bir anlatı için uygun mu?",
            "Konuşmaya başlamadan önce yeterince sessizlik bıraktın mı?",
            "Son kelimeyi abartmadan netleştirebilir miyiz?",
            "Cümle uzadığında ritim aynı kalıyor mu?",
        ),
        "numbers": (
            "Takvimde 4 görüşme, 18 dakikalık deneme ve 32 okunan satır işaretlerim.",
            "Ses seviyesi 70% civarında kalır, mesafe yaklaşık 20 santimetredir.",
            "5 kart hazırlarım, 1 tanesini çıkarır ve 14 yararlı örnek saklarım.",
            "İkinci klip 42 saniye sürer ve 6 doğal duraklama içerir.",
            "Saat 9:30'da 3 kısa cümle ve 2 daha uzun cümle kaydederim.",
        ),
        "names": (
            "Irene, Mateo'yu dinler ve sonra Bianca'dan metni kontrol etmesini ister.",
            "Luca, Gianni ve Serena tonu değiştirmeden sırayla okur.",
            "Elisa kitaplığın yanında Fabio ile buluşur ve ona bir dosya verir.",
            "Robert, Anna'yı selamlar, mikrofonu ayarlar ve cümleyi tekrar dener.",
            "Clara ve Simon yeni veri seti için açık bir örnek seçer.",
        ),
        "punctuation": (
            "Harika: cümle kısa, açık ve dengeli okunmuş.",
            "Bir saniye bekle, nefes al, sonra doğal şekilde devam et.",
            "Acele etmeye gerek yok; açık ve sakin okumak daha iyidir.",
            "Gürültü artarsa dur! Oda sessizleşince devam et.",
            "Not: Noktalama ritmi yönlendirir, ama metin gibi okunmamalıdır.",
        ),
    },
    "ru": {
        "short": (
            "Чашка остается на полке, пока я готовлю комнату.",
            "Я иду медленно и держу одинаковое расстояние до микрофона.",
            "В блокноте лежат короткие и аккуратные заметки.",
            "Голос остается мягким, даже когда фраза ускоряется.",
            "Я тихо закрываю дверь и снова начинаю читать.",
        ),
        "medium": (
            "У каждой записи должно быть чистое начало, полная фраза и конец без лишнего шума.",
            "Если слово кажется трудным, я произношу его естественно, не повышая громкость слишком сильно.",
            "Текст чередует простые описания, обычные действия и контролируемые изменения ритма.",
            "Короткая пауза между двумя мыслями делает речь яснее, но не звучит искусственно.",
            "Я читаю внимательно, позволяя голосу двигаться легко и естественно.",
        ),
        "question": (
            "Хочешь повторить фразу, если слышен кашель или шорох?",
            "Подходит ли этот тон для простого рассказа?",
            "Ты оставил достаточно тишины перед началом речи?",
            "Можем сделать последнее слово ясным без преувеличения?",
            "Ритм остается ровным, когда фраза становится длиннее?",
        ),
        "numbers": (
            "В календаре я отмечаю 4 встречи, 18 минут проверки и 32 прочитанные строки.",
            "Громкость держится около 70%, а расстояние составляет примерно 20 сантиметров.",
            "Я готовлю 5 карточек, убираю 1 и оставляю 14 полезных примеров.",
            "Второй клип длится 42 секунды и содержит 6 естественных пауз.",
            "В 9:30 я записываю 3 короткие фразы и 2 более длинные.",
        ),
        "names": (
            "Ирина слушает Матвея, затем просит Бьянку проверить текст.",
            "Лука, Джанни и Серена читают по очереди, не меняя тон.",
            "Элиза встречает Фабио у книжного шкафа и передает ему папку.",
            "Роберт здоровается с Анной, настраивает микрофон и повторяет фразу.",
            "Клара и Симон выбирают ясный пример для нового набора данных.",
        ),
        "punctuation": (
            "Отлично: фраза короткая, ясная и ровно прочитанная.",
            "Подожди секунду, вдохни, затем продолжай естественно.",
            "Не нужно спешить; лучше читать четко и спокойно.",
            "Если шум усилился, остановись! Продолжай только в тишине.",
            "Примечание: пунктуация задает ритм, но ее не нужно читать как текст.",
        ),
    },
    "nl": {
        "short": (
            "De beker blijft op de plank terwijl ik de kamer voorbereid.",
            "Ik loop langzaam en houd dezelfde afstand tot de microfoon.",
            "Het schrift bevat korte en nette notities.",
            "De stem blijft zacht, ook wanneer de zin sneller gaat.",
            "Ik sluit de deur stil en begin weer te lezen.",
        ),
        "medium": (
            "Elke opname heeft een schoon begin, een volledige zin en een einde zonder storend geluid nodig.",
            "Als een woord moeilijk lijkt, spreek ik het natuurlijk uit zonder het volume te veel te verhogen.",
            "De tekst wisselt eenvoudige beschrijvingen, dagelijkse handelingen en gecontroleerde ritmewissels af.",
            "Een korte pauze tussen twee gedachten maakt spraak duidelijker zonder kunstmatig te klinken.",
            "Ik lees aandachtig, maar laat de stem licht en natuurlijk bewegen.",
        ),
        "question": (
            "Wil je de zin herhalen als je hoest of geritsel hoort?",
            "Past deze toon bij een eenvoudig verhaal?",
            "Heb je genoeg stilte gelaten voordat je begon te spreken?",
            "Kunnen we het laatste woord duidelijk maken zonder te overdrijven?",
            "Blijft het ritme gelijk wanneer de zin langer wordt?",
        ),
        "numbers": (
            "Op de kalender noteer ik 4 afspraken, 18 minuten test en 32 gelezen regels.",
            "Het volume blijft rond 70%, en de afstand is ongeveer 20 centimeter.",
            "Ik maak 5 kaarten klaar, gooi er 1 weg en bewaar 14 nuttige voorbeelden.",
            "De tweede clip duurt 42 seconden en bevat 6 natuurlijke pauzes.",
            "Om 9:30 neem ik één korte zin en 2 langere zinnen op.",
        ),
        "names": (
            "Irene luistert naar Mateo en vraagt daarna aan Bianca om de tekst te controleren.",
            "Luca, Gianni en Serena lezen om de beurt zonder van toon te veranderen.",
            "Elisa ontmoet Fabio bij de boekenkast en geeft hem een map.",
            "Robert begroet Anna, zet de microfoon goed en probeert de zin opnieuw.",
            "Clara en Simon kiezen een duidelijk voorbeeld voor de nieuwe dataset.",
        ),
        "punctuation": (
            "Prima: de zin is kort, duidelijk en goed getimed.",
            "Wacht een seconde, adem in en ga dan natuurlijk verder.",
            "Je hoeft niet te haasten; rustig en duidelijk lezen is beter.",
            "Als het geluid toeneemt, stop dan! Ga pas verder als de kamer stil is.",
            "Let op: interpunctie stuurt het ritme, maar moet niet als tekst worden gelezen.",
        ),
    },
    "cs": {
        "short": (
            "Hrnek zůstává na polici, zatímco připravuji místnost.",
            "Jdu pomalu a držím stejnou vzdálenost od mikrofonu.",
            "Zápisník obsahuje krátké a uspořádané poznámky.",
            "Hlas zůstává měkký, i když věta zrychlí.",
            "Tiše zavřu dveře a znovu začnu číst.",
        ),
        "medium": (
            "Každá nahrávka má mít čistý začátek, celou větu a konec bez rušivých zvuků.",
            "Když je slovo obtížné, vyslovím ho přirozeně a nezvyšuji příliš hlasitost.",
            "Text střídá jednoduché popisy, běžné činnosti a kontrolované změny rytmu.",
            "Krátká pauza mezi dvěma myšlenkami zlepší srozumitelnost, aniž by řeč zněla uměle.",
            "Čtu pozorně, ale nechávám hlasu lehký a přirozený pohyb.",
        ),
        "question": (
            "Chceš větu zopakovat, pokud uslyšíš kašel nebo šustění?",
            "Hodí se tento tón k jednoduchému vyprávění?",
            "Nechal jsi dost ticha před začátkem řeči?",
            "Můžeme poslední slovo vyslovit jasně a bez přehánění?",
            "Zůstává rytmus stejný, když je věta delší?",
        ),
        "numbers": (
            "V kalendáři značím 4 schůzky, 18 minut zkoušky a 32 přečtených řádků.",
            "Hlasitost zůstává kolem 70% a vzdálenost je asi 20 centimetrů.",
            "Připravím 5 karet, 1 vyřadím a nechám 14 užitečných příkladů.",
            "Druhý klip trvá 42 sekund a obsahuje 6 přirozených pauz.",
            "V 9:30 nahrávám 3 krátké věty a 2 delší.",
        ),
        "names": (
            "Irena poslouchá Matea a potom požádá Bianku o kontrolu textu.",
            "Luca, Gianni a Serena čtou postupně a nemění tón.",
            "Elisa potká Fabia u knihovny a podá mu složku.",
            "Robert pozdraví Annu, nastaví mikrofon a zkusí větu znovu.",
            "Klára a Simon vyberou jasný příklad pro nový datový soubor.",
        ),
        "punctuation": (
            "Výborně: věta je krátká, jasná a dobře rytmizovaná.",
            "Počkej vteřinu, nadechni se a potom přirozeně pokračuj.",
            "Není třeba spěchat; lepší je číst zřetelně a klidně.",
            "Pokud hluk zesílí, zastav se! Pokračuj až v tichu.",
            "Poznámka: interpunkce vede rytmus, ale nemá se číst jako text.",
        ),
    },
    "ar": {
        "short": (
            "يبقى الكوب على الرف بينما أجهز الغرفة.",
            "أمشي ببطء وأحافظ على نفس المسافة من الميكروفون.",
            "يحتوي الدفتر على ملاحظات قصيرة ومرتبة.",
            "يبقى الصوت ناعما حتى عندما تسرع الجملة.",
            "أغلق الباب بهدوء وأعود إلى القراءة.",
        ),
        "medium": (
            "يجب أن يكون لكل تسجيل بداية نظيفة وجملة كاملة ونهاية بلا ضجيج.",
            "إذا بدت كلمة صعبة، أنطقها بطبيعية بدلا من رفع الصوت كثيرا.",
            "يمزج النص بين أوصاف بسيطة وأفعال يومية وتغييرات إيقاع مضبوطة.",
            "وقفة قصيرة بين فكرتين تجعل الكلام أوضح من دون أن يبدو مصطنعا.",
            "أقرأ بانتباه، لكن أترك للصوت حركة خفيفة وطبيعية.",
        ),
        "question": (
            "هل تريد إعادة الجملة إذا سمعت سعالا أو حفيفا؟",
            "هل تناسب هذه النبرة قصة بسيطة؟",
            "هل تركت صمتا كافيا قبل أن تبدأ الكلام؟",
            "هل يمكن أن نجعل الكلمة الأخيرة واضحة من دون مبالغة؟",
            "هل يبقى الإيقاع ثابتا عندما تصبح الجملة أطول؟",
        ),
        "numbers": (
            "في التقويم أضع 4 مواعيد و18 دقيقة اختبار و32 سطرا مقروءا.",
            "يبقى مستوى الصوت قرب 70%، والمسافة نحو 20 سنتيمترا.",
            "أجهز 5 بطاقات، أستبعد 1، وأحتفظ ب14 مثالا مفيدا.",
            "تدوم اللقطة الثانية 42 ثانية وفيها 6 وقفات طبيعية.",
            "في الساعة 9:30 أسجل 3 جمل قصيرة و2 أطول.",
        ),
        "names": (
            "تستمع إيرين إلى ماتيو، ثم تطلب من بيانكا مراجعة النص.",
            "يقرأ لوكا وجياني وسيرينا بالتناوب من دون تغيير النبرة.",
            "تلتقي إليسا بفابيو قرب المكتبة وتعطيه ملفا.",
            "يحيي روبرت آنا، يضبط الميكروفون، ثم يعيد الجملة.",
            "تختار كلارا وسيمون مثالا واضحا للمجموعة الجديدة.",
        ),
        "punctuation": (
            "ممتاز: الجملة قصيرة وواضحة وموزونة.",
            "انتظر ثانية، تنفس، ثم تابع بشكل طبيعي.",
            "لا داعي للعجلة؛ القراءة الواضحة والهادئة أفضل.",
            "إذا زاد الضجيج، توقف! تابع فقط عندما تهدأ الغرفة.",
            "ملاحظة: علامات الترقيم توجه الإيقاع، لكنها لا تقرأ كنص.",
        ),
    },
    "zh-cn": {
        "short": (
            "杯子留在架子上，我开始整理房间。",
            "我慢慢走动，并保持和麦克风相同的距离。",
            "笔记本里有简短而整齐的记录。",
            "即使句子加快，声音也保持柔和。",
            "我轻轻关上门，然后继续朗读。",
        ),
        "medium": (
            "每段录音都应该有干净的开头、完整的句子和没有杂音的结尾。",
            "如果某个词比较难，我会自然地说出来，而不是把音量提高太多。",
            "文本交替使用简单描述、日常动作和受控制的节奏变化。",
            "两个想法之间短暂停顿，可以让讲话更清楚，也不会显得生硬。",
            "我认真朗读，同时让声音保持轻松自然的变化。",
        ),
        "question": (
            "如果听到咳嗽或纸张摩擦声，你想重新读这一句吗？",
            "这种语气适合一个简单的故事吗？",
            "开始说话之前，你留下足够的安静时间了吗？",
            "我们能把最后一个词说清楚，但不要夸张吗？",
            "当句子变长时，节奏还能保持稳定吗？",
        ),
        "numbers": (
            "我在日历上标出4次会议、18分钟测试和32行朗读内容。",
            "音量保持在70%左右，距离大约是20厘米。",
            "我准备5张卡片，去掉1张，留下14个有用例子。",
            "第二段录音长42秒，其中有6个自然停顿。",
            "9:30的时候，我录3个短句和2个较长的句子。",
        ),
        "names": (
            "艾琳听马特奥朗读，然后请比安卡检查文字。",
            "卢卡、詹尼和塞雷娜轮流朗读，不改变语气。",
            "艾丽莎在书架旁遇到法比奥，并把文件夹交给他。",
            "罗伯特向安娜打招呼，调整麦克风，然后重读句子。",
            "克拉拉和西蒙为新的数据集选择一个清楚的例子。",
        ),
        "punctuation": (
            "很好：句子短、清楚，而且节奏稳定。",
            "等一秒，吸气，然后自然地继续。",
            "不用着急；清楚而平静地读更好。",
            "如果噪音变大，就停下！等房间安静后再继续。",
            "注意：标点引导节奏，但不应该当成文字读出来。",
        ),
    },
    "ja": {
        "short": (
            "カップは棚に置いたまま、部屋を整えます。",
            "ゆっくり歩き、マイクとの距離を同じに保ちます。",
            "ノートには短く整理されたメモがあります。",
            "文が速くなっても、声はやわらかく保ちます。",
            "静かにドアを閉めて、また読み始めます。",
        ),
        "medium": (
            "どの録音にも、きれいな始まり、完全な文、雑音のない終わりが必要です。",
            "難しい言葉があっても、音量を上げすぎず自然に発音します。",
            "文章は、簡単な説明、日常の動き、そして制御されたリズムの変化を組み合わせます。",
            "二つの考えの間に短い間を置くと、話し方は自然なまま聞き取りやすくなります。",
            "注意して読みながら、声には軽く自然な動きを残します。",
        ),
        "question": (
            "咳や紙の音が聞こえたら、この文をもう一度読みますか？",
            "この声の調子は、簡単な話に合っていますか？",
            "話し始める前に、十分な静けさを残しましたか？",
            "最後の言葉を大げさにせず、はっきり言えますか？",
            "文が長くなっても、リズムは安定していますか？",
        ),
        "numbers": (
            "カレンダーに4件の予定、18分のテスト、32行の読み上げを記録します。",
            "音量は70%くらいで、距離は約20センチです。",
            "5枚のカードを用意し、1枚を外して、14個の例を残します。",
            "2番目のクリップは42秒で、6回の自然な間があります。",
            "9:30に短い文を3つ、少し長い文を2つ録音します。",
        ),
        "names": (
            "アイリーンはマテオの声を聞き、ビアンカに文章の確認を頼みます。",
            "ルカ、ジャンニ、セレナは、声の調子を変えずに順番に読みます。",
            "エリサは本棚のそばでファビオに会い、フォルダーを渡します。",
            "ロバートはアンナに挨拶し、マイクを整えて文を読み直します。",
            "クララとサイモンは、新しいデータセットのために分かりやすい例を選びます。",
        ),
        "punctuation": (
            "よいです：文は短く、明瞭で、リズムも安定しています。",
            "一秒待って、息を吸い、それから自然に続けます。",
            "急ぐ必要はありません；落ち着いてはっきり読む方がよいです。",
            "音が大きくなったら止まりましょう！部屋が静かになってから続けます。",
            "注意：句読点はリズムを導きますが、文字として読むものではありません。",
        ),
    },
    "hu": {
        "short": (
            "A bögre a polcon marad, amíg előkészítem a szobát.",
            "Lassan sétálok, és ugyanazt a távolságot tartom a mikrofontól.",
            "A füzetben rövid és rendezett jegyzetek vannak.",
            "A hang puha marad akkor is, amikor a mondat gyorsul.",
            "Csendben becsukom az ajtót, és újra olvasni kezdek.",
        ),
        "medium": (
            "Minden felvételnek tiszta kezdetre, teljes mondatra és zajmentes befejezésre van szüksége.",
            "Ha egy szó nehéznek tűnik, természetesen mondom ki, nem pedig túl hangosan.",
            "A szöveg egyszerű leírásokat, mindennapi cselekvéseket és kontrollált ritmusváltásokat kever.",
            "Két gondolat között egy rövid szünet érthetőbbé teszi a beszédet, anélkül hogy mesterkélt lenne.",
            "Figyelmesen olvasok, de a hangnak könnyed és természetes mozgást hagyok.",
        ),
        "question": (
            "Megismétled a mondatot, ha köhögést vagy zizegést hallasz?",
            "Ez a hangnem illik egy egyszerű történethez?",
            "Hagytál elég csendet, mielőtt beszélni kezdtél?",
            "Ki tudjuk mondani az utolsó szót tisztán, túlzás nélkül?",
            "A ritmus stabil marad akkor is, amikor a mondat hosszabb lesz?",
        ),
        "numbers": (
            "A naptárban 4 találkozót, 18 perc próbát és 32 felolvasott sort jelölök.",
            "A hangerő 70% körül marad, a távolság pedig nagyjából 20 centiméter.",
            "Előkészítek 5 kártyát, 1-et félreteszek, és 14 hasznos példát megtartok.",
            "A második klip 42 másodpercig tart, és 6 természetes szünetet tartalmaz.",
            "9:30-kor 3 rövid mondatot és 2 hosszabbat veszek fel.",
        ),
        "names": (
            "Irén Mátét hallgatja, majd megkéri Biankát, hogy ellenőrizze a szöveget.",
            "Luca, Gianni és Serena felváltva olvas, anélkül hogy hangnemet váltana.",
            "Elisa a könyvespolc mellett találkozik Fabióval, és átad neki egy mappát.",
            "Róbert üdvözli Annát, beállítja a mikrofont, és újra megpróbálja a mondatot.",
            "Klára és Simon világos példát választ az új adathalmazhoz.",
        ),
        "punctuation": (
            "Nagyon jó: a mondat rövid, tiszta és jól tagolt.",
            "Várj egy másodpercet, vegyél levegőt, majd folytasd természetesen.",
            "Nem kell sietni; jobb tisztán és nyugodtan olvasni.",
            "Ha a zaj erősödik, állj meg! Csak akkor folytasd, ha a szoba csendes.",
            "Megjegyzés: az írásjel a ritmust vezeti, de nem szabad szövegként felolvasni.",
        ),
    },
    "ko": {
        "short": (
            "컵은 선반 위에 있고, 나는 방을 준비합니다.",
            "천천히 걸으며 마이크와 같은 거리를 유지합니다.",
            "공책에는 짧고 정리된 메모가 있습니다.",
            "문장이 빨라져도 목소리는 부드럽게 유지됩니다.",
            "문을 조용히 닫고 다시 읽기 시작합니다.",
        ),
        "medium": (
            "각 녹음에는 깨끗한 시작, 완전한 문장, 그리고 잡음 없는 끝이 필요합니다.",
            "어려운 단어가 나오면 소리를 너무 키우지 않고 자연스럽게 말합니다.",
            "이 글은 간단한 설명, 일상적인 행동, 조절된 리듬 변화를 번갈아 사용합니다.",
            "두 생각 사이의 짧은 멈춤은 말을 더 분명하게 만들지만 인위적으로 들리지는 않습니다.",
            "주의해서 읽되, 목소리에는 가볍고 자연스러운 움직임을 남깁니다.",
        ),
        "question": (
            "기침이나 종이 소리가 들리면 그 문장을 다시 읽을까요?",
            "이 톤은 간단한 이야기와 잘 어울리나요?",
            "말하기 전에 충분한 조용한 시간을 남겼나요?",
            "마지막 단어를 과장하지 않고 분명하게 말할 수 있을까요?",
            "문장이 길어져도 리듬이 안정적으로 유지되나요?",
        ),
        "numbers": (
            "달력에 회의 4개, 테스트 18분, 읽은 줄 32개를 표시합니다.",
            "음량은 70% 근처로 유지하고, 거리는 약 20센티미터입니다.",
            "카드 5장을 준비하고, 1장을 빼고, 유용한 예시 14개를 남깁니다.",
            "두 번째 클립은 42초이며 자연스러운 멈춤이 6번 있습니다.",
            "9:30에 짧은 문장 3개와 조금 긴 문장 2개를 녹음합니다.",
        ),
        "names": (
            "아이린은 마테오의 말을 듣고, 비앙카에게 글을 확인해 달라고 합니다.",
            "루카, 지아니, 세레나는 톤을 바꾸지 않고 차례로 읽습니다.",
            "엘리사는 책장 옆에서 파비오를 만나 폴더를 건넵니다.",
            "로버트는 안나에게 인사하고, 마이크를 맞춘 뒤 문장을 다시 읽습니다.",
            "클라라와 사이먼은 새 데이터셋을 위해 분명한 예시를 고릅니다.",
        ),
        "punctuation": (
            "좋습니다: 문장은 짧고 분명하며 리듬도 안정적입니다.",
            "잠시 기다리고, 숨을 쉬고, 자연스럽게 계속하세요.",
            "서두를 필요는 없습니다; 또렷하고 차분하게 읽는 것이 좋습니다.",
            "소음이 커지면 멈추세요! 방이 조용해진 뒤에 계속합니다.",
            "참고: 문장 부호는 리듬을 이끌지만, 글자처럼 읽으면 안 됩니다.",
        ),
    },
    "hi": {
        "short": (
            "कप शेल्फ पर रहता है, और मैं कमरा तैयार करता हूं।",
            "मैं धीरे चलता हूं और माइक्रोफोन से वही दूरी रखता हूं।",
            "नोटबुक में छोटी और साफ नोट्स लिखी हैं।",
            "वाक्य तेज हो जाए तब भी आवाज़ नरम रहती है।",
            "मैं दरवाजा चुपचाप बंद करता हूं और फिर पढ़ता हूं।",
        ),
        "medium": (
            "हर रिकॉर्डिंग की शुरुआत साफ, वाक्य पूरा और अंत बिना शोर के होना चाहिए।",
            "अगर कोई शब्द कठिन लगे, तो मैं आवाज़ बहुत बढ़ाए बिना उसे स्वाभाविक रूप से बोलता हूं।",
            "पाठ में सरल विवरण, रोज़मर्रा की क्रियाएं और नियंत्रित लय परिवर्तन शामिल हैं।",
            "दो विचारों के बीच छोटी रुकावट बोलने को साफ बनाती है, पर उसे कृत्रिम नहीं बनाती।",
            "मैं ध्यान से पढ़ता हूं, लेकिन आवाज़ में हल्की और प्राकृतिक गति रहने देता हूं।",
        ),
        "question": (
            "क्या खांसी या कागज़ की आवाज़ सुनाई दे तो आप वाक्य दोहराना चाहेंगे?",
            "क्या यह स्वर एक सरल कहानी के लिए ठीक है?",
            "क्या आपने बोलना शुरू करने से पहले पर्याप्त शांति छोड़ी?",
            "क्या हम अंतिम शब्द को बिना बढ़ा-चढ़ाकर साफ बोल सकते हैं?",
            "क्या वाक्य लंबा होने पर भी लय स्थिर रहती है?",
        ),
        "numbers": (
            "कैलेंडर में मैं 4 बैठकें, 18 मिनट की जांच और 32 पढ़ी गई पंक्तियां लिखता हूं।",
            "आवाज़ 70% के पास रहती है, और दूरी लगभग 20 सेंटीमीटर है।",
            "मैं 5 कार्ड तैयार करता हूं, 1 हटाता हूं और 14 उपयोगी उदाहरण रखता हूं।",
            "दूसरी क्लिप 42 सेकंड की है और इसमें 6 प्राकृतिक रुकावटें हैं।",
            "9:30 पर मैं 3 छोटे वाक्य और 2 लंबे वाक्य रिकॉर्ड करता हूं।",
        ),
        "names": (
            "आइरीन मातेओ को सुनती है, फिर बियांका से पाठ जांचने को कहती है।",
            "लूका, जियानी और सेरेना बिना स्वर बदले बारी-बारी पढ़ते हैं।",
            "एलिसा किताबों की अलमारी के पास फैबियो से मिलती है और उसे फोल्डर देती है।",
            "रॉबर्ट अन्ना को नमस्ते कहता है, माइक्रोफोन ठीक करता है और वाक्य फिर पढ़ता है।",
            "क्लारा और साइमन नए डेटासेट के लिए स्पष्ट उदाहरण चुनते हैं।",
        ),
        "punctuation": (
            "बहुत अच्छा: वाक्य छोटा, साफ और सही लय वाला है।",
            "एक सेकंड रुकिए, सांस लीजिए, फिर स्वाभाविक रूप से जारी रखें।",
            "जल्दी करने की जरूरत नहीं; साफ और शांत पढ़ना बेहतर है।",
            "अगर शोर बढ़े, रुकिए! कमरा शांत होने पर ही आगे पढ़िए।",
            "ध्यान दें: विराम चिह्न लय बताते हैं, उन्हें शब्द की तरह नहीं पढ़ना चाहिए।",
        ),
    },
}


def merge_prompt_corpus(
    base: dict[str, ModelingPromptCorpus],
    extensions: dict[str, ModelingPromptCorpus],
) -> dict[str, ModelingPromptCorpus]:
    merged: dict[str, ModelingPromptCorpus] = {}
    for language_code, corpus in base.items():
        extension = extensions.get(language_code)
        if extension is None:
            merged[language_code] = corpus
            continue
        merged[language_code] = {
            slot_name: (*corpus[slot_name], *extension[slot_name])
            for slot_name in PROMPT_SLOT_ORDER
        }
    return merged


MODELING_PROMPT_CORPUS = merge_prompt_corpus(MODELING_PROMPT_CORPUS, MODELING_PROMPT_CORPUS_EXTENSIONS)


def generate_modeling_prompt(
    language_code: str,
    *,
    used_texts: tuple[str, ...] = (),
    max_chars: int = MODELING_PROMPT_DEFAULT_MAX_CHARS,
) -> GeneratedModelingPrompt:
    language_key = modeling_prompt_language_key(language_code)
    corpus = MODELING_PROMPT_CORPUS[language_key]
    used = {normalize_prompt_text(text) for text in used_texts if normalize_prompt_text(text)}
    max_chars = max(80, int(max_chars))
    max_attempts = min(5000, max(1, modeling_prompt_variant_count(corpus)))

    for attempt in range(max_attempts):
        prompt = build_prompt_from_corpus(corpus, seed=len(used_texts) + attempt, max_chars=max_chars)
        if normalize_prompt_text(prompt) not in used:
            return GeneratedModelingPrompt(
                text=prompt,
                language_code=language_key,
                corpus_version=MODELING_PROMPT_CORPUS_VERSION,
                source=MODELING_PROMPT_SOURCE_GENERATED,
            )

    raise NoUnusedModelingPromptError(NO_UNUSED_MODELING_PROMPTS_MESSAGE)


def build_prompt_from_corpus(corpus: ModelingPromptCorpus, *, seed: int, max_chars: int) -> str:
    selected: list[str] = []
    variant_index = prompt_variant_index(seed, corpus)
    for slot_index, slot_name in enumerate(PROMPT_SLOT_ORDER):
        slot = corpus[slot_name]
        sentence = slot[slot_sentence_index(variant_index, corpus, slot_index, len(slot))]
        candidate = normalize_prompt_text(" ".join((*selected, sentence)))
        if len(candidate) <= max_chars:
            selected.append(sentence)
    if selected:
        return normalize_prompt_text(" ".join(selected))

    fallback = corpus["short"][seed % len(corpus["short"])]
    return normalize_prompt_text(fallback[:max_chars])


def prompt_variant_index(seed: int, corpus: ModelingPromptCorpus) -> int:
    variant_count = modeling_prompt_variant_count(corpus)
    if variant_count <= 1:
        return 0
    return (seed * prompt_variant_stride(corpus)) % variant_count


def prompt_variant_stride(corpus: ModelingPromptCorpus) -> int:
    variant_count = modeling_prompt_variant_count(corpus)
    if variant_count <= 1:
        return 1
    stride = 0
    multiplier = 1
    for slot_index, slot_name in enumerate(PROMPT_SLOT_ORDER):
        slot_length = max(1, len(corpus[slot_name]))
        digit = 0
        if slot_length > 1:
            digit = PROMPT_SLOT_STRIDE_DIGITS[slot_index] % slot_length or 1
        stride += digit * multiplier
        multiplier *= slot_length
    stride %= variant_count
    if stride == 0:
        stride = 1
    while gcd(stride, variant_count) != 1:
        stride = (stride + 1) % variant_count or 1
    return stride


def slot_sentence_index(variant_index: int, corpus: ModelingPromptCorpus, slot_index: int, slot_length: int) -> int:
    if slot_length <= 1:
        return 0
    divisor = 1
    for previous_slot in PROMPT_SLOT_ORDER[:slot_index]:
        divisor *= max(1, len(corpus[previous_slot]))
    return (variant_index // divisor) % slot_length


def modeling_prompt_variant_count(corpus: ModelingPromptCorpus) -> int:
    count = 1
    for slot_name in PROMPT_SLOT_ORDER:
        count *= max(1, len(corpus[slot_name]))
    return count


def modeling_prompt_available_count(language_code: str) -> int:
    return modeling_prompt_variant_count(MODELING_PROMPT_CORPUS[modeling_prompt_language_key(language_code)])


def modeling_prompt_language_key(language_code: str) -> str:
    normalized = normalize_language_code(language_code) or "en"
    if normalized == "zh":
        normalized = "zh-cn"
    if normalized in MODELING_PROMPT_CORPUS:
        return normalized
    return "en"


def generated_prompt_source(source: str) -> bool:
    return source.strip().startswith("generated_prompt:")


def normalize_prompt_text(text: str) -> str:
    return " ".join(text.split()).strip()


def prompt_corpus_languages_complete() -> bool:
    return set(VOICE_PROFILE_LANGUAGES) <= set(MODELING_PROMPT_CORPUS)
