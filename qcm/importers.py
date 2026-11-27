import re

LETTERS = "ABCDEFGH"

# Garde-fous contre les fichiers piégés (bombes de décompression, documents géants).
# Les fichiers DOCX/XLSX sont des archives ZIP : 15 Mo compressés peuvent en faire des Go.
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_PDF_PAGES = 300
MAX_XLSX_ROWS = 2000
MAX_XLSX_COLS = 20
MAX_QUESTIONS = 500
MAX_TEXT_LENGTH = 5000


def _check_zip_archive(data, label):
    """Refuse une archive Office dont la taille décompressée déclarée est excessive."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile:
        raise ValueError(f"Fichier {label} invalide ou corrompu.")
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError(f"Fichier {label} trop volumineux une fois décompressé.")


def _read_xlsx_rows(data, label):
    """Lit au plus MAX_XLSX_ROWS lignes et MAX_XLSX_COLS colonnes, sans tout charger en mémoire."""
    import io
    from itertools import islice
    from openpyxl import load_workbook
    _check_zip_archive(data, label)
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        try:
            rows = list(islice(wb.active.iter_rows(values_only=True, max_col=MAX_XLSX_COLS), MAX_XLSX_ROWS + 1))
        finally:
            wb.close()
    except Exception as exc:
        raise ValueError(f"Lecture du fichier {label} impossible : {exc}")
    if len(rows) > MAX_XLSX_ROWS:
        raise ValueError(f"Le fichier {label} dépasse {MAX_XLSX_ROWS} lignes.")
    return rows


def _normalise_answer(value):
    if value is None:
        return []
    text = str(value).strip().upper()
    if not text:
        return []
    text = re.sub(r"^(REPONSE|RÉPONSE|CORRECTE?|BONNE REPONSE|ANSWER)\s*[:=-]\s*", "", text)
    found = re.findall(r"\b([A-H])\b", text)
    return sorted(set(found), key=LETTERS.index)


def parse_answer_key(text):
    answers = {}
    current_number = None
    for line in text.splitlines():
        line = line.strip()
        qmatch = re.match(r"^(?:QUESTION\s*)?Q?\s*(\d{1,3})\s*[\.\):\-]", line, re.I)
        if qmatch:
            current_number = int(qmatch.group(1))
        standalone = re.search(r"(?:BONNE\s+)?R[ÉE]PONSE\s*[:=\-]\s*([A-H](?:\s*[,;/+]\s*[A-H])*)", line, re.I)
        if standalone and current_number is not None:
            answers[current_number] = _normalise_answer(standalone.group(1))
            continue
        m = re.search(r"(?:QUESTION\s*)?Q?\s*(\d{1,3})\s*[\.\):\-].{0,35}?(?:R[ÉE]PONSE|ANSWER)\s*[:=]\s*([A-H](?:\s*[,;/+]\s*[A-H])*)", line, re.I)
        if m:
            answers[int(m.group(1))] = _normalise_answer(m.group(2))
    return answers


def parse_text_questions(text):
    # Supports common layouts: "1. Question", "Q1. Question", followed by A) ... D).
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.replace("\x0c", "\n").splitlines()]
    lines = [x for x in lines if x]
    starts = []
    for i, line in enumerate(lines):
        m = re.match(r"^(?:QUESTION\s*)?Q?\s*(\d{1,3})\s*[\.\):\-]\s*(.*)$", line, re.I)
        if m:
            starts.append((i, int(m.group(1)), m.group(2)))
    questions = []
    if starts:
        for j, (idx, number, first) in enumerate(starts):
            end = starts[j+1][0] if j+1 < len(starts) else len(lines)
            block = ([first] if first else []) + lines[idx+1:end]
            stem, opts, correct = [], {}, []
            for line in block:
                am = re.match(r"^(?:BONNE\s+)?R[ÉE]PONSE\s*[:=]\s*(.+)$", line, re.I)
                if am:
                    correct = _normalise_answer(am.group(1))
                    continue
                m = re.match(r"^([A-H])\s*[\)\].:\-]\s*(.*)$", line, re.I)
                if m:
                    opts[m.group(1).upper()] = m.group(2).strip()
                elif opts:
                    last = list(opts.keys())[-1]
                    opts[last] = (opts[last] + " " + line).strip()
                else:
                    stem.append(line)
            if len(opts) >= 2 and stem:
                questions.append({
                    "number": number,
                    "text": " ".join(stem).strip(),
                    "options": [{"letter": k, "text": v} for k, v in opts.items()],
                    "correct": correct,
                })
    if not questions:
        raise ValueError("Aucune question détectée. Vérifiez la mise en forme du document : numéro de question puis propositions A), B), C), D).")
    return questions


def extract_text(uploaded):
    name = uploaded.name.lower()
    data = uploaded.read()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError(f"Le PDF dépasse {MAX_PDF_PAGES} pages.")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ValueError(f"Lecture PDF impossible : {exc}")
    if name.endswith(".docx"):
        _check_zip_archive(data, "Word")
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" ".join(cell.text for cell in row.cells))
            return "\n".join(parts)
        except Exception as exc:
            raise ValueError(f"Lecture Word impossible : {exc}")
    if name.endswith((".xlsx", ".xlsm")):
        return None
    raise ValueError("Format non pris en charge. Utilisez PDF, DOCX ou XLSX.")


def parse_xlsx(uploaded):
    rows = _read_xlsx_rows(uploaded.read(), "Excel")
    if not rows:
        raise ValueError("Le fichier Excel est vide.")
    header = [str(x or "").strip().lower() for x in rows[0]]
    known = {"question", "énoncé", "enonce", "a", "b", "c", "d", "réponse", "reponse", "correcte"}
    has_header = any(x in known for x in header)
    data = rows[1:] if has_header else rows
    if has_header:
        def col(*names):
            for n in names:
                if n in header:
                    return header.index(n)
            return None
        qi = col("question", "énoncé", "enonce")
        # L'en-tête est passé en minuscules : chercher "a", "b"… et non "A", "B"…
        option_cols = [col(x.lower()) for x in LETTERS[:4]]
        ai = col("réponse", "reponse", "correcte")
    else:
        qi, option_cols, ai = 0, [1,2,3,4], 5
    if qi is None:
        raise ValueError("La colonne Question/Énoncé est introuvable dans le fichier Excel.")
    result = []
    for number, row in enumerate(data, 1):
        if qi >= len(row) or not row[qi]:
            continue
        opts = []
        for letter, ci in zip(LETTERS, option_cols):
            if ci is not None and ci < len(row) and row[ci] is not None:
                opts.append({"letter": letter, "text": str(row[ci]).strip()})
        if len(opts) < 2:
            continue
        correct = _normalise_answer(row[ai]) if ai is not None and ai < len(row) else []
        result.append({"number": number, "text": str(row[qi]).strip(), "options": opts, "correct": correct})
    if not result:
        raise ValueError("Aucune ligne de question exploitable. Consultez le modèle Excel fourni dans l'aide.")
    return result


def parse_uploaded_questions(uploaded):
    if uploaded.name.lower().endswith((".xlsx", ".xlsm")):
        questions = parse_xlsx(uploaded)
    else:
        questions = parse_text_questions(extract_text(uploaded))
    # Le résultat est stocké en session pour la prévisualisation : on borne sa taille.
    if len(questions) > MAX_QUESTIONS:
        raise ValueError(f"Le sujet contient plus de {MAX_QUESTIONS} questions. Découpez-le en plusieurs examens.")
    for q in questions:
        q["text"] = q["text"][:MAX_TEXT_LENGTH]
        for option in q["options"]:
            option["text"] = option["text"][:500]
    return questions



def parse_answer_key_xlsx(uploaded):
    rows = _read_xlsx_rows(uploaded.read(), "corrigé Excel")
    if not rows:
        raise ValueError("Le corrigé Excel est vide.")
    header = [str(x or "").strip().lower() for x in rows[0]]
    qcol = next((i for i, x in enumerate(header) if x in ("question", "numéro", "numero", "n°")), 0)
    acol = next((i for i, x in enumerate(header) if x in ("réponse", "reponse", "correcte", "answer")), 1)
    answers = {}
    for row in rows[1:]:
        try:
            number = int(row[qcol])
            answers[number] = _normalise_answer(row[acol] if acol < len(row) else None)
        except (ValueError, TypeError, IndexError):
            continue
    return answers

def apply_answer_key(questions, key_text):
    key = parse_answer_key(key_text)
    for q in questions:
        q["correct"] = key.get(q["number"], [])
    return questions
