"""Download the PM-JAY corpus into data/raw/.

Two transport problems this handles, both discovered the hard way:

1. TLS. nha.gov.in and several state health hosts present a chain that Windows
   trusts but certifi does not, so requests fails with CERTIFICATE_VERIFY_FAILED
   ("self-signed certificate in certificate chain"). truststore points Python at
   the OS trust store, which fixes it without disabling verification.

2. Dead URLs. The nha.gov.in/img/... paths in the project brief no longer serve
   PDFs -- the portal was rebuilt as a single-page app and those paths now return
   the app shell as HTTP 200 text/html. Each entry below records where the file
   actually comes from now; see PROVENANCE for what that means for citations.

Responses are checked for the %PDF magic bytes, which is what caught problem 2 --
an HTML error page with a 200 status would otherwise save as a corrupt "PDF".
"""

import time
from pathlib import Path

import requests

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - documented in requirements.txt
    print("WARN   truststore not installed; nha.gov.in will likely fail TLS verification")

OUT = Path("data/raw")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

# name -> (url, provenance)
#
# provenance is recorded because document version matters for this project: the
# empanelment pair is the whole point of the version-conflict test case, so a
# silently-different edition would corrupt the eval.
URLS = {
    # --- Core scheme documents ---
    "operation_manual.pdf": (
        "https://sha.kerala.gov.in/wp-content/uploads/2025/12/Operation-Manual-for-AB-PM-JAY-April-2022.pdf",
        "Kerala SHA mirror; April 2022 edition. NHA original 404s (SPA shell).",
    ),
    "hbp_2_2_manual.pdf": (
        "https://hem.nha.gov.in/HBP.pdf",
        "NHA HEM subdomain; the nha.gov.in/img path is dead.",
    ),
    "stg_manual.pdf": (
        "https://web.archive.org/web/20250214231529id_/https://nha.gov.in/img/pmjay-files/STG-Manual-Booklet-final.pdf",
        "Wayback capture 2025-02-14. No live mirror found.",
    ),
    "grievance_redressal.pdf": (
        "https://cgrms.pmjay.gov.in/GRMS/mainPage/AB%20PMJAY%20Grievance%20Redressal%20Guidelines.pdf",
        "PM-JAY CGRMS portal, live.",
    ),
    # --- Version-conflict pair: both needed, and they must stay distinguishable ---
    #
    # Named by edition rather than by the brief's labels. The brief calls the
    # NHA "Revised" file the newer of the pair, but the copy that survives on
    # mirrors is dated December 2021 -- older than the 21-12-2022 file it was
    # supposed to supersede. Encoding the edition in the filename keeps that
    # ambiguity visible in every citation instead of hiding it behind "revised".
    "empanelment_dec2021.pdf": (
        "https://www.nitiforstates.gov.in/public-assets/Policy/policy_files/GNC509Q000048.pdf",
        "NITI for States. 46pp, titled December 2021, no version number printed.",
    ),
    "empanelment_v2_0.pdf": (
        "https://sha.kerala.gov.in/wp-content/uploads/2020/07/Empanelment-guidelines-23.pdf",
        "Kerala SHA. 64pp, cover states 'Version - 2.0'. Self-labelled, so this is "
        "the more trustworthy half of the version pair.",
    ),
    # DELIBERATELY NOT DOWNLOADED: Hospital-Empanelment-Guidelines-21-12-22.pdf
    #
    #   https://web.archive.org/web/20240507232924id_/https://nha.gov.in/img/resources/Hospital-Empanelment-Guidelines-21-12-22.pdf
    #
    # The brief treats that file and Revised-Empanelment-and-De-empanelment-Guideline.pdf
    # as two conflicting versions. They are not: both were fetched and are byte-identical
    # (sha256 9B61270B..., 1,481,305 bytes) -- one document served under two names on
    # nha.gov.in. Indexing it would add ~65 duplicate chunks, skew retrieval, and make the
    # version-conflict eval cases meaningless by testing a document against itself.
    #
    # The genuine version conflict is empanelment_dec2021 (46pp) vs empanelment_v2_0 (64pp).
    # --- Anti-fraud cluster (all live at the brief's URLs) ---
    "antifraud_guidelines.pdf": (
        "https://ayushmanup.in/admin/Clients/Doc/79_Guidelines-Anti-Fraud-Guidelines.pdf",
        "UP Ayushman portal, live.",
    ),
    "antifraud_guidebook_2024.pdf": (
        "https://cdnbbsr.s3waas.gov.in/s3169779d3852b32ce8b1a1724dbf5217d/uploads/2024/09/20240924831436164.pdf",
        "S3WaaS CDN, live.",
    ),
    "field_investigation_manual.pdf": (
        "https://sha.kerala.gov.in/wp-content/uploads/2026/03/NHA_Field-Investigation-and-Medical-Audit-Manual_April-2020.pdf",
        "Kerala SHA, live.",
    ),
    # --- Process documents ---
    "beneficiary_identification.pdf": (
        "https://ayushmanup.in/admin/Clients/Doc/85_Guidelines-on-Process-of-Beneficiary-Identification.pdf",
        "UP Ayushman portal, live.",
    ),
    "fraud_analytics_rfe.pdf": (
        "https://web.archive.org/web/20251018221756id_/https://nha.gov.in/img/pmjay-files/RFE_fraud_Analytics_Services.pdf",
        "Wayback capture 2025-10-18; replay is flaky, may need retries.",
    ),
}


def fetch(url):
    """Return PDF bytes, or None if the response was not a PDF.

    Deliberately non-streaming: several of these hosts use chunked transfer
    encoding, and r.content decodes it correctly where a raw read does not.
    """
    r = requests.get(url, headers=HEADERS, timeout=180)
    r.raise_for_status()
    return r.content if r.content.startswith(b"%PDF") else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []

    for name, (url, _provenance) in URLS.items():
        dest = OUT / name
        if dest.exists() and dest.stat().st_size > 10_000:
            print(f"skip   {name}")
            continue

        for attempt in range(4):
            try:
                content = fetch(url)
                if content is None:
                    print(f"WARN   {name}: not a PDF (SPA shell? error page?)")
                    failed.append(name)
                    break
                dest.write_bytes(content)
                print(f"ok     {name}  ({len(content) // 1024} KB)")
                break
            except Exception as e:
                print(f"retry  {name} [{attempt + 1}/4]: {type(e).__name__}")
                # Wayback in particular 503s under load; back off rather than hammer.
                time.sleep(6 * (attempt + 1))
        else:
            print(f"FAILED {name}")
            failed.append(name)

    print(f"\n{len(URLS) - len(failed)}/{len(URLS)} present in {OUT}")
    if failed:
        print("missing: " + ", ".join(failed))
        print("re-run to retry, or fetch manually in a browser -- URLs in this file")


if __name__ == "__main__":
    main()
