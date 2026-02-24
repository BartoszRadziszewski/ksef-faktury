# KSeF API 2.0 — Pobieranie faktur do Excel

Skrypt Python pobierający faktury wystawione i otrzymane z produkcyjnego KSeF API 2.0
i zapisujący wyniki do pliku Excel (`.xlsx`) z podziałem na arkusze.

---

## Wymagania wstępne

| Wymaganie | Wersja | Uwagi |
|-----------|--------|-------|
| Python | 3.12+ | https://www.python.org/downloads/ |
| Token KSeF | — | Wygenerowany w Module Certyfikatów i Uprawnień |

**Jak wygenerować Token KSeF:**
1. Zaloguj się na https://ksef.podatki.gov.pl
2. Przejdź do: Moduł Certyfikatów i Uprawnień → Tokeny
3. Utwórz token z uprawnieniem **InvoiceRead**
4. Skopiuj wygenerowany ciąg znaków — wkleisz go do pliku `.env`

---

## Instalacja automatyczna (zalecana)

Uruchom plik `instaluj.bat` — skrypt automatycznie:
- Tworzy środowisko wirtualne Python (venv)
- Instaluje wszystkie zależności
- Tworzy gotowy plik `.env` do uzupełnienia

```
instaluj.bat
```

Po uruchomieniu zostaniesz zapytany o katalog docelowy.
Domyślnie: `C:\ksef_faktury`

---

## Instalacja ręczna

```bat
:: 1. Przejdź do wybranego katalogu
cd C:\ksef_faktury

:: 2. Utwórz środowisko wirtualne
python -m venv venv

:: 3. Aktywuj środowisko
venv\Scripts\activate

:: 4. Zainstaluj zależności
pip install -r requirements.txt
```

---

## Konfiguracja

Uzupełnij plik `.env` (tworzony automatycznie przez `instaluj.bat`):

```ini
KSEF_NIP=522.......          # NIP firmy (bez kresek)
KSEF_TOKEN=eyJ...            # Token KSeF z uprawnieniem InvoiceRead
KSEF_ENV=prod                # prod = produkcja, test = środowisko testowe
DATE_FROM=2026-02-01         # Początek zakresu dat (format: YYYY-MM-DD)
DATE_TO=2026-12-31           # Koniec zakresu dat
PAGE_SIZE=100                # Liczba faktur na stronę (zalecane: 100)
```

> **Uwaga:** Plik `.env` zawiera dane wrażliwe. Nie udostępniaj go nikomu.

---

## Uruchomienie

```bat
:: Aktywuj środowisko (jeśli nieaktywne)
venv\Scripts\activate

:: Uruchom skrypt
python main.py
```

Lub bez aktywacji:
```bat
venv\Scripts\python main.py
```

---

## Czas działania i limity API

KSeF API 2.0 narzuca limit **20 zapytań na godzinę** dla endpointu `/invoices/query/metadata`.

| Zakres dat | Liczba okien | Szac. czas |
|------------|-------------|------------|
| 3 miesiące | 2 | ~7 min |
| 1 rok | 8 | ~28 min |
| 2 lata | 16 | ~56 min |
| 4 lata (2022–2026) | 34 | ~1h 58min |

Skrypt automatycznie:
- Dzieli zakres na okna 3-miesięczne
- Czeka 185 s między oknami (limit API)
- Odświeża token bez utraty postępu gdy wygaśnie (~45 min)
- Obsługuje błędy 429 (Too Many Requests) z odczytem `Retry-After`
- Wyświetla szacowany czas do końca

---

## Wynik

Plik `faktury_ksef.xlsx` tworzony w katalogu skryptu, z arkuszami:

| Arkusz | Zawartość |
|--------|-----------|
| **Wystawione** | Faktury sprzedaży (Subject1) |
| **Otrzymane** | Faktury zakupów (Subject2) |
| **Podsumowanie** | Liczba faktur, zakres dat, NIP |

Kolumny w arkuszach:
- Typ faktury, Numer KSeF, Numer faktury, Rodzaj faktury
- Data wystawienia, Data przyjęcia w KSeF
- Wystawca (nazwa, NIP), Nabywca (nazwa, NIP)
- Kwota netto, VAT, brutto, Waluta

---

## Struktura plików

```
katalog_instalacji\
├── main.py              # Główny skrypt
├── ksef_auth.py         # Uwierzytelnienie (6-krokowy flow RSA-OAEP)
├── ksef_invoices.py     # Pobieranie faktur (okna 3-miesięczne, rate limiting)
├── requirements.txt     # Zależności Python
├── .env                 # Konfiguracja (uzupełnij po instalacji)
├── .env.example         # Szablon konfiguracji
└── venv\                # Środowisko wirtualne (tworzone przez instalator)
```

---

## Zależności

| Pakiet | Wersja | Zastosowanie |
|--------|--------|--------------|
| requests | 2.32.3 | Zapytania HTTP do KSeF API |
| cryptography | 43.0.3 | Szyfrowanie tokena RSA-OAEP SHA-256 |
| python-dotenv | 1.0.1 | Wczytywanie pliku `.env` |
| openpyxl | 3.1.5 | Zapis do pliku Excel |
| python-dateutil | 2.9.0 | Obliczanie okien 3-miesięcznych |

---

## Rozwiązywanie problemów

### `ModuleNotFoundError: No module named 'dateutil'`
```bat
venv\Scripts\pip install python-dateutil
```

### HTTP 401 przy pierwszym zapytaniu
Skrypt automatycznie ponawia uwierzytelnienie. Jeśli problem się powtarza — sprawdź ważność tokena KSeF w Module Certyfikatów i Uprawnień.

### HTTP 429 — Too Many Requests
Skrypt automatycznie czeka tyle sekund ile wskazuje nagłówek `Retry-After`.
Jeśli pojawia się regularnie — zwiększ wartość `SLEEP_BETWEEN_WINDOWS` w `ksef_invoices.py` (domyślnie: 185 s).

### Błąd uwierzytelnienia — HTTP 400/401 przy kroku 4
Sprawdź czy token KSeF ma uprawnienie **InvoiceRead** i nie jest wygasły.
