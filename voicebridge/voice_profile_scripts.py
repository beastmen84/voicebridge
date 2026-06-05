from voicebridge.recording_text import RECORDING_TEXT_BREAK_MARKS, format_recording_text_for_display
from voicebridge.voice_profiles import VOICE_PROFILE_LANGUAGES

VOICE_PROFILE_RECORDING_BREAK_MARKS = RECORDING_TEXT_BREAK_MARKS

VOICE_PROFILE_RECORDING_SCRIPTS = {
    "it": (
        "Oggi registriamo una voce chiara, naturale e costante. Prima leggo piano, poi con più energia: "
        "buongiorno, come stai? Attenzione, arriva una notizia importante! Nel 2026 abbiamo preparato tre versioni, "
        "due prove brevi e una finale. Ora faccio una pausa, respiro, e continuo con calma. Se qualcosa cambia, "
        "lo dico subito; se tutto è pronto, possiamo proteggere il lavoro e concludere."
    ),
    "en": (
        "Today we are recording a clear, natural, steady voice. First I read softly, then with more energy: "
        "good morning, how are you? Listen, this is important! In 2026 we prepared three versions, two short tests "
        "and one final take. Now I pause, breathe, and continue calmly. If something changes, I say it right away; "
        "if everything is ready, we protect the work and finish."
    ),
    "es": (
        "Hoy grabamos una voz clara, natural y constante. Primero leo despacio, luego con más energía: "
        "buenos días, cómo estás? Atención, llega una noticia importante! En 2026 preparamos tres versiones, "
        "dos pruebas breves y una toma final. Ahora hago una pausa, respiro y continuo con calma. Si algo cambia, "
        "lo digo enseguida; si todo está listo, protegemos el trabajo y terminamos."
    ),
    "fr": (
        "Aujourd'hui, nous enregistrons une voix claire, naturelle et régulière. Je lis d'abord doucement, "
        "puis avec plus d'énergie: bonjour, comment ça va? Attention, voici une information importante! En 2026, "
        "nous avons préparé trois versions, deux essais courts et une prise finale. Maintenant je fais une pause, "
        "je respire, et je continue calmement. Si quelque chose change, je le dis tout de suite; si tout est prêt, "
        "nous protégeons le travail et nous terminons."
    ),
    "de": (
        "Heute nehmen wir eine klare, natürliche und gleichmäßige Stimme auf. Zuerst lese ich ruhig, "
        "danach mit mehr Energie: guten Morgen, wie geht es dir? Achtung, jetzt kommt eine wichtige Nachricht! "
        "Im Jahr 2026 haben wir drei Versionen vorbereitet, zwei kurze Tests und eine finale Aufnahme. Jetzt mache "
        "ich eine Pause, atme ein, und spreche gelassen weiter. Wenn sich etwas ändert, sage ich es sofort; "
        "wenn alles bereit ist, sichern wir die Arbeit und schließen ab."
    ),
    "pt": (
        "Hoje vamos gravar uma voz clara, natural e constante. Primeiro leio devagar, depois com mais energia: "
        "bom dia, como você está? Atenção, vem uma notícia importante! Em 2026 preparamos três versões, "
        "dois testes curtos e uma tomada final. Agora faço uma pausa, respiro e continuo com calma. Se algo mudar, "
        "eu aviso imediatamente; se tudo estiver pronto, protegemos o trabalho e terminamos."
    ),
    "pl": (
        "Dzisiaj nagrywamy głos wyraźny, naturalny i równy. Najpierw czytam spokojnie, potem z większą energią: "
        "dzień dobry, jak się masz? Uwaga, to ważna wiadomość! W 2026 roku przygotowaliśmy trzy wersje, "
        "dwie krótkie próby i jedno nagranie finalne. Teraz robię pauzę, oddycham i mówię dalej spokojnie. "
        "Jeśli coś się zmieni, powiem od razu; jeśli wszystko jest gotowe, zabezpieczamy pracę i kończymy."
    ),
    "tr": (
        "Bugün net, doğal ve dengeli bir ses kaydediyoruz. Önce yavaş okuyorum, sonra daha enerjik: "
        "günaydın, nasılsın? Dikkat, önemli bir haber geliyor! 2026 yılında üç sürüm hazırladık, iki kısa deneme "
        "ve bir son kayıt. Şimdi kısa bir ara veriyorum, nefes alıyorum ve sakin devam ediyorum. Bir şey değişirse "
        "hemen söylerim; her şey hazırsa işi korur ve bitiririz."
    ),
    "ru": (
        "Сегодня мы записываем четкий, естественный и ровный голос. Сначала я читаю спокойно, потом энергичнее: "
        "доброе утро, как дела? Внимание, это важная новость! В 2026 году мы подготовили три версии, две короткие "
        "проверки и одну финальную запись. Сейчас я делаю паузу, дышу и продолжаю спокойно. Если что-то изменится, "
        "я скажу сразу; если все готово, мы сохраним работу и закончим."
    ),
    "nl": (
        "Vandaag nemen we een heldere, natuurlijke en gelijkmatige stem op. Eerst lees ik rustig, daarna met meer "
        "energie: goedemorgen, hoe gaat het? Let op, dit is een belangrijk bericht! In 2026 hebben we drie versies "
        "voorbereid, twee korte tests en een definitieve opname. Nu neem ik een pauze, adem ik rustig, en ga ik door. "
        "Als er iets verandert, zeg ik het meteen; als alles klaar is, bewaren we het werk en ronden we af."
    ),
    "cs": (
        "Dnes nahráváme jasný, přirozený a vyrovnaný hlas. Nejdříve čtu pomalu, potom s větší energií: "
        "dobré ráno, jak se máš? Pozor, přichází důležitá zpráva! V roce 2026 jsme připravili tři verze, "
        "dvě krátké zkoušky a jeden finální záběr. Teď udělám pauzu, nadechnu se a pokračuji klidně. "
        "Když se něco změní, řeknu to hned; když je vše připraveno, práci uložíme a skončíme."
    ),
    "ar": (
        "اليوم نسجل صوتا واضحا وطبيعيا وثابتا. في البداية اقرأ بهدوء، ثم بطاقة اكبر: صباح الخير، كيف حالك؟ "
        "انتبه، هذه معلومة مهمة! في عام 2026 اعددنا ثلاث نسخ، تجربتين قصيرتين وتسجيل نهائي واحد. الان اتوقف "
        "لحظة، اتنفس، ثم اكمل بهدوء. اذا تغير شيء، ساقوله فورا؛ واذا كان كل شيء جاهزا، نحفظ العمل وننهي التسجيل."
    ),
    "zh-cn": (
        "今天我们录制一段清晰、自然、稳定的声音。先慢慢读，然后更有精神一点：早上好，你好吗？请注意，"
        "这里有一条重要消息！在2026年，我们准备了三个版本，两个简短测试，还有一次最终录音。现在我停顿一下，"
        "呼吸，然后平稳地继续。如果情况改变，我会马上说明；如果一切准备好了，我们就保存工作并结束。"
    ),
    "ja": (
        "今日は、はっきりした自然で安定した声を録音します。最初はゆっくり読み、次に少し元気よく読みます。"
        "おはようございます、調子はどうですか？大切なお知らせです！2026年には三つの版、二つの短いテスト、"
        "そして最後の録音を用意しました。ここで少し休み、息を整えて、落ち着いて続けます。変化があればすぐ伝え、"
        "準備ができたら作業を保存して終わります。"
    ),
    "hu": (
        "Ma tiszta, természetes és egyenletes hangot rögzítünk. Először lassan olvasok, aztán több energiával: "
        "jó reggelt, hogy vagy? Figyelem, fontos hír következik! 2026-ban három változatot készítettünk, "
        "két rövid próbát és egy végső felvételt. Most tartok egy kis szünetet, levegőt veszek, "
        "és nyugodtan folytatom. "
        "Ha valami változik, azonnal jelzem; ha minden kész, megőrizzük a munkát és befejezzük."
    ),
    "ko": (
        "오늘은 또렷하고 자연스러우며 안정적인 목소리를 녹음합니다. 먼저 천천히 읽고, "
        "다음에는 조금 더 힘 있게 읽습니다. "
        "좋은 아침입니다, 잘 지내시나요? 중요한 소식이 있습니다! 2026년에 우리는 세 가지 버전, 짧은 시험 두 번, "
        "그리고 최종 녹음 하나를 준비했습니다. 이제 잠시 멈추고 숨을 고른 뒤 차분하게 이어 갑니다. "
        "변화가 있으면 바로 말하고, "
        "모든 준비가 끝나면 작업을 저장하고 마칩니다."
    ),
    "hi": (
        "आज हम एक साफ, स्वाभाविक और स्थिर आवाज रिकॉर्ड कर रहे हैं। पहले मैं धीरे पढ़ता हूं, फिर थोड़ी ऊर्जा के साथ: "
        "सुप्रभात, आप कैसे हैं? ध्यान दें, यह एक महत्वपूर्ण सूचना है! 2026 में हमने तीन संस्करण तैयार किए, दो छोटे परीक्षण "
        "और एक अंतिम रिकॉर्डिंग। अब मैं थोड़ा रुकता हूं, सांस लेता हूं, और शांत होकर आगे पढ़ता हूं। अगर कुछ बदलता है, "
        "तो मैं तुरंत बताऊंगा; अगर सब तैयार है, तो हम काम सुरक्षित करके समाप्त करेंगे।"
    ),
}


def voice_profile_recording_script(language_code: str) -> str:
    return VOICE_PROFILE_RECORDING_SCRIPTS.get(language_code, VOICE_PROFILE_RECORDING_SCRIPTS["en"])


def voice_profile_recording_script_for_display(language_code: str) -> str:
    return format_voice_profile_recording_script(voice_profile_recording_script(language_code))


def format_voice_profile_recording_script(script: str) -> str:
    return format_recording_text_for_display(script)


def voice_profile_recording_script_languages() -> set[str]:
    return set(VOICE_PROFILE_RECORDING_SCRIPTS)


assert voice_profile_recording_script_languages() == set(VOICE_PROFILE_LANGUAGES)
