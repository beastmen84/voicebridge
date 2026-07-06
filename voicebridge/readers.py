import importlib
import io
import os
import re
from contextlib import suppress
from typing import Any

from docx import Document
from pypdf import PdfReader
from pypdf.errors import PyPdfError

try:
    import pywintypes

    WordComError = pywintypes.com_error
except ImportError:
    pywintypes = None

    class WordComError(Exception):
        pass

try:
    from langdetect import DetectorFactory, detect_langs
    from langdetect.lang_detect_exception import LangDetectException

    DetectorFactory.seed = 0
except ImportError:
    DetectorFactory = None
    detect_langs = None
    LangDetectException = Exception

from voicebridge.languages import normalize_language_code

SUPPORTED_FILETYPES = [
    ("Supported files", "*.docx *.doc *.txt *.pdf"),
    ("Word documents", "*.docx *.doc"),
    ("Text files", "*.txt"),
    ("PDF files", "*.pdf"),
    ("All files", "*.*"),
]

LANGUAGE_DETECTION_SAMPLE_LIMIT = 12000
MIN_LANGUAGE_ALPHA_CHARS = 40
MIN_PDF_PAGE_ALPHA_CHARS = 6
MIN_LANGUAGE_CONFIDENCE = 0.55
PDF_OCR_DPI = 200
TESSERACT_LANGUAGE_PREFERENCE = ("eng", "ita", "fra", "deu", "spa", "por")
TESSERACT_WINDOWS_INSTALL_URL = "https://github.com/UB-Mannheim/tesseract/wiki"
TESSERACT_WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
TESSERACT_NOT_INSTALLED_TEXT = "Tesseract OCR is not installed or is not available in PATH."
WORD_REQUIRED_TEXT = "This requires Microsoft Word installed."
PDF_NUMBERED_ITEM_RE = re.compile(r"^\s*\d{1,3}(?:[.)])?\s+\S")
PDF_UPPER_HEADING_RE = re.compile(r"^[A-ZÀ-ÖØ-Þ0-9][A-ZÀ-ÖØ-Þ0-9 '’().,-]{0,80}$")


def alphabetic_char_count(text):
    return len(re.findall(r"[^\W\d_]", text, flags=re.UNICODE))


def text_for_language_detection(text):
    lines = []

    for line in clean_text(text).splitlines():
        if alphabetic_char_count(line) >= 2:
            lines.append(line)

    # langdetect is surprisingly case-sensitive on short technical documents:
    # all-caps Italian headings can be scored as English with near-total confidence.
    return "\n".join(lines).casefold()


def detect_text_language(text):
    sample = text_for_language_detection(text)[:LANGUAGE_DETECTION_SAMPLE_LIMIT]
    if not sample:
        return None, 0.0

    if alphabetic_char_count(sample) < MIN_LANGUAGE_ALPHA_CHARS:
        return None, 0.0

    if detect_langs is None:
        return None, 0.0

    try:
        detected_languages = detect_langs(sample)
    except LangDetectException:
        return None, 0.0

    if not detected_languages:
        return None, 0.0

    best_match = detected_languages[0]
    language_code = normalize_language_code(best_match.lang)
    confidence = float(best_match.prob)

    if confidence < MIN_LANGUAGE_CONFIDENCE:
        return None, confidence

    return language_code, confidence


def read_txt(path):
    # Try common encodings so TXT files from different systems can be opened.
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]

    for enc in encodings:
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    raise ValueError("Could not read TXT file with common encodings.")


def read_docx(path):
    # Extract non-empty paragraphs from modern Word documents.
    doc = Document(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def extract_pdf_page_text(page, page_number):
    try:
        plain_text = page.extract_text(extraction_mode="plain") or ""
    except (AttributeError, KeyError, PyPdfError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not extract text from PDF page {page_number}: {exc}") from exc

    try:
        layout_text = page.extract_text(extraction_mode="layout") or ""
    except (AttributeError, KeyError, PyPdfError, TypeError, ValueError):
        layout_text = ""

    if alphabetic_char_count(layout_text) > alphabetic_char_count(plain_text):
        return layout_text
    return plain_text


def pdf_line_starts_paragraph(line):
    return bool(PDF_NUMBERED_ITEM_RE.match(line) or PDF_UPPER_HEADING_RE.match(line))


def join_pdf_lines(previous, current):
    if previous.endswith("-"):
        return f"{previous[:-1]}{current}"
    return f"{previous} {current}"


def clean_pdf_text(text):
    # PDF extractors often return visual lines, not logical paragraphs.
    paragraphs = []
    current = ""

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line.strip())
        if not line:
            continue
        if not current:
            current = line
            continue
        if pdf_line_starts_paragraph(line):
            paragraphs.append(current)
            current = line
        else:
            current = join_pdf_lines(current, line)

    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs).strip()


