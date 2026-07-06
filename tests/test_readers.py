from voicebridge.readers import clean_pdf_text


def test_clean_pdf_text_reflows_visual_lines_and_keeps_numbered_items() -> None:
    text = (
        "LIBRO I\n"
        "\n"
        "1 Da mia madre: la religiosità e anche all'idea di\n"
        "compierlo; ancora: il tenore di vita semplice.\n"
        "2 Dalla fama e dal ricordo di mio padre: il comportamento\n"
        "riservato e virile.\n"
    )

    assert clean_pdf_text(text) == (
        "LIBRO I\n\n"
        "1 Da mia madre: la religiosità e anche all'idea di compierlo; ancora: il tenore di vita semplice.\n\n"
        "2 Dalla fama e dal ricordo di mio padre: il comportamento riservato e virile."
    )


def test_clean_pdf_text_joins_page_continuations_without_numbered_heading() -> None:
    text = (
        "17 Dagli dèi: è un beneficio degli dèi che non si\n"
        "sia verificato nessun concorso di avvenimenti.\n"
        "LIBRO II\n"
        "1 Al mattino ricorda a te stesso quanto segue.\n"
    )

    assert clean_pdf_text(text) == (
        "17 Dagli dèi: è un beneficio degli dèi che non si sia verificato nessun concorso di avvenimenti.\n\n"
        "LIBRO II\n\n"
        "1 Al mattino ricorda a te stesso quanto segue."
    )
