from dataclasses import dataclass
from typing import TypedDict

from voicebridge.languages import normalize_language_code
from voicebridge.voice_profiles import VOICE_PROFILE_LANGUAGES

MODELING_PROMPT_CORPUS_VERSION = "1.0"
MODELING_PROMPT_SOURCE_GENERATED = f"generated_prompt:{MODELING_PROMPT_CORPUS_VERSION}"
MODELING_PROMPT_SOURCE_PROVIDED = "provided_text"
MODELING_PROMPT_DEFAULT_MAX_CHARS = 450


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


PROMPT_SLOT_ORDER = ("short", "medium", "question", "numbers", "names", "punctuation")

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
            "Hai controllato se il testo e' completo prima di registrare?",
            "Possiamo ripetere questa parte con lo stesso tono e la stessa distanza dal microfono?",
            "Ti sembra piu' naturale fare una pausa breve dopo la domanda?",
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
            "La sala esta tranquila y la voz se mantiene firme.",
            "Abro el cuaderno y leo la siguiente linea con calma.",
            "Un ritmo sereno ayuda a entender cada palabra.",
        ),
        "medium": (
            "Cuando el texto se hace mas largo, mantengo una cadencia regular y respiro sin prisa.",
            "Una voz clara permite seguir cada idea sin esfuerzo.",
            "Hoy describo detalles sencillos con palabras comunes y algunos sonidos menos frecuentes.",
        ),
        "question": (
            "Has comprobado que el texto coincide con el audio antes de guardarlo?",
            "Podemos repetir esta frase con el mismo tono y la misma distancia al microfono?",
            "Suena mas natural hacer una pausa breve despues de la pregunta?",
        ),
        "numbers": (
            "En la mesa hay 3 lapices, 12 hojas y 24 etiquetas pequenas.",
            "La lectura debe durar unos 30 segundos, no 10 y no 90.",
            "A las 8:15 preparo una nota corta y despues leo otras 2.",
        ),
        "names": (
            "Marta y Daniel miran el jardin mientras Nora ordena las sillas.",
            "Julia, Mateo y Clara eligen palabras simples para explicar la idea.",
            "Leo espera junto a la puerta y luego vuelve despacio.",
        ),
        "punctuation": (
            "Bien, seguimos con calma! Luego paramos un momento.",
            "Primero leo la frase; despues reviso la respiracion, el ritmo y la claridad.",
            "Nota: el volumen debe mantenerse estable, sin forzar la voz.",
        ),
    },
    "fr": {
        "short": (
            "La piece est calme et la voix reste reguliere.",
            "J'ouvre le carnet et je lis la ligne suivante.",
            "Un rythme pose rend chaque mot plus clair.",
        ),
        "medium": (
            "Quand le passage devient plus long, je garde une cadence simple et je respire naturellement.",
            "Une parole nette aide l'auditeur a suivre chaque idee sans effort.",
            "Aujourd'hui je decris des details ordinaires avec des mots courants et quelques sons moins habituels.",
        ),
        "question": (
            "As-tu verifie que le texte correspond bien a l'audio avant de l'enregistrer?",
            "Pouvons-nous repeter cette phrase avec le meme ton et la meme distance du micro?",
            "Une courte pause apres la question semble-t-elle plus naturelle?",
        ),
        "numbers": (
            "Sur la table il y a 3 crayons, 12 feuilles et 24 petites etiquettes.",
            "Cette lecture doit durer environ 30 secondes, pas 10 et pas 90.",
            "A 8:15 je prepare une note courte, puis j'en lis 2 autres.",
        ),
        "names": (
            "Marta et Daniel regardent le jardin pendant que Nora range les chaises.",
            "Julie, Mateo et Claire choisissent des mots simples pour expliquer l'idee.",
            "Leo attend pres de la porte, puis il rentre tranquillement.",
        ),
        "punctuation": (
            "Bien, continuons calmement! Ensuite nous faisons une pause.",
            "D'abord je lis la phrase; ensuite je controle le souffle, le rythme et la clarte.",
            "Note: le volume doit rester stable, sans forcer la voix.",
        ),
    },
    "de": {
        "short": (
            "Der Raum ist ruhig, und die Stimme bleibt gleichmaessig.",
            "Ich oeffne das Heft und lese die naechste Zeile.",
            "Ein ruhiges Tempo macht jedes Wort klarer.",
        ),
        "medium": (
            "Wenn der Abschnitt laenger wird, halte ich einen regelmaessigen Rhythmus und atme natuerlich.",
            "Deutliche Sprache hilft beim Folgen jeder Idee ohne Anstrengung.",
            "Heute beschreibe ich einfache Details mit haeufigen Woertern und einigen selteneren Lauten.",
        ),
        "question": (
            "Hast du geprueft, ob der Text vor dem Speichern zum Audio passt?",
            "Koennen wir diesen Satz mit gleichem Ton und gleichem Mikrofonabstand wiederholen?",
            "Klingt eine kurze Pause nach der Frage natuerlicher?",
        ),
        "numbers": (
            "Auf dem Tisch liegen 3 Stifte, 12 Blaetter und 24 kleine Etiketten.",
            "Diese Aufnahme soll etwa 30 Sekunden dauern, nicht 10 und nicht 90.",
            "Um 8:15 schreibe ich eine kurze Notiz und lese danach 2 weitere.",
        ),
        "names": (
            "Marta und Daniel sehen in den Garten, waehrend Nora die Stuehle ordnet.",
            "Julia, Mateo und Clara waehlen einfache Worte, um die Idee zu erklaeren.",
            "Leo wartet an der Tuer und geht dann langsam wieder hinein.",
        ),
        "punctuation": (
            "Gut, wir machen ruhig weiter! Danach halten wir kurz an.",
            "Zuerst lese ich den Satz; danach pruefe ich Atem, Rhythmus und Klarheit.",
            "Hinweis: Die Lautstaerke soll stabil bleiben, ohne die Stimme zu druecken.",
        ),
    },
    "pt": {
        "short": (
            "A sala esta calma e a voz permanece estavel.",
            "Abro o caderno e leio a proxima linha devagar.",
            "Um ritmo tranquilo ajuda cada palavra a ficar clara.",
        ),
        "medium": (
            "Quando o trecho fica mais longo, mantenho uma cadencia regular e respiro naturalmente.",
            "Uma fala clara ajuda quem escuta a acompanhar cada ideia sem esforco.",
            "Hoje descrevo detalhes simples com palavras comuns e alguns sons menos frequentes.",
        ),
        "question": (
            "Voce conferiu se o texto combina com o audio antes de salvar?",
            "Podemos repetir esta frase com o mesmo tom e a mesma distancia do microfone?",
            "Uma pausa curta depois da pergunta soa mais natural?",
        ),
        "numbers": (
            "Na mesa ha 3 lapis, 12 folhas e 24 etiquetas pequenas.",
            "Esta leitura deve durar cerca de 30 segundos, nao 10 e nao 90.",
            "As 8:15 preparo uma nota curta e depois leio mais 2.",
        ),
        "names": (
            "Marta e Daniel olham o jardim enquanto Nora organiza as cadeiras.",
            "Julia, Mateo e Clara escolhem palavras simples para explicar a ideia.",
            "Leo espera perto da porta e depois volta sem pressa.",
        ),
        "punctuation": (
            "Certo, vamos continuar com calma! Depois paramos um momento.",
            "Primeiro leio a frase; depois verifico respiracao, ritmo e clareza.",
            "Nota: o volume deve ficar estavel, sem forcar a voz.",
        ),
    },
    "pl": {
        "short": (
            "Pokoj jest cichy, a glos pozostaje rowny.",
            "Otwieram notes i czytam nastepne zdanie spokojnie.",
            "Spokojne tempo pomaga wyraznie wypowiedziec kazde slowo.",
        ),
        "medium": (
            "Kiedy fragment staje sie dluzszy, utrzymuje rowny rytm i oddycham naturalnie.",
            "Wyrazna mowa pomaga sluchaczowi bez wysilku sledzic kazda mysl.",
            "Dzis opisuje proste szczegoly, uzywajac codziennych slow i kilku rzadszych dzwiekow.",
        ),
        "question": (
            "Czy sprawdzono, ze tekst zgadza sie z nagraniem przed zapisaniem?",
            "Czy mozemy powtorzyc to zdanie tym samym tonem i z tej samej odleglosci od mikrofonu?",
            "Czy krotka pauza po pytaniu brzmi bardziej naturalnie?",
        ),
        "numbers": (
            "Na biurku sa 3 olowki, 12 kartek i 24 male etykiety.",
            "To czytanie powinno trwac okolo 30 sekund, nie 10 i nie 90.",
            "O 8:15 przygotowuje krotka notatke, potem czytam jeszcze 2.",
        ),
        "names": (
            "Marta i Daniel patrza na ogrod, a Nora ustawia krzesla.",
            "Julia, Mateusz i Klara wybieraja proste slowa, aby wyjasnic pomysl.",
            "Leo czeka przy drzwiach, a potem wraca spokojnym krokiem.",
        ),
        "punctuation": (
            "Dobrze, kontynuujmy spokojnie! Potem zatrzymamy sie na chwile.",
            "Najpierw czytam zdanie; potem sprawdzam oddech, rytm i wyraznosc.",
            "Uwaga: glosnosc powinna byc stala, bez napinania glosu.",
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
            "Mistnost je ticha a hlas zustava vyrovnany.",
            "Oteviram zapisnik a klidne ctu dalsi radek.",
            "Klidne tempo pomaha vyslovit kazde slovo jasne.",
        ),
        "medium": (
            "Kdyz je odstavec delsi, drzim pravidelny rytmus a dycham prirozene.",
            "Zretelna rec pomaha posluchaci sledovat kazdou myslenku bez namahy.",
            "Dnes popisuji jednoduche detaily beznymi slovy a nekolika mene obvyklymi zvuky.",
        ),
        "question": (
            "Zkontroloval jsi pred ulozenim, ze text odpovida nahravce?",
            "Muzeme tuto vetu zopakovat stejnym tonem a ze stejne vzdalenosti od mikrofonu?",
            "Zni kratka pauza po otazce prirozeneji?",
        ),
        "numbers": (
            "Na stole jsou 3 tuzky, 12 listu a 24 malych stitku.",
            "Toto cteni ma trvat asi 30 sekund, ne 10 a ne 90.",
            "V 8:15 pripravim kratkou poznamku a pak prectu jeste 2.",
        ),
        "names": (
            "Marta a Daniel se divaji do zahrady, zatimco Nora rovna zidle.",
            "Julie, Matej a Klara voli jednoducha slova, aby vysvetlili napad.",
            "Leo ceka u dveri a potom se klidne vraci dovnitr.",
        ),
        "punctuation": (
            "Dobre, pokracujme v klidu! Potom se na chvili zastavime.",
            "Nejprve prectu vetu; potom zkontroluji dech, rytmus a zretelnost.",
            "Poznamka: hlasitost ma zustat stabilni, bez tlaceni na hlas.",
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
            "A szoba csendes, es a hang egyenletes marad.",
            "Kinyitom a fuzetet, es nyugodtan olvasom a kovetkezo sort.",
            "A lassu, biztos tempo minden szot erthetobbe tesz.",
        ),
        "medium": (
            "Amikor a szoveg hosszabb lesz, tartom az egyenletes ritmust es termeszetesen lelegzem.",
            "A tiszta beszed segit a hallgatonak kovetni minden gondolatot.",
            "Ma egyszeru reszleteket irok le gyakori szavakkal es nehany ritkabb hanggal.",
        ),
        "question": (
            "Ellenorizted, hogy a szoveg megegyezik a hanggal mentes elott?",
            "Meg tudjuk ismetelni ezt a mondatot ugyanazzal a hangszinnel es mikrofontavolsaggal?",
            "Termeszetesebben hangzik egy rovid szunet a kerdes utan?",
        ),
        "numbers": (
            "Az asztalon 3 ceruza, 12 lap es 24 kis cimke van.",
            "Ez a felolvasas korulbelul 30 masodpercig tart, nem 10 es nem 90.",
            "8:15-kor keszitek egy rovid jegyzetet, majd meg 2-t felolvasok.",
        ),
        "names": (
            "Marta es Daniel a kertet nezi, mikozben Nora elrendezi a szekeket.",
            "Julia, Mateo es Klara egyszeru szavakat valaszt az otlet magyarazatahoz.",
            "Leo az ajto mellett var, aztan nyugodtan visszamegy.",
        ),
        "punctuation": (
            "Rendben, folytassuk nyugodtan! Utana megallunk egy pillanatra.",
            "Eloszor felolvasom a mondatot; utana figyelem a lelegzetet, a ritmust es a tisztasagot.",
            "Megjegyzes: a hangeronek stabilnak kell maradnia, eroltetes nelkul.",
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

    prompt = build_prompt_from_corpus(corpus, seed=len(used_texts), max_chars=max_chars)
    return GeneratedModelingPrompt(
        text=prompt,
        language_code=language_key,
        corpus_version=MODELING_PROMPT_CORPUS_VERSION,
        source=MODELING_PROMPT_SOURCE_GENERATED,
    )


def build_prompt_from_corpus(corpus: ModelingPromptCorpus, *, seed: int, max_chars: int) -> str:
    selected: list[str] = []
    for slot_index, slot_name in enumerate(PROMPT_SLOT_ORDER):
        slot = corpus[slot_name]
        sentence = slot[slot_sentence_index(seed, corpus, slot_index, len(slot))]
        candidate = normalize_prompt_text(" ".join((*selected, sentence)))
        if len(candidate) <= max_chars:
            selected.append(sentence)
    if selected:
        return normalize_prompt_text(" ".join(selected))

    fallback = corpus["short"][seed % len(corpus["short"])]
    return normalize_prompt_text(fallback[:max_chars])


def slot_sentence_index(seed: int, corpus: ModelingPromptCorpus, slot_index: int, slot_length: int) -> int:
    if slot_length <= 1:
        return 0
    divisor = 1
    for previous_slot in PROMPT_SLOT_ORDER[:slot_index]:
        divisor *= max(1, len(corpus[previous_slot]))
    return (seed // divisor) % slot_length


def modeling_prompt_variant_count(corpus: ModelingPromptCorpus) -> int:
    count = 1
    for slot_name in PROMPT_SLOT_ORDER:
        count *= max(1, len(corpus[slot_name]))
    return count


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
