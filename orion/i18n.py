# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""English and Italian, from one table.

Orion is written in English and translated into Italian here, by looking the
English up. That is the whole mechanism: :func:`tr` takes the string the code
already contains and returns the Italian for it, or the English back if the
language is English or the phrase has no translation yet.

Chosen over Qt's own ``QTranslator`` for two reasons that matter to this
project rather than in general. ``QTranslator`` reads compiled ``.qm`` files,
which are binary blobs that have to be built by a separate tool and shipped in
the bundle — and Orion deliberately has none, down to drawing its icons in
code. And a missing translation in a ``.qm`` is silent, whereas a plain dict
can be, and is, checked by a test that walks the real window and fails on any
English left showing.

The keys are the English source strings, keyboard accelerators and all. An
ampersand is part of the string because it is part of what the user sees: the
Italian needs its own, on a letter the Italian word actually has.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["Language", "current_language", "detect_language", "set_language", "tr"]


class Language(str, Enum):
    ENGLISH = "en"
    ITALIAN = "it"

    @property
    def label(self) -> str:
        """The language's name in itself, which is how a picker should read."""
        return "Italiano" if self is Language.ITALIAN else "English"


def detect_language(locale_name: str | None) -> Language:
    """Italian for an Italian system, English for everything else.

    Takes the locale as a string — ``"it_IT"``, ``"it-CH"``, ``"en_GB"`` — so
    this module needs no Qt to answer, and the caller passes whatever its
    platform reports. A missing or unreadable locale is English, which is the
    same answer as for any other language and needs no special case.
    """
    if not locale_name:
        return Language.ENGLISH
    return Language.ITALIAN if locale_name.lower().startswith("it") else Language.ENGLISH


_language: Language = Language.ENGLISH


def set_language(language: Language | str) -> None:
    global _language
    _language = Language(language)


def current_language() -> Language:
    return _language


def tr(text: str) -> str:
    """The Italian for *text*, or *text* itself.

    Returning the English rather than raising is deliberate: a phrase nobody
    has translated yet should look untranslated, not stop the window from
    opening. The test suite is where a gap is meant to be caught.
    """
    if _language is Language.ENGLISH:
        return text
    return _CATALOGUE.get(text, text)


