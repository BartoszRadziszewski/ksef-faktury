"""
ksef_auth.py - KSeF API 2.0 - uwierzytelnienie Tokenem KSeF
"""

import base64
import time
import logging

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

BASE_URLS = {
    "test": "https://api-test.ksef.mf.gov.pl/api/v2",
    "prod": "https://api.ksef.mf.gov.pl/api/v2",
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class KSeFAuthError(Exception):
    pass


class KSeFAuth:

    def __init__(self, nip: str, ksef_token: str, env: str = "test"):
        self.nip = nip
        self.ksef_token = ksef_token
        self.base_url = BASE_URLS.get(env, BASE_URLS["test"])
        self.access_token: str | None = None
        self.refresh_token: str | None = None

    def _get_public_key(self) -> bytes:
        url = f"{self.base_url}/security/public-key-certificates"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        self._raise_for_status(resp, "Błąd pobierania klucza publicznego")
        data = resp.json()
        logger.info(f"Klucz publiczny RAW: {str(data)[:400]}")

        certificates = data if isinstance(data, list) else data.get("certificates", [])
        if not certificates:
            raise KSeFAuthError("Brak certyfikatów w odpowiedzi KSeF")

        first = certificates[0]
        logger.info(f"Klucz — dostępne pola: {list(first.keys())}")
        der_b64 = first.get("certificate") or first.get("value") or first.get("publicKey") or ""
        if not der_b64:
            raise KSeFAuthError(f"Brak danych certyfikatu. Pola: {list(first.keys())}")
        return base64.b64decode(der_b64)

    def _get_challenge(self) -> dict:
        url = f"{self.base_url}/auth/challenge"
        resp = requests.post(url, json={}, headers=HEADERS, timeout=30)
        self._raise_for_status(resp, "Błąd pobierania challenge")
        data = resp.json()
        logger.info(f"Challenge RAW: {data}")
        return data

    def _encrypt_token(self, public_key_der: bytes, timestamp_ms: int) -> str:
        plaintext = f"{self.ksef_token}|{timestamp_ms}".encode("utf-8")
        try:
            public_key = serialization.load_der_public_key(public_key_der)
        except Exception:
            from cryptography import x509
            cert = x509.load_der_x509_certificate(public_key_der)
            public_key = cert.public_key()
        encrypted = public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(encrypted).decode("ascii")

    def _send_ksef_token(self, challenge: str, encrypted_token: str) -> dict:
        url = f"{self.base_url}/auth/ksef-token"
        body = {
            "challenge": challenge,
            "contextIdentifier": {"type": "Nip", "value": self.nip},
            "encryptedToken": encrypted_token,
        }
        resp = requests.post(url, json=body, headers=HEADERS, timeout=30)
        self._raise_for_status(resp, "Błąd wysyłania tokena KSeF")
        data = resp.json()
        logger.info(f"SendKsefToken RAW: {data}")
        return data

    def _wait_for_auth(self, reference_number: str, auth_token: str,
                       max_retries: int = 15, sleep_s: float = 1.5) -> None:
        url = f"{self.base_url}/auth/{reference_number}"
        bearer_headers = {**HEADERS, "Authorization": f"Bearer {auth_token}"}

        for attempt in range(1, max_retries + 1):
            resp = requests.get(url, headers=bearer_headers, timeout=30)
            logger.info(f"Auth HTTP {resp.status_code} (próba {attempt}): {resp.text[:300]}")

            if resp.status_code == 200:
                data = resp.json()
                # API 2.0: status = {"code": 200, "description": "..."}
                status_obj = data.get("status", {})
                status_code = status_obj.get("code", 0)

                if status_code == 200:
                    logger.info("✓ Uwierzytelnienie potwierdzone (kod 200)")
                    return
                if status_code >= 400:
                    desc = status_obj.get("description", "")
                    details = status_obj.get("details", [])
                    raise KSeFAuthError(
                        f"Uwierzytelnienie odrzucone (kod {status_code}): {desc} | {details}"
                    )
                logger.info(f"Auth w toku, status={status_code} (próba {attempt})...")

            elif resp.status_code == 202:
                logger.info(f"Auth w toku HTTP 202 (próba {attempt})...")

            time.sleep(sleep_s)

        raise KSeFAuthError("Przekroczono limit prób oczekiwania na uwierzytelnienie")

    def _redeem_token(self, auth_token: str) -> dict:
        url = f"{self.base_url}/auth/token/redeem"
        bearer_headers = {**HEADERS, "Authorization": f"Bearer {auth_token}"}
        resp = requests.post(url, json={}, headers=bearer_headers, timeout=30)
        self._raise_for_status(resp, "Błąd wymiany tokena na accessToken")
        data = resp.json()
        logger.info(f"Redeem RAW: {str(data)[:300]}")
        return data

    def authenticate(self) -> str:
        logger.info("Krok 1/6: Pobieranie klucza publicznego KSeF...")
        public_key_der = self._get_public_key()

        logger.info("Krok 2/6: Pobieranie challenge...")
        challenge_resp = self._get_challenge()
        logger.info(f"Challenge klucze: {list(challenge_resp.keys())}")

        challenge_id = (
            challenge_resp.get("challenge")
            or challenge_resp.get("referenceNumber")
            or challenge_resp.get("challengeKey")
        )
        if not challenge_id:
            raise KSeFAuthError(f"Brak challenge ID. Klucze: {list(challenge_resp.keys())}")

        timestamp_ms = (
            challenge_resp.get("timestampMs")
            or challenge_resp.get("timestamp")
            or int(time.time() * 1000)
        )
        logger.info(f"challenge={challenge_id} | timestampMs={timestamp_ms}")

        logger.info("Krok 3/6: Szyfrowanie tokena KSeF (RSA-OAEP SHA-256)...")
        encrypted_token = self._encrypt_token(public_key_der, timestamp_ms)

        logger.info("Krok 4/6: Wysyłanie zaszyfrowanego tokena...")
        auth_resp = self._send_ksef_token(challenge_id, encrypted_token)

        auth_ref = auth_resp.get("referenceNumber") or auth_resp.get("challenge") or challenge_id
        auth_token_value = (
            auth_resp.get("authenticationToken", {}).get("token")
            or auth_resp.get("token")
        )
        if not auth_token_value:
            raise KSeFAuthError(f"Brak authenticationToken. Klucze: {list(auth_resp.keys())}")

        logger.info("Krok 5/6: Oczekiwanie na potwierdzenie uwierzytelnienia...")
        self._wait_for_auth(auth_ref, auth_token_value)

        logger.info("Krok 6/6: Pobieranie accessToken (JWT)...")
        tokens = self._redeem_token(auth_token_value)
        # accessToken może być stringiem LUB obiektem {"token": "eyJ..."}
        access = tokens.get("accessToken") or tokens.get("token")
        if isinstance(access, dict):
            self.access_token = access.get("token")
        else:
            self.access_token = access

        refresh = tokens.get("refreshToken")
        if isinstance(refresh, dict):
            self.refresh_token = refresh.get("token")
        else:
            self.refresh_token = refresh

        if not self.access_token:
            raise KSeFAuthError(f"Brak accessToken. Klucze: {list(tokens.keys())}, wartość: {tokens.get('accessToken')}")

        logger.info("✓ Uwierzytelnienie zakończone sukcesem.")
        return self.access_token

    def refresh(self) -> str:
        if not self.refresh_token:
            raise KSeFAuthError("Brak refreshToken — wykonaj najpierw authenticate()")
        url = f"{self.base_url}/auth/token/refresh"
        resp = requests.post(url, json={"refreshToken": self.refresh_token}, headers=HEADERS, timeout=30)
        self._raise_for_status(resp, "Błąd odświeżania accessToken")
        data = resp.json()
        access = data.get("accessToken") or data.get("token")
        self.access_token = access.get("token") if isinstance(access, dict) else access
        refresh = data.get("refreshToken", self.refresh_token)
        self.refresh_token = refresh.get("token") if isinstance(refresh, dict) else refresh
        logger.info("✓ accessToken odświeżony.")
        return self.access_token

    def get_auth_headers(self) -> dict:
        if not self.access_token:
            raise KSeFAuthError("Brak accessToken — wykonaj najpierw authenticate()")
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    @staticmethod
    def _raise_for_status(resp: requests.Response, context: str) -> None:
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:500]
            raise KSeFAuthError(f"{context} — HTTP {resp.status_code}: {detail}")