def load_ocr_dependencies():
    missing_packages = []

    try:
        fitz_module = importlib.import_module("fitz")
    except ImportError:
        fitz_module = None
        missing_packages.append("pymupdf")

    try:
        pytesseract_module = importlib.import_module("pytesseract")
    except ImportError:
        pytesseract_module = None
        missing_packages.append("pytesseract")

    try:
        pil_image_module = importlib.import_module("PIL.Image")
    except ImportError:
        pil_image_module = None
        missing_packages.append("pillow")

    if missing_packages:
        raise RuntimeError(
            "Python OCR packages are missing: "
            f"{', '.join(missing_packages)}. "
            "Install them with requirements-ocr.txt."
        )

    assert fitz_module is not None
    assert pytesseract_module is not None
    assert pil_image_module is not None

    for tesseract_path in TESSERACT_WINDOWS_CANDIDATES:
        if os.path.isfile(tesseract_path):
            pytesseract_module.pytesseract.tesseract_cmd = tesseract_path
            break

    try:
        pytesseract_module.get_tesseract_version()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"{TESSERACT_NOT_INSTALLED_TEXT} "
            f"Download the Windows installer from {TESSERACT_WINDOWS_INSTALL_URL}."
        ) from exc

    return fitz_module, pytesseract_module, pil_image_module


def tesseract_language_config(pytesseract):
    try:
        installed_languages = set(pytesseract.get_languages(config=""))
    except (OSError, RuntimeError, ValueError):
        return "eng"

    selected_languages = [
        language for language in TESSERACT_LANGUAGE_PREFERENCE
        if language in installed_languages
    ]
    if selected_languages:
        return "+".join(selected_languages)

    fallback_languages = sorted(
        language for language in installed_languages
        if language != "osd"
    )
    return "+".join(fallback_languages[:1]) if fallback_languages else "eng"


def ocr_pdf_pages(path, page_numbers):
    fitz, pytesseract, image_module = load_ocr_dependencies()
    language_config = tesseract_language_config(pytesseract)
    extracted_pages = {}

    with fitz.open(path) as pdf_document:
        scale = PDF_OCR_DPI / 72
        matrix = fitz.Matrix(scale, scale)

        for page_number in page_numbers:
            page = pdf_document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_bytes = pixmap.tobytes("png")
            image = image_module.open(io.BytesIO(image_bytes))
            text = clean_text(
                pytesseract.image_to_string(image, lang=language_config)
            )

            if alphabetic_char_count(text) >= MIN_PDF_PAGE_ALPHA_CHARS:
                extracted_pages[page_number] = text

    return extracted_pages


def read_pdf(path):
    # Prefer selectable text; OCR is used only for pages that need it.
    reader = PdfReader(path)
    pages_by_number = {}
    pages_needing_ocr = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = extract_pdf_page_text(page, page_number)
        clean_page_text = clean_pdf_text(text)

        if alphabetic_char_count(clean_page_text) >= MIN_PDF_PAGE_ALPHA_CHARS:
            pages_by_number[page_number] = text
        else:
            pages_needing_ocr.append(page_number)

    ocr_error = None
    if pages_needing_ocr:
        try:
            pages_by_number.update(ocr_pdf_pages(path, pages_needing_ocr))
        except RuntimeError as exc:
            ocr_error = str(exc)
        except (OSError, ValueError) as exc:
            ocr_error = f"OCR failed: {exc}"

    if not pages_by_number:
        message = "No readable text was found in this PDF."
        if ocr_error:
            message = f"{message} OCR is unavailable: {ocr_error}"
        else:
            message = f"{message} If it is scanned or image-based, run OCR first."
        raise ValueError(message)

    return clean_pdf_text("\n".join(
        pages_by_number[page_number]
        for page_number in sorted(pages_by_number)
    ))


def read_doc_legacy(path):
    """
    Reads old .doc files using Microsoft Word.
    Requires Windows + Microsoft Word + pywin32.
    """
    try:
        import win32com.client
    except ImportError as exc:
        raise ValueError("Reading .doc files requires pywin32. Install with: pip install pywin32") from exc

    word: Any | None = None
    doc: Any | None = None

    try:
        word_app: Any = win32com.client.Dispatch("Word.Application")
        word = word_app
        word_app.Visible = False
        word_app.DisplayAlerts = 0

        document: Any = word_app.Documents.Open(os.path.abspath(path), ReadOnly=True)
        doc = document
        text = document.Content.Text
        return text.strip()

    except (WordComError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError(
            f"Could not read .doc file. {WORD_REQUIRED_TEXT}\n\n"
            f"Details: {exc}"
        ) from exc

    finally:
        if doc is not None:
            document: Any = doc
            with suppress(WordComError, OSError, RuntimeError, ValueError):
                document.Close(False)
        if word is not None:
            word_app: Any = word
            with suppress(WordComError, OSError, RuntimeError, ValueError):
                word_app.Quit()


def clean_text(text):
    # Normalize spacing and remove empty lines before sending text to TTS.
    lines = []

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        cleaned_line = re.sub(r"[ \t]+", " ", raw_line.strip())
        if cleaned_line:
            lines.append(cleaned_line)

    return "\n\n".join(lines).strip()


def read_input_file(path):
    # Choose the correct reader based on the selected file extension.
    ext = os.path.splitext(path)[1].lower()

    if ext in {".txt", ".md"}:
        text = read_txt(path)
    elif ext == ".docx":
        text = read_docx(path)
    elif ext == ".pdf":
        text = read_pdf(path)
    elif ext == ".doc":
        text = read_doc_legacy(path)
    else:
        raise ValueError(f"Unsupported file format: {ext or '(none)'}")

    return clean_text(text)


def file_signature(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None

    return (
        os.path.abspath(path),
        stat.st_mtime_ns,
        stat.st_size,
    )