#: English source string -> Italian. Everything the user can read.
_CATALOGUE: dict[str, str] = {
    # -- menu bar ---------------------------------------------------------
    "&File": "&File",
    "&Edit": "&Modifica",
    "&View": "&Visualizza",
    "&Pages": "&Pagine",
    "&Tools": "&Strumenti",
    "&Help": "&Aiuto",
    "&Theme": "&Tema",
    "&Language": "&Lingua",
    "Open &Recent": "Apri &recenti",
    # -- file -------------------------------------------------------------
    "&New Document": "&Nuovo documento",
    "Create an empty document": "Crea un documento vuoto",
    "&Open…": "&Apri…",
    "Open a PDF document": "Apre un documento PDF",
    "&Close Document": "&Chiudi documento",
    "Close the current document": "Chiude il documento corrente",
    "&Save": "&Salva",
    "Save the document": "Salva il documento",
    "Save &As…": "Salva con &nome…",
    "Save the document under a new name": "Salva il documento con un altro nome",
    "&Merge PDF…": "&Unisci PDF…",
    "Combine several PDF files into one": "Unisce più file PDF in uno solo",
    "Clear Recent Files": "Svuota i file recenti",
    "Forget the list of recently opened files": "Dimentica l'elenco dei file aperti di recente",
    "Export as &Images…": "Esporta come &immagini…",
    "Save pages as PNG or JPEG files": "Salva le pagine come file PNG o JPEG",
    "Document &Properties…": "&Proprietà del documento…",
    "Read and edit the document's title, author and keywords": (
        "Legge e modifica titolo, autore e parole chiave del documento"
    ),
    "&Quit": "&Esci",
    "Close Orion": "Chiude Orion",
    # -- edit -------------------------------------------------------------
    "&Undo": "&Annulla",
    "Undo the last change": "Annulla l'ultima modifica",
    "&Redo": "&Ripeti",
    "Redo the last undone change": "Ripete l'ultima modifica annullata",
    "Cu&t": "&Taglia",
    "Cut the selected objects": "Taglia gli oggetti selezionati",
    "&Copy": "&Copia",
    "Copy the selected objects": "Copia gli oggetti selezionati",
    "&Paste": "&Incolla",
    "Paste objects onto the current page": "Incolla gli oggetti nella pagina corrente",
    "&Duplicate": "&Duplica",
    "Duplicate the selected objects": "Duplica gli oggetti selezionati",
    "Delete": "Elimina",
    "Delete the selected objects": "Elimina gli oggetti selezionati",
    "Select &All on Page": "Seleziona &tutto nella pagina",
    "Select every object on this page": "Seleziona ogni oggetto di questa pagina",
    "Deselect": "Deseleziona",
    "Clear the selection": "Annulla la selezione",
    "Bring to &Front": "Porta in &primo piano",
    "Move the object above the others": "Porta l'oggetto sopra gli altri",
    "Send to &Back": "Porta in &secondo piano",
    "Move the object below the others": "Porta l'oggetto sotto gli altri",
    # -- view -------------------------------------------------------------
    "Zoom &In": "&Ingrandisci",
    "Zoom in": "Ingrandisce",
    "Zoom &Out": "&Riduci",
    "Zoom out": "Riduce",
    "Actual Size": "Dimensione reale",
    "Show the page at 100%": "Mostra la pagina al 100%",
    "Fit &Page": "Adatta &pagina",
    "Fit the whole page in the window": "Adatta l'intera pagina alla finestra",
    "Fit &Width": "Adatta &larghezza",
    "Fit the page width to the window": "Adatta la larghezza della pagina alla finestra",
    "&First Page": "&Prima pagina",
    "Go to the first page": "Va alla prima pagina",
    "&Previous Page": "Pagina &precedente",
    "Go to the previous page": "Va alla pagina precedente",
    "&Next Page": "Pagina &successiva",
    "Go to the next page": "Va alla pagina successiva",
    "&Last Page": "&Ultima pagina",
    "Go to the last page": "Va all'ultima pagina",
    "&Go to Page…": "&Vai alla pagina…",
    "Jump to a page number": "Salta a un numero di pagina",
    "&Find…": "&Trova…",
    "Search for text": "Cerca del testo",
    "Find Next": "Trova successivo",
    "Go to the next match": "Va al risultato successivo",
    "Find Previous": "Trova precedente",
    "Go to the previous match": "Va al risultato precedente",
    "&Thumbnails": "&Miniature",
    "Show or hide the page thumbnails": "Mostra o nasconde le miniature delle pagine",
    "&Properties Panel": "Pannello &proprietà",
    "Show or hide the properties panel": "Mostra o nasconde il pannello delle proprietà",
    "&Light Theme": "Tema &chiaro",
    "Use the light theme": "Usa il tema chiaro",
    "&Dark Theme": "Tema &scuro",
    "Use the dark theme": "Usa il tema scuro",
    "Match &System": "Come il &sistema",
    "Follow the desktop's light or dark setting": (
        "Segue l'impostazione chiara o scura del sistema"
    ),
    # -- pages ------------------------------------------------------------
    "&Insert Blank Page…": "&Inserisci pagina vuota…",
    "Add an empty page": "Aggiunge una pagina vuota",
    "&Duplicate Page": "&Duplica pagina",
    "Duplicate the current page": "Duplica la pagina corrente",
    "De&lete Page": "E&limina pagina",
    "Delete the selected pages": "Elimina le pagine selezionate",
    "Rotate &Left": "Ruota a &sinistra",
    "Rotate the selected pages 90° left": "Ruota di 90° a sinistra le pagine selezionate",
    "Rotate &Right": "Ruota a &destra",
    "Rotate the selected pages 90° right": "Ruota di 90° a destra le pagine selezionate",
    "Rotate 180°": "Ruota di 180°",
    "Turn the selected pages upside down": "Capovolge le pagine selezionate",
    "Move Page &Up": "Sposta pagina in &alto",
    "Move the current page earlier": "Sposta la pagina corrente più indietro",
    "Move Page D&own": "Sposta pagina in &basso",
    "Move the current page later": "Sposta la pagina corrente più avanti",
    "I&mport Pages…": "I&mporta pagine…",
    "Insert pages from another PDF": "Inserisce pagine da un altro PDF",
    "&Extract Pages…": "&Estrai pagine…",
    "Save selected pages as a new PDF": "Salva le pagine selezionate come nuovo PDF",
    "&Split PDF…": "&Dividi PDF…",
    "Split this document into several files": "Divide questo documento in più file",
    # -- tools ------------------------------------------------------------
    "Insert &Image…": "Inserisci &immagine…",
    "Place an image on the page": "Inserisce un'immagine nella pagina",
    "&Edit Text Object": "&Modifica oggetto di testo",
    "Edit the selected text object": "Modifica l'oggetto di testo selezionato",
    "&Watermark…": "&Filigrana…",
    "Stamp a word across a range of pages": "Imprime una parola su un intervallo di pagine",
    "Page &Numbers…": "&Numeri di pagina…",
    "Number a range of pages": "Numera un intervallo di pagine",
    "Edit &Comment…": "Modifica &commento…",
    "Edit the selected annotation's comment": "Modifica il commento dell'annotazione selezionata",
    # -- help -------------------------------------------------------------
    "&Find a Command…": "&Cerca un comando…",
    "Search every command by name": "Cerca per nome fra tutti i comandi",
    "&Keyboard Shortcuts": "&Scorciatoie da tastiera",
    "List the keyboard shortcuts": "Elenca le scorciatoie da tastiera",
    "Open &Log Folder": "Apri cartella dei &log",
    "Open the folder containing Orion's log file": "Apre la cartella con il file di log di Orion",
    "&About Orion": "&Informazioni su Orion",
    "About this application": "Informazioni su questa applicazione",
    # -- the tool palette -------------------------------------------------
    "Select": "Seleziona",
    "Select, move and resize objects": "Seleziona, sposta e ridimensiona gli oggetti",
    "Pan": "Scorri",
    "Drag to scroll the page": "Trascina per scorrere la pagina",
    "Text": "Testo",
    "Click or drag to add a text box": "Clicca o trascina per aggiungere una casella di testo",
    "Image": "Immagine",
    "Click to place an image": "Clicca per inserire un'immagine",
    "Rectangle": "Rettangolo",
    "Drag to draw a rectangle": "Trascina per disegnare un rettangolo",
    "Ellipse": "Ellisse",
    "Drag to draw an ellipse": "Trascina per disegnare un'ellisse",
    "Line": "Linea",
    "Drag to draw a line": "Trascina per disegnare una linea",
    "Arrow": "Freccia",
    "Drag to draw an arrow": "Trascina per disegnare una freccia",
    "Highlight": "Evidenzia",
    "Drag across text to highlight it": "Trascina sul testo per evidenziarlo",
    "Underline": "Sottolinea",
    "Drag across text to underline it": "Trascina sul testo per sottolinearlo",
    "Strikeout": "Barra",
    "Drag across text to strike it out": "Trascina sul testo per barrarlo",
    "Freehand": "Mano libera",
    "Draw freely with the mouse": "Disegna liberamente con il mouse",
    "Sticky Note": "Nota",
    "Click to place a note": "Clicca per inserire una nota",
    "Redact": "Oscura",
    "Drag over anything that must be removed from the saved file": (
        "Trascina su ciò che deve sparire dal file salvato"
    ),
    # -- panels and the status bar ----------------------------------------
    "Properties": "Proprietà",
    "Pages": "Pagine",
    "Tools": "Strumenti",
    "Main": "Principale",
    "Select an object to edit its properties.": (
        "Seleziona un oggetto per modificarne le proprietà."
    ),
    "Ready": "Pronto",
    "Modified": "Modificato",
    "Current page": "Pagina corrente",
    "Zoom": "Zoom",
    "Fit Page": "Adatta pagina",
    "Fit Width": "Adatta larghezza",
    "Custom": "Personalizzato",
    # -- everything else the user can read -----------------------------
    'A document must keep at least one page.': 'Un documento deve conservare almeno una pagina.',
    'A3 (297 × 420 mm)': 'A3 (297 × 420 mm)',
    'A4 (210 × 297 mm)': 'A4 (210 × 297 mm)',
    'A5 (148 × 210 mm)': 'A5 (148 × 210 mm)',
    'Add Current Document': 'Aggiungi il documento corrente',
    'Add Files…': 'Aggiungi file…',
    'Add at least two documents.': 'Aggiungi almeno due documenti.',
    'After current page': 'Dopo la pagina corrente',
    'Alignment': 'Allineamento',
    'Also in the file': 'Altro nel file',
    'Angle': 'Inclinazione',
    'Annotation': 'Annotazione',
    'Annotation Colour': "Colore dell'annotazione",
    'Arrange': 'Disponi',
    'At the beginning': "All'inizio",
    'At the end': 'Alla fine',
    'Author': 'Autore',
    'Before current page': 'Prima della pagina corrente',
    'Bold': 'Grassetto',
    'Browse…': 'Sfoglia…',
    'Cannot Delete': 'Impossibile eliminare',
    'Cannot Export Images': 'Impossibile esportare le immagini',
    'Cannot Extract Pages': 'Impossibile estrarre le pagine',
    'Cannot Import Pages': 'Impossibile importare le pagine',
    'Cannot Insert Image': "Impossibile inserire l'immagine",
    'Cannot Merge Documents': 'Impossibile unire i documenti',
    'Cannot Open Document': 'Impossibile aprire il documento',
    'Cannot Recover Document': 'Impossibile recuperare il documento',
    'Cannot Redo': 'Impossibile ripetere',
    'Cannot Save Document': 'Impossibile salvare il documento',
    'Cannot Split Document': 'Impossibile dividere il documento',
    'Cannot Undo': 'Impossibile annullare',
    'Centre': 'Centro',
    'Choose an output folder': 'Scegli una cartella di destinazione',
    'Close (Esc)': 'Chiudi (Esc)',
    'Colour': 'Colore',
    'Commands': 'Comandi',
    'Comment': 'Commento',
    'Comment…': 'Commento…',
    'Copied {count} object(s).': 'Copiati {count} oggetti.',
    'Custom Zoom': 'Zoom personalizzato',
    'Cut {count} object(s).': 'Tagliati {count} oggetti.',
    'Delete Pages': 'Elimina pagine',
    'Discard All': 'Scarta tutto',
    'Document Properties': 'Proprietà del documento',
    'Document properties updated.': 'Proprietà del documento aggiornate.',
    'Drop a PDF file, or a PNG, JPEG or WEBP image.': (
        "Trascina un file PDF, o un'immagine PNG, JPEG o WEBP."
    ),
    'Export Pages Into': 'Esporta le pagine in',
    'Export Pages as Images': 'Esporta pagine come immagini',
    'Extract to New PDF…': 'Estrai in un nuovo PDF…',
    'Extracted {count} page(s) to {name}': 'Estratte {count} pagine in {name}',
    'Fill': 'Riempimento',
    'Fill Colour': 'Colore di riempimento',
    'Find': 'Trova',
    'Font': 'Carattere',
    'For example: 1-3, 7, 10-12': 'Per esempio: 1-3, 7, 10-12',
    'Format': 'Formato',
    'Geometry': 'Geometria',
    'Go to Page': 'Vai alla pagina',
    'Height': 'Altezza',
    'Images (*.png *.jpg *.jpeg *.webp);;All files (*)': (
        'Immagini (*.png *.jpg *.jpeg *.webp);;Tutti i file (*)'
    ),
    'Import Pages': 'Importa pagine',
    'Import Pages From': 'Importa pagine da',
    'Imported {count} page(s) from {name}': 'Importate {count} pagine da {name}',
    'Insert': 'Inserisci',
    'Insert Blank Page': 'Inserisci pagina vuota',
    'Insert Blank Page After': 'Inserisci pagina vuota dopo',
    'Italic': 'Corsivo',
    'Justify': 'Giustificato',
    'Keyboard Shortcuts': 'Scorciatoie da tastiera',
    'Keywords': 'Parole chiave',
    'Left': 'Sinistra',
    'Line spacing': 'Interlinea',
    'Lock aspect ratio': 'Blocca le proporzioni',
    'Merge Complete': 'Unione completata',
    'Merge PDF': 'Unisci PDF',
    'Merge…': 'Unisci…',
    'Move Down': 'Sposta giù',
    'Move Up': 'Sposta su',
    'New empty document created.': 'Creato un nuovo documento vuoto.',
    'Next match (Enter)': 'Risultato successivo (Invio)',
    'No changes to save.': 'Nessuna modifica da salvare.',
    'No colour': 'Nessun colore',
    'No matches': 'Nessun risultato',
    'No recent files': 'Nessun file recente',
    'Not Now': 'Non ora',
    'Note': 'Nota',
    'Opacity': 'Opacità',
    'Open PDF': 'Apri PDF',
    'Open a PDF with Ctrl+O, or drop one here.': 'Apri un PDF con Ctrl+O, o trascinane uno qui.',
    'Opened {name}': 'Aperto {name}',
    'Optional': 'Facoltativo',
    'Orion keyboard shortcuts': 'Scorciatoie da tastiera di Orion',
    'PDF documents (*.pdf)': 'Documenti PDF (*.pdf)',
    'PDF documents (*.pdf);;All files (*)': 'Documenti PDF (*.pdf);;Tutti i file (*)',
    'Page': 'Pagina',
    'Page Number Colour': 'Colore dei numeri di pagina',
    'Page Numbers': 'Numeri di pagina',
    'Pages to extract': 'Pagine da estrarre',
    'Password Required': 'Password richiesta',
    'Pasted {count} object(s).': 'Incollati {count} oggetti.',
    'Pen width': 'Spessore del tratto',
    'Position': 'Posizione',
    'Previous match (Shift+Enter)': 'Risultato precedente (Maiusc+Invio)',
    'Recover': 'Recupera',
    'Recover Unsaved Work': 'Recupera il lavoro non salvato',
    'Recovered document — use Save As to write it to a file.': (
        'Documento recuperato — usa Salva con nome per scriverlo su file.'
    ),
    'Redaction': 'Oscuramento',
    'Redaction Colour': "Colore dell'oscuramento",
    'Redid {what}': 'Ripetuto: {what}',
    'Remove': 'Rimuovi',
    'Remove the selected objects from the page': 'Rimuove dalla pagina gli oggetti selezionati',
    'Reset to natural size': 'Ripristina la dimensione originale',
    'Resolution': 'Risoluzione',
    'Right': 'Destra',
    'Rotate Left': 'Ruota a sinistra',
    'Rotate Right': 'Ruota a destra',
    'Rotation': 'Rotazione',
    'Save Extracted Pages': 'Salva le pagine estratte',
    'Save Merged PDF': 'Salva il PDF unito',
    'Save PDF As': 'Salva PDF con nome',
    'Save to': 'Salva in',
    'Saved {name}': 'Salvato {name}',
    'Search text…': 'Cerca testo…',
    'Select Colour': 'Scegli un colore',
    'Select PDF files to merge': 'Scegli i file PDF da unire',
    'Select Pages': 'Scegli le pagine',
    'Shape': 'Forma',
    'Size': 'Dimensione',
    'Split': 'Dividi',
    'Split Complete': 'Divisione completata',
    'Split PDF': 'Dividi PDF',
    'Split by page ranges': 'Dividi per intervalli di pagine',
    'Split every': 'Dividi ogni',
    'Start at': 'Inizia da',
    'Stroke': 'Contorno',
    'Stroke Colour': 'Colore del contorno',
    'Stroke width': 'Spessore del contorno',
    'Subject': 'Oggetto',
    'Text Colour': 'Colore del testo',
    'That is not a page range this document has.': (
        "Questo documento non ha quell'intervallo di pagine."
    ),
    'The clipboard has no Orion objects.': 'Negli appunti non ci sono oggetti di Orion.',
    'This font is embedded in the saved file.': (
        'Questo carattere viene incorporato nel file salvato.'
    ),
    'Title': 'Titolo',
    'Type a command…': 'Scrivi un comando…',
    'Type the text…': 'Scrivi il testo…',
    'US Legal (8.5 × 14 in)': 'US Legal (8,5 × 14 in)',
    'US Letter (8.5 × 11 in)': 'US Letter (8,5 × 11 in)',
    'Undid {what}': 'Annullato: {what}',
    'Unsaved Changes': 'Modifiche non salvate',
    'Watermark': 'Filigrana',
    'Watermark Colour': 'Colore della filigrana',
    'What the first numbered page is called': 'Come si chiama la prima pagina numerata',
    'Width': 'Larghezza',
    'Write your note…': 'Scrivi la tua nota…',
    'Add Text': 'Aggiungi testo',
    'Add Image': 'Aggiungi immagine',
    'Add Freehand': 'Aggiungi tratto libero',
    'Add Watermark': 'Aggiungi filigrana',
    'Add Page Numbers': 'Aggiungi numeri di pagina',
    'Delete Object': 'Elimina oggetto',
    'Edit Text': 'Modifica testo',
    'Edit Comment': 'Modifica commento',
    'Move': 'Sposta',
    'Resize': 'Ridimensiona',
    'Rotate': 'Ruota',
    'Duplicate': 'Duplica',
    'Paste': 'Incolla',
    'Cut': 'Taglia',
    'Bring to Front': 'Porta in primo piano',
    'Send to Back': 'Porta in secondo piano',
    'Insert Image': 'Inserisci immagine',
    'Extract Pages': 'Estrai pagine',
    'Reset Image Size': 'Ripristina dimensione immagine',
    'Change Colour': 'Cambia colore',
    'Change Font': 'Cambia carattere',
    'Change Font Size': 'Cambia dimensione del carattere',
    'Change Alignment': 'Cambia allineamento',
    'Change Opacity': 'Cambia opacità',
    'Change Geometry': 'Cambia geometria',
    'Change Fill Colour': 'Cambia colore di riempimento',
    'Change Stroke Colour': 'Cambia colore del contorno',
    'Change Stroke Width': 'Cambia spessore del contorno',
    'Change Line Spacing': 'Cambia interlinea',
    'Change Aspect Ratio': 'Cambia proporzioni',
    'Change Redaction Colour': "Cambia colore dell'oscuramento",
}
