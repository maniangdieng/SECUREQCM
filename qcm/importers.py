import json
import re
from decimal import Decimal
from pathlib import Path

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
MAX_OPTION_LENGTH = 500
MIN_POINTS, MAX_POINTS = Decimal("0.1"), Decimal("100")  # mêmes bornes que la saisie manuelle


class InvalidQuestions(ValueError):
    """Au moins une question est invalide : rien n'est importé."""

    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


def _check_question_count(count):
    # Le résultat est stocké en session pour la prévisualisation : on borne sa taille.
    if count > MAX_QUESTIONS:
        raise ValueError(f"Le sujet contient plus de {MAX_QUESTIONS} questions. Découpez-le en plusieurs examens.")


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
            stem, opts, correct, errors = [], {}, [], []
            for line in block:
                am = re.match(r"^(?:BONNE\s+)?R[ÉE]PONSE\s*[:=]\s*(.+)$", line, re.I)
                if am:
                    correct = _normalise_answer(am.group(1))
                    continue
                m = re.match(r"^([A-H])\s*[\)\].:\-]\s*(.*)$", line, re.I)
                if m:
                    letter = m.group(1).upper()
                    if letter in opts:
                        errors.append(f"proposition {letter} en double")
                    opts[letter] = m.group(2).strip()
                elif opts:
                    last = list(opts.keys())[-1]
                    opts[last] = (opts[last] + " " + line).strip()
                else:
                    stem.append(line)
            questions.append({
                "number": number,
                "text": " ".join(stem).strip(),
                "options": [{"letter": k, "text": v} for k, v in opts.items()],
                "correct": correct,
                "errors": errors,
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
        option_cols = [col(x.lower()) for x in LETTERS]
        ai = col("réponse", "reponse", "correcte")
    else:
        qi, option_cols, ai = 0, [1,2,3,4], 5
    if qi is None:
        raise ValueError("La colonne Question/Énoncé est introuvable dans le fichier Excel.")

    def cell(row, index):
        if index is None or index >= len(row) or row[index] is None:
            return ""
        return str(row[index]).strip()

    result = []
    for number, row in enumerate(data, 1):
        text = cell(row, qi)
        opts = [{"letter": letter, "text": cell(row, ci)} for letter, ci in zip(LETTERS, option_cols) if cell(row, ci)]
        answer = cell(row, ai)
        if not (text or opts or answer):
            continue  # ligne vide : ce n'est pas une question
        result.append({"number": number, "line": number + has_header, "text": text, "options": opts,
                       "correct": _normalise_answer(answer)})
    if not result:
        raise ValueError("Aucune ligne de question exploitable. Consultez le modèle Excel fourni dans l'aide.")
    return result


def _json_question(number, item):
    if not isinstance(item, dict):
        return {"number": number, "invalid": "format invalide (un objet est attendu)", "correct": []}
    errors, options, correct = [], [], []
    raw_options = item.get("options")
    raw_options = raw_options if isinstance(raw_options, list) else []
    if len(raw_options) > len(LETTERS):
        errors.append(f"plus de {len(LETTERS)} propositions")
    for letter, option in zip(LETTERS, raw_options):
        option = option if isinstance(option, dict) else {}
        text = option.get("text")
        options.append({"letter": letter, "text": text.strip() if isinstance(text, str) else ""})
        is_correct = option.get("correct", False)
        if not isinstance(is_correct, bool):
            errors.append(f"proposition {letter} : « correct » doit valoir true ou false")
        elif is_correct:
            correct.append(letter)
    text = item.get("text")
    question = {"number": number, "text": text.strip() if isinstance(text, str) else "",
                "options": options, "correct": correct, "errors": errors}
    if item.get("type") is not None:
        if item["type"] in ("SINGLE", "MULTIPLE"):
            question["type"] = item["type"]
        else:
            errors.append("type inconnu (SINGLE ou MULTIPLE)")
    raw_points = item.get("points", 1)
    points = Decimal(str(raw_points)) if type(raw_points) in (int, float) else None
    if (points is None or not points.is_finite() or not MIN_POINTS <= points <= MAX_POINTS
            or points != points.quantize(Decimal("0.01"))):
        errors.append("barème invalide (nombre entre 0.1 et 100, deux décimales au plus)")
    else:
        question["points"] = str(points)
    return question


def parse_json(raw):
    """Lit {"questions": [{"text", "type", "points", "options": [{"text", "correct"}]}]}.

    Renvoie (document, questions). Les défauts de chaque question sont notés pour check_questions().
    """
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"Fichier JSON illisible : {exc}")
    items = document.get("questions") if isinstance(document, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Le fichier JSON doit contenir une liste « questions » non vide.")
    _check_question_count(len(items))  # avant de construire quoi que ce soit
    return document, [_json_question(number, item) for number, item in enumerate(items, 1)]


def _text_errors(label, text, limit):
    if len(text) > limit:
        return [f"{label} de plus de {limit} caractères"]
    # NUL (refusé par PostgreSQL) et demi-codets UTF-16 isolés (inaffichables), possibles en JSON.
    if any(c == "\x00" or "\ud800" <= c <= "\udfff" for c in text):
        return [f"{label} : caractère non autorisé"]
    return []


def _question_errors(question):
    if "invalid" in question:
        return [question["invalid"]]
    errors = list(question.get("errors", []))
    if not question["text"]:
        errors.append("énoncé vide")
    errors += _text_errors("énoncé", question["text"], MAX_TEXT_LENGTH)
    if len(question["options"]) < 2:
        errors.append("au moins deux propositions sont nécessaires")
    for option in question["options"]:
        if not option["text"]:
            errors.append(f"proposition {option['letter']} vide")
        errors += _text_errors(f"proposition {option['letter']}", option["text"], MAX_OPTION_LENGTH)
    letters = {option["letter"] for option in question["options"]}
    for letter in question["correct"]:
        if letter not in letters:
            errors.append(f"la réponse {letter} ne correspond à aucune proposition")
    if question.get("type") == "SINGLE" and len(question["correct"]) > 1:
        errors.append("une question à réponse unique ne peut avoir qu'une bonne réponse")
    return errors


def check_questions(questions):
    """À appeler une fois les bonnes réponses connues : tout ou rien, chaque défaut est signalé."""
    _check_question_count(len(questions))
    errors = []
    for question in questions:
        label = f"Question {question['number']}"
        if "line" in question:
            label += f" (ligne {question['line']})"
        errors += [f"{label} : {reason}" for reason in _question_errors(question)]
    if errors:
        raise InvalidQuestions(errors)


def parse_uploaded_questions(uploaded):
    """Lit le sujet sans le valider : l'appelant doit ensuite passer par check_questions()."""
    name = uploaded.name.lower()
    if name.endswith(".json"):
        return parse_json(uploaded.read())[1]
    if name.endswith((".xlsx", ".xlsm")):
        return parse_xlsx(uploaded)
    if name.endswith((".pdf", ".docx")):
        return parse_text_questions(extract_text(uploaded))
    raise ValueError("Format non pris en charge. Utilisez PDF, DOCX, XLSX ou JSON.")


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
