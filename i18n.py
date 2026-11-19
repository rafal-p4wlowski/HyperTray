"""User interface language. English texts are the keys; tr() returns the
translation for the current language."""
from PyQt6.QtCore import QLocale

AUTO, ENGLISH, POLISH = "auto", "en", "pl"
LANGUAGES = ((AUTO, "System"), (ENGLISH, "English"), (POLISH, "Polski"))

_current = ENGLISH


def resolve(code):
    if code == AUTO:
        return POLISH if QLocale.system().name().lower().startswith("pl") else ENGLISH
    return code if code in (ENGLISH, POLISH) else ENGLISH


def set_language(code):
    global _current
    _current = resolve(code)


def tr(text):
    if _current == POLISH:
        return PL.get(text, text)
    return text


PL = {
    # --- tray ---
    "Looking for headset...": "Szukam słuchawek...",
    "Headset panel...": "Panel słuchawek...",
    "Quit": "Zakończ",
    "Settings": "Ustawienia",
    "Start with Windows": "Uruchamiaj z systemem Windows",
    "Battery refresh": "Odświeżanie baterii",
    "Language": "Język",
    "System": "Systemowy",
    "Version {}": "Wersja {}",
    "Dongle not found": "Nie znaleziono odbiornika",
    "Headset off / out of range": "Słuchawki wyłączone / poza zasięgiem",
    "Headset connected": "Słuchawki połączone",
    "Battery level: {}": "Poziom baterii: {}",
    "Charging status: {}": "Ładowanie: {}",
    "Estimated time left: {}": "Szacowany czas pracy: {}",
    "Time left: {}": "Pozostało: {}",
    "Microphone muted": "Mikrofon wyciszony",
    "Charging": "Ładuje się",
    "Not charging": "Nie ładuje się",
    "Fully charged": "Naładowane",
    "Charge error": "Błąd ładowania",

    # --- panel: general ---
    "HyperTray - Headset": "HyperTray - Słuchawki",
    "Status": "Stan",
    "Sound": "Dźwięk",
    "Headset": "Słuchawki",
    "Reload": "Odczytaj ponownie",
    "Read every setting from the headset again": "Odczytaj ponownie wszystkie ustawienia słuchawek",
    "Reading the headset...": "Odczytuję słuchawki...",
    "Saving...": "Zapisuję...",
    "Saved in the headset at {}": "Zapisano w słuchawkach o {}",
    "The headset did not take the change ({}). Is it on?": "Słuchawki nie przyjęły zmiany ({}). Czy są włączone?",
    "Connected": "Połączone",
    "battery {}%": "bateria {}%",
    "Yes": "Tak",
    "No": "Nie",

    # --- panel: status ---
    "Battery": "Bateria",
    "Connection": "Połączenie",
    "Charging state": "Ładowanie",
    "Time left": "Pozostały czas",
    "Cell voltage": "Napięcie ogniwa",
    "Battery history": "Historia baterii",
    "Green: charging. A gap: the headset was off.": "Zielony: ładowanie. Przerwa: słuchawki były wyłączone.",
    "24 h": "24 h",
    "7 days": "7 dni",
    "No battery readings in this period yet.": "Brak odczytów baterii w tym okresie.",

    # --- panel: sound ---
    "Microphone": "Mikrofon",
    "The microphone is unplugged.": "Mikrofon jest odłączony.",
    "Microphone volume (Windows)": "Głośność mikrofonu (Windows)",
    "Side tone": "Odsłuch mikrofonu",
    "Hear my own voice in the headphones": "Słyszę własny głos w słuchawkach",
    "Side tone volume": "Głośność odsłuchu",
    "Holding the mute button on the headset also switches the side tone.":
        "Przytrzymanie przycisku wyciszenia na słuchawkach też przełącza odsłuch.",
    "Headphones": "Słuchawki",
    "Headphone volume (Windows)": "Głośność słuchawek (Windows)",
    "Silent mode": "Tryb cichy",
    "Silent mode (no sound in the headphones)": "Tryb cichy (bez dźwięku w słuchawkach)",
    "Silences the headset itself; Windows still plays to it.":
        "Wycisza same słuchawki; Windows nadal wysyła do nich dźwięk.",
    "About the volumes": "O głośności",
    "The headset has no volume or microphone gain setting of its own. Like NGENUITY, "
    "the panel sets the volume of the headset's Windows audio devices.":
        "Słuchawki nie mają własnego ustawienia głośności ani czułości mikrofonu. Tak jak NGENUITY, "
        "panel ustawia głośność urządzeń audio słuchawek w Windows.",
    "The headset is not among the active Windows audio devices.":
        "Słuchawek nie ma wśród aktywnych urządzeń audio Windows.",

    # --- panel: headset ---
    "Automatic shutdown": "Automatyczne wyłączanie",
    "Switch the headset off when it has been idle for:": "Wyłącz słuchawki po bezczynności przez:",
    "{} min": "{} min",
    "Never": "Nigdy",
    "Device": "Urządzenie",
    "Model": "Model",
    "Colour": "Kolor",
    "Headset firmware": "Firmware słuchawek",
    "Dongle firmware": "Firmware odbiornika",
    "Headset ID": "Identyfikator słuchawek",
    "Black": "Czarny",
    "White": "Biały",
    "Black/Red": "Czarno-czerwony",
    "Pairing": "Parowanie",
    "If the headset no longer pairs with the dongle, the pairing key (SIRK) shared by both can be reset. "
    "Afterwards the headset may have to be paired again following its manual.":
        "Jeśli słuchawki przestały łączyć się z odbiornikiem, można zresetować wspólny klucz parowania (SIRK). "
        "Potem może być potrzebne ponowne sparowanie według instrukcji słuchawek.",
    "Pairing reset required: {}": "Wymagany reset parowania: {}",
    "Reset pairing (SIRK)...": "Resetuj parowanie (SIRK)...",
    "Reset headset pairing": "Reset parowania słuchawek",
    "This resets the pairing key (SIRK) shared by the headset and the dongle.\n\n"
    "The headset may disconnect from the dongle. If it does not reconnect, pair it "
    "again following the headset manual.\n\nThis feature is experimental. Continue?":
        "To zresetuje klucz parowania (SIRK) wspólny dla słuchawek i odbiornika.\n\n"
        "Słuchawki mogą się rozłączyć. Jeśli nie połączą się ponownie, sparuj je "
        "według instrukcji słuchawek.\n\nTa funkcja jest eksperymentalna. Kontynuować?",

    # --- panel: settings ---
    "A click on the tray icon opens this panel; the microphone can be muted from its menu.":
        "Kliknięcie ikony w zasobniku otwiera ten panel; mikrofon wyciszysz z jej menu.",
    "Mute, charging and power changes are shown at once; the refresh only follows the battery level.":
        "Wyciszenie, ładowanie i włączenie słuchawek widać od razu; odświeżanie dotyczy tylko poziomu baterii.",
}